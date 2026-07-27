"""Bounded descriptor reads and manifest-declared artifact integrity contracts."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_REGISTERED_ARTIFACT_BYTES = 256 * 1024 * 1024
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class ArtifactSourceFingerprint:
    manifest_path: str
    manifest_sha256: str
    manifest_device: int
    manifest_inode: int
    manifest_size: int
    manifest_mtime_ns: int
    manifest_ctime_ns: int
    role: str
    absolute_path: str
    artifact_sha256: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True, slots=True)
class LoadedArtifactSource:
    manifest: dict[str, Any]
    artifact: dict[str, Any]
    raw: bytes
    fingerprint: ArtifactSourceFingerprint


def file_identity(
    stat_result: os.stat_result,
) -> tuple[int, int, int, int, int]:
    return (
        stat_result.st_dev,
        stat_result.st_ino,
        stat_result.st_size,
        stat_result.st_mtime_ns,
        stat_result.st_ctime_ns,
    )


def file_identity_matches(left: os.stat_result, right: os.stat_result) -> bool:
    left_identity = file_identity(left)
    right_identity = file_identity(right)
    if left.st_dev and left.st_ino and right.st_dev and right.st_ino:
        return left_identity == right_identity
    return left_identity[2:] == right_identity[2:]


def declared_artifact_integrity(
    artifact: dict[str, Any],
    *,
    max_bytes: int = MAX_REGISTERED_ARTIFACT_BYTES,
) -> tuple[int | None, str | None, str | None]:
    """Validate size/hash metadata before opening a potentially hostile path."""
    declared_bytes = artifact.get("bytes")
    declared_sha256 = artifact.get("sha256")
    if declared_bytes is None and declared_sha256 is None:
        # Legacy bundle manifests may omit both. The loader still derives and
        # pins the actual bounded bytes/hash; partial metadata is never accepted.
        return None, None, None
    if (
        not isinstance(declared_bytes, int)
        or isinstance(declared_bytes, bool)
        or declared_bytes < 0
        or not isinstance(declared_sha256, str)
        or _SHA256_RE.fullmatch(declared_sha256) is None
    ):
        return None, None, "integrity_unavailable"
    if declared_bytes > max_bytes:
        return None, None, "too_large"
    return declared_bytes, declared_sha256, None


def _read_descriptor_bytes(
    path: Path,
    max_bytes: int,
) -> tuple[
    bytes | None,
    os.stat_result | None,
    os.stat_result | None,
    str | None,
    str | None,
]:
    try:
        path_before = os.lstat(path)
        if stat.S_ISLNK(path_before.st_mode):
            return (
                None,
                None,
                None,
                "unreadable",
                "source path is a symbolic link",
            )
        if not stat.S_ISREG(path_before.st_mode):
            return (
                None,
                None,
                None,
                "unreadable",
                "source is not a regular file",
            )
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            stat_before = os.fstat(stream.fileno())
            if not stat.S_ISREG(stat_before.st_mode):
                return (
                    None,
                    None,
                    None,
                    "unreadable",
                    "source is not a regular file",
                )
            if not file_identity_matches(path_before, stat_before):
                return None, None, None, "source_changed", None
            if stat_before.st_size > max_bytes:
                return None, None, None, "too_large", None
            raw = stream.read(max_bytes + 1)
            stat_after = os.fstat(stream.fileno())
    except FileNotFoundError:
        return None, None, None, "file_missing", None
    except OSError as exc:
        return None, None, None, "unreadable", str(exc)
    return raw, stat_before, stat_after, None, None


def read_stable_regular_file_bytes(
    path: Path,
    *,
    max_bytes: int,
) -> tuple[bytes | None, os.stat_result | None, str | None, str | None]:
    """Read at most ``max_bytes`` from one stable regular-file descriptor."""
    if (
        not isinstance(max_bytes, int)
        or isinstance(max_bytes, bool)
        or max_bytes < 0
    ):
        raise ValueError("max_bytes must be a non-negative integer")
    raw, stat_before, stat_after, failure, detail = _read_descriptor_bytes(
        path,
        max_bytes,
    )
    if failure is not None:
        return None, None, failure, detail
    assert raw is not None and stat_before is not None and stat_after is not None
    if len(raw) > max_bytes:
        return None, None, "too_large", None
    if not file_identity_matches(stat_before, stat_after):
        return None, None, "source_changed", None
    if len(raw) != stat_after.st_size:
        return None, None, "source_changed", "source bytes were truncated"
    try:
        current_lstat = os.lstat(path)
        current_stat = path.stat()
    except OSError as exc:
        return None, None, "source_changed", str(exc)
    if (
        stat.S_ISLNK(current_lstat.st_mode)
        or not file_identity_matches(stat_after, current_lstat)
        or not file_identity_matches(stat_after, current_stat)
    ):
        return None, None, "source_changed", None
    return raw, stat_after, None, None
