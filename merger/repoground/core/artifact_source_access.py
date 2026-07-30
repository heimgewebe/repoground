"""Pinned artifact source reads, fingerprints and cache-currency checks.

Extracted from bundle_access as a T011 residual slice so integrity validation and
bounded source loads are not entangled with call-navigation orchestration.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from threading import RLock
from typing import Any

from merger.repoground.core.bounded_artifact_read import (
    MAX_REGISTERED_ARTIFACT_BYTES,
    ArtifactSourceFingerprint,
    LoadedArtifactSource,
    declared_artifact_integrity,
    file_identity,
    read_stable_regular_file_bytes,
)
from merger.repoground.core.bundle_identity import is_bundle_manifest
from merger.repoground.core.bundle_roles import (
    resolve_unique_artifact,
)
from merger.repoground.core.citation_projection import (
    is_non_empty_string,
)
from merger.repoground.core.manifest_snapshot import (
    MAX_MANIFEST_BYTES,
    active_manifest_snapshot,
    resolve_manifest_path,
)

logger = logging.getLogger(__name__)

CACHE_VALIDATION_ENV = "REPOGROUND_CACHE_VALIDATION"
STRICT_SOURCE_HASH_ENV = "REPOGROUND_STRICT_CACHE_HASH"

_CACHE_VALIDATION_LOCK = RLock()
_WARNED_INVALID_CACHE_VALIDATION_VALUES: set[str] = set()

def _stat_identity_is_strong(stat_result: os.stat_result) -> bool:
    return all(
        value != 0
        for value in (
            stat_result.st_dev,
            stat_result.st_ino,
            stat_result.st_mtime_ns,
            stat_result.st_ctime_ns,
        )
    )


def _stat_matches_identity(
    stat_result: os.stat_result,
    *,
    device: int,
    inode: int,
    size: int,
    mtime_ns: int,
    ctime_ns: int,
) -> bool:
    def available(expected: int, observed: int) -> bool:
        return expected == 0 or observed == expected

    return (
        available(device, stat_result.st_dev)
        and available(inode, stat_result.st_ino)
        and stat_result.st_size == size
        and available(mtime_ns, stat_result.st_mtime_ns)
        and available(ctime_ns, stat_result.st_ctime_ns)
    )


def _manifest_stat_matches_fingerprint(
    fingerprint: ArtifactSourceFingerprint,
    stat_result: os.stat_result,
) -> bool:
    return _stat_matches_identity(
        stat_result,
        device=fingerprint.manifest_device,
        inode=fingerprint.manifest_inode,
        size=fingerprint.manifest_size,
        mtime_ns=fingerprint.manifest_mtime_ns,
        ctime_ns=fingerprint.manifest_ctime_ns,
    )


def _artifact_stat_matches_fingerprint(
    fingerprint: ArtifactSourceFingerprint,
    stat_result: os.stat_result,
) -> bool:
    return _stat_matches_identity(
        stat_result,
        device=fingerprint.device,
        inode=fingerprint.inode,
        size=fingerprint.size,
        mtime_ns=fingerprint.mtime_ns,
        ctime_ns=fingerprint.ctime_ns,
    )


def _fingerprint_matches_active_manifest_snapshot(
    fingerprint: ArtifactSourceFingerprint,
) -> bool | None:
    snapshot = active_manifest_snapshot(fingerprint.manifest_path)
    if snapshot is None:
        return None
    return fingerprint.manifest_sha256 == snapshot.binding.sha256


def _manifest_source_is_current(
    fingerprint: ArtifactSourceFingerprint,
) -> bool:
    active_match = _fingerprint_matches_active_manifest_snapshot(fingerprint)
    if active_match is not None:
        return active_match
    raw, current, failure, _detail = _read_stable_regular_file_bytes(
        Path(fingerprint.manifest_path)
    )
    if failure is not None or raw is None or current is None:
        return False
    return (
        _manifest_stat_matches_fingerprint(fingerprint, current)
        and hashlib.sha256(raw).hexdigest() == fingerprint.manifest_sha256
    )


def _artifact_bytes_match_fingerprint(
    fingerprint: ArtifactSourceFingerprint,
    artifact_path: Path,
) -> bool:
    artifact_bytes, artifact_stat, failure, _detail = _read_stable_artifact_bytes(
        artifact_path
    )
    if failure is not None or artifact_bytes is None or artifact_stat is None:
        return False
    if not _artifact_stat_matches_fingerprint(fingerprint, artifact_stat):
        return False
    if hashlib.sha256(artifact_bytes).hexdigest() != fingerprint.artifact_sha256:
        return False
    try:
        artifact_after_stat = artifact_path.stat()
    except OSError:
        return False
    return _artifact_stat_matches_fingerprint(
        fingerprint,
        artifact_after_stat,
    )


def _bound_artifact_source_is_current(
    fingerprint: ArtifactSourceFingerprint,
    artifact_path: Path,
    *,
    requires_content: bool,
) -> bool:
    if not requires_content:
        try:
            artifact_stat = artifact_path.stat()
        except OSError:
            return False
        if _stat_identity_is_strong(artifact_stat):
            return _artifact_stat_matches_fingerprint(
                fingerprint,
                artifact_stat,
            )
    return _artifact_bytes_match_fingerprint(fingerprint, artifact_path)


def _fast_artifact_source_validation(
    fingerprint: ArtifactSourceFingerprint,
    manifest_path: Path,
    artifact_path: Path,
) -> bool | None:
    try:
        manifest_stat = manifest_path.stat()
        artifact_stat = artifact_path.stat()
    except OSError:
        return False
    if not (
        _stat_identity_is_strong(manifest_stat)
        and _stat_identity_is_strong(artifact_stat)
    ):
        return None
    return _manifest_stat_matches_fingerprint(
        fingerprint,
        manifest_stat,
    ) and _artifact_stat_matches_fingerprint(fingerprint, artifact_stat)


def _source_bytes_match_fingerprint(
    fingerprint: ArtifactSourceFingerprint,
    manifest_path: Path,
    artifact_path: Path,
) -> bool:
    manifest_bytes, manifest_stat, manifest_failure, _manifest_detail = (
        _read_stable_regular_file_bytes(manifest_path)
    )
    if (
        manifest_failure is not None
        or manifest_bytes is None
        or manifest_stat is None
        or not _manifest_stat_matches_fingerprint(fingerprint, manifest_stat)
        or hashlib.sha256(manifest_bytes).hexdigest() != fingerprint.manifest_sha256
    ):
        return False
    if not _artifact_bytes_match_fingerprint(fingerprint, artifact_path):
        return False
    try:
        manifest_after_stat = manifest_path.stat()
    except OSError:
        return False
    return _manifest_stat_matches_fingerprint(
        fingerprint,
        manifest_after_stat,
    )


def _cache_validation_mode() -> str:
    """Return the cache-validation mode while preserving legacy semantics.

    ``REPOGROUND_CACHE_VALIDATION`` accepts only ``auto`` and ``strict``.
    Any other non-empty value falls back to ``strict`` and is logged once per
    distinct invalid value. The legacy
    ``REPOGROUND_STRICT_CACHE_HASH`` switch remains supported when the
    new variable is unset or empty: unset/empty/0/false/no/off means ``auto``;
    every other non-empty legacy value means ``strict``.
    """
    configured_raw = os.environ.get(CACHE_VALIDATION_ENV, "")
    configured = configured_raw.strip().lower()
    if configured in {"auto", "strict"}:
        return configured
    if configured:
        with _CACHE_VALIDATION_LOCK:
            if configured_raw not in _WARNED_INVALID_CACHE_VALIDATION_VALUES:
                _WARNED_INVALID_CACHE_VALIDATION_VALUES.add(configured_raw)
                logger.warning(
                    "Invalid %s value %r; falling back to strict cache validation",
                    CACHE_VALIDATION_ENV,
                    configured_raw,
                )
        return "strict"

    legacy = os.environ.get(
        STRICT_SOURCE_HASH_ENV, ""
    ).strip().lower()
    if legacy in {"", "0", "false", "no", "off"}:
        return "auto"
    return "strict"


def _source_identity_is_strong(
    fingerprint: ArtifactSourceFingerprint,
) -> bool:
    """Whether metadata can support the fast warm-cache validation path."""
    return all(
        value != 0
        for value in (
            fingerprint.manifest_device,
            fingerprint.manifest_inode,
            fingerprint.manifest_mtime_ns,
            fingerprint.manifest_ctime_ns,
            fingerprint.device,
            fingerprint.inode,
            fingerprint.mtime_ns,
            fingerprint.ctime_ns,
        )
    )


def _source_content_verification_required(
    fingerprint: ArtifactSourceFingerprint,
    *,
    verify_content: bool,
) -> bool:
    return (
        verify_content
        or _cache_validation_mode() == "strict"
        or not _source_identity_is_strong(fingerprint)
    )


def _read_stable_artifact_bytes(
    artifact_path: Path,
) -> tuple[bytes | None, os.stat_result | None, str | None, str | None]:
    return read_stable_regular_file_bytes(
        artifact_path,
        max_bytes=MAX_REGISTERED_ARTIFACT_BYTES,
    )


def _read_stable_regular_file_bytes(
    path: Path,
    *,
    max_bytes: int = MAX_MANIFEST_BYTES,
) -> tuple[bytes | None, os.stat_result | None, str | None, str | None]:
    return read_stable_regular_file_bytes(path, max_bytes=max_bytes)


def _read_artifact_manifest_source(
    manifest_path: Path,
) -> tuple[
    bytes | None,
    Any,
    tuple[int, int, int, int, int] | None,
    str | None,
    str | None,
]:
    snapshot = active_manifest_snapshot(manifest_path)
    if snapshot is not None:
        identity = snapshot.file_identity
        return (
            snapshot.raw,
            snapshot.json_object(),
            (identity[0], identity[1], identity[3], identity[4], identity[5]),
            None,
            None,
        )
    raw, manifest_stat, failure, detail = _read_stable_regular_file_bytes(
        manifest_path
    )
    if failure == "too_large":
        failure = "manifest_too_large"
    if failure is not None:
        return None, None, None, failure, detail
    assert raw is not None and manifest_stat is not None
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, None, None, "unreadable", str(exc)
    if (
        not is_bundle_manifest(manifest)
        or not is_non_empty_string(manifest.get("run_id"))
        or not isinstance(manifest.get("artifacts"), list)
    ):
        return (
            None,
            None,
            None,
            "manifest_invalid",
            "bundle manifest identity, run_id, or artifacts are invalid",
        )
    return raw, manifest, file_identity(manifest_stat), None, None


def _read_registered_artifact_source(
    manifest_path: Path, role: str
) -> tuple[
    LoadedArtifactSource | None,
    dict[str, Any] | None,
    str | None,
    str | None,
]:
    manifest_bytes, manifest, manifest_identity, failure, detail = (
        _read_artifact_manifest_source(manifest_path)
    )
    if failure is not None:
        return None, None, failure, detail
    assert manifest_bytes is not None and manifest_identity is not None
    if not isinstance(manifest, dict):
        return None, None, "unreadable", "bundle manifest must be a JSON object"
    try:
        artifact_payload, artifact, resolution_failure = resolve_unique_artifact(
            manifest_path,
            manifest,
            role,
        )
    except ValueError as exc:
        return None, None, "unreadable", str(exc)
    if resolution_failure is not None:
        return None, artifact, resolution_failure, None
    assert artifact_payload is not None and artifact is not None
    artifact_path = Path(artifact["absolute_path"])
    declared_bytes, declared_sha256, integrity_failure = (
        declared_artifact_integrity(artifact_payload)
    )
    if integrity_failure is not None:
        return None, artifact, integrity_failure, None
    raw, artifact_stat, failure, detail = _read_stable_artifact_bytes(artifact_path)
    if failure is not None:
        return None, artifact, failure, detail
    assert raw is not None and artifact_stat is not None
    if declared_bytes is not None and declared_bytes != len(raw):
        return None, artifact, "bytes_mismatch", None
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if declared_sha256 is not None and actual_sha256 != declared_sha256:
        return None, artifact, "sha256_mismatch", None
    fingerprint = ArtifactSourceFingerprint(
        manifest_path=str(resolve_manifest_path(manifest_path)),
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        manifest_device=manifest_identity[0],
        manifest_inode=manifest_identity[1],
        manifest_size=manifest_identity[2],
        manifest_mtime_ns=manifest_identity[3],
        manifest_ctime_ns=manifest_identity[4],
        role=role,
        absolute_path=str(artifact_path),
        artifact_sha256=actual_sha256,
        device=artifact_stat.st_dev,
        inode=artifact_stat.st_ino,
        size=artifact_stat.st_size,
        mtime_ns=artifact_stat.st_mtime_ns,
        ctime_ns=artifact_stat.st_ctime_ns,
    )
    if not _manifest_source_is_current(fingerprint):
        return None, artifact, "source_changed", None
    return (
        LoadedArtifactSource(
            manifest=manifest,
            artifact=artifact,
            raw=raw,
            fingerprint=fingerprint,
        ),
        artifact,
        None,
        None,
    )


def _artifact_source_is_current(
    fingerprint: ArtifactSourceFingerprint,
    *,
    verify_content: bool = False,
) -> bool:
    """Validate one cached generation without reparsing its JSON payload.

    Cold loads and post-build checks always hash bytes read from one pinned file
    descriptor. Request-bound lookups authorize the cached manifest hash only
    from the active snapshot and never from transient path bytes. Other warm
    lookups use the manifest hash plus strong file identity metadata.
    ``REPOGROUND_CACHE_VALIDATION=strict`` forces a full hash on every lookup;
    the legacy strict-hash switch remains supported. Weak identities such as
    zero device or inode values automatically use strict validation.
    """
    manifest_path = Path(fingerprint.manifest_path)
    artifact_path = Path(fingerprint.absolute_path)
    active_manifest_match = _fingerprint_matches_active_manifest_snapshot(fingerprint)
    if active_manifest_match is False:
        return False

    requires_content = _source_content_verification_required(
        fingerprint,
        verify_content=verify_content,
    )
    if active_manifest_match is True:
        return _bound_artifact_source_is_current(
            fingerprint,
            artifact_path,
            requires_content=requires_content,
        )

    if not requires_content:
        fast_validation = _fast_artifact_source_validation(
            fingerprint,
            manifest_path,
            artifact_path,
        )
        if fast_validation is not None:
            return fast_validation
    return _source_bytes_match_fingerprint(
        fingerprint,
        manifest_path,
        artifact_path,
    )

