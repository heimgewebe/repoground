"""Precomputed, revision-bound Flake evidence for offline agent consumption.

The producer is the existing Git-only flake_revision_relations. The persisted
document is not a second index, scheduler or mutable cache: it is a portable
content-addressed artifact. Reading must not open any source repository.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from .flake_input_relations import flake_revision_relations

KIND = "repoground.flake_relation_evidence_pack"
VERSION = "1.0"
_MAX_BYTES = 2 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def prepare_flake_evidence_pack(
    source_root: str | Path, source_commit: str, *, source_repo: str,
    targets: dict[str, tuple[str | Path, str]],
) -> dict[str, Any]:
    """Compute once from exact Git objects; fail on unresolved target revisions."""
    result = flake_revision_relations(
        source_root, source_commit, source_repo=source_repo, targets=targets,
    )
    pins = sorted(
        [{"repo_id": name, "commit": revision}
         for name, (_, revision) in targets.items()],
        key=lambda item: (item["repo_id"], item["commit"]),
    )
    if not pins or result["source_commit"] != source_commit:
        raise ValueError("source revision or target pins are unverified")
    if result["status"] not in {"ok", "partial"}:
        raise ValueError("unsupported producer status")
    envelope = {
        "kind": KIND, "version": VERSION,
        "source_repo": source_repo, "source_commit": source_commit,
        "target_pins": pins, "evidence": result,
        "read_contract": {
            "no_git_access": True, "no_network_access": True,
            "revision_exact": True, "asserts_runtime_dependency": False,
            "absence_means_no_proof_not_no_dependency": True,
        },
    }
    envelope["pack_sha256"] = _digest(envelope)
    payload = _canonical(envelope)
    if len(payload) > _MAX_BYTES:
        raise ValueError("cross-repository evidence exceeds bounded pack size")
    return envelope


def write_flake_evidence_pack(path: str | Path, pack: dict[str, Any]) -> None:
    """Create only an absent regular artifact; never replace a live generation."""
    target = Path(path)
    read_flake_evidence_pack_payload(pack)
    payload = _canonical(pack) + b"\n"
    if len(payload) > _MAX_BYTES:
        raise ValueError("pack too large")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("pack parent must be an existing directory")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def _valid_target_pin(item: object) -> bool:
    if not isinstance(item, dict) or set(item) != {"repo_id", "commit"}:
        return False
    return (
        isinstance(item["repo_id"], str)
        and _REPO.fullmatch(item["repo_id"]) is not None
        and isinstance(item["commit"], str)
        and _SHA.fullmatch(item["commit"]) is not None
    )


def _validate_target_pins(pins: object) -> None:
    if not isinstance(pins, list) or not 1 <= len(pins) <= 16:
        raise ValueError("invalid ordered target pins")
    if any(not _valid_target_pin(item) for item in pins):
        raise ValueError("invalid ordered target pins")
    if (
        pins != sorted(pins, key=lambda item: (item["repo_id"], item["commit"]))
        or len({item["repo_id"] for item in pins}) != len(pins)
    ):
        raise ValueError("invalid ordered target pins")


def _validate_producer_evidence(
    evidence: object, *, source_repo: str, source_commit: str,
) -> None:
    if (
        not isinstance(evidence, dict)
        or evidence.get("kind") != "repoground.flake-revision-relations"
        or evidence.get("version") != "1"
        or evidence.get("source_repo") != source_repo
        or evidence.get("source_commit") != source_commit
        or evidence.get("status") not in {"ok", "partial"}
        or not isinstance(evidence.get("relations"), list)
        or not isinstance(evidence.get("gaps"), list)
        or not isinstance(evidence.get("evidence_sha256"), str)
        or not _DIGEST.fullmatch(evidence["evidence_sha256"])
        or _digest({k: v for k, v in evidence.items() if k != "evidence_sha256"})
        != evidence["evidence_sha256"]
    ):
        raise ValueError("corrupt or unbound producer evidence")
    for edge in evidence["relations"]:
        if (
            not isinstance(edge, dict)
            or edge.get("evidence_level") != "S1"
            or edge.get("resolution_status") != "resolved"
            or edge.get("asserts_runtime_dependency") is not False
        ):
            raise ValueError("invalid evidence level or runtime claim")


def read_flake_evidence_pack_payload(
    pack: Any, *, expected_repo: str | None = None,
    expected_commit: str | None = None,
) -> dict[str, Any]:
    if not isinstance(pack, dict) or set(pack) != {
        "kind", "version", "source_repo", "source_commit", "target_pins",
        "evidence", "read_contract", "pack_sha256",
    }:
        raise ValueError("invalid flake evidence pack fields")
    if pack["kind"] != KIND or pack["version"] != VERSION:
        raise ValueError("unsupported flake evidence pack contract")
    if (
        not isinstance(pack["source_repo"], str)
        or not _REPO.fullmatch(pack["source_repo"])
        or not isinstance(pack["source_commit"], str)
        or not _SHA.fullmatch(pack["source_commit"])
    ):
        raise ValueError("invalid source identity")
    if expected_repo is not None and expected_repo != pack["source_repo"]:
        raise ValueError("pack source repo does not match expected identity")
    if expected_commit is not None and expected_commit != pack["source_commit"]:
        raise ValueError("pack source revision does not match expected identity")
    _validate_target_pins(pack["target_pins"])
    _validate_producer_evidence(
        pack["evidence"], source_repo=pack["source_repo"],
        source_commit=pack["source_commit"],
    )
    contract = pack["read_contract"]
    if contract != {
        "no_git_access": True, "no_network_access": True,
        "revision_exact": True, "asserts_runtime_dependency": False,
        "absence_means_no_proof_not_no_dependency": True,
    }:
        raise ValueError("unknown read contract")
    expected_digest = pack["pack_sha256"]
    if not isinstance(expected_digest, str) or not _DIGEST.fullmatch(expected_digest):
        raise ValueError("missing pack integrity digest")
    if _digest({k: v for k, v in pack.items() if k != "pack_sha256"}) != expected_digest:
        raise ValueError("pack integrity mismatch")
    return pack


def read_flake_evidence_pack(
    path: str | Path, *, expected_repo: str,
    expected_commit: str,
    expected_file_sha256: str | None = None,
) -> dict[str, Any]:
    """Only the referenced bounded immutable document is read; never Git."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_BYTES:
            raise ValueError("evidence pack is not a bounded regular file")
        payload = handle.read(_MAX_BYTES + 1)
    if len(payload) > _MAX_BYTES:
        raise ValueError("evidence pack exceeded maximum size")
    if expected_file_sha256 is not None and hashlib.sha256(payload).hexdigest() != expected_file_sha256:
        raise ValueError("manifest artifact SHA-256 does not match selected bytes")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("malformed evidence pack JSON") from exc
    return read_flake_evidence_pack_payload(
        value, expected_repo=expected_repo, expected_commit=expected_commit,
    )


def read_flake_evidence_from_manifest(
    manifest_path: str | Path, *, expected_repo: str,
    expected_commit: str, expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Read the already sealed role in a selected immutable bundle, never Git."""
    from merger.repoground.core.manifest_snapshot import manifest_snapshot

    snapshot = manifest_snapshot(manifest_path)
    if (
        expected_manifest_sha256 is not None
        and snapshot.binding.sha256 != expected_manifest_sha256
    ):
        raise ValueError("bundle manifest differs from selected digest")
    document = snapshot.json_object()
    provenance = document.get("snapshot_provenance")
    sources = provenance.get("repositories") if isinstance(provenance, dict) else None
    if not isinstance(sources, list) or not any(
        isinstance(item, dict)
        and item.get("git_commit") == expected_commit
        and item.get("git_dirty") is False
        and _remote_matches_repo(item.get("repo_remote"), expected_repo)
        for item in sources
    ):
        raise ValueError("bundle source revision or repository remote is unverified")
    artifacts = document.get("artifacts")
    roles = [
        row for row in (artifacts if isinstance(artifacts, list) else [])
        if isinstance(row, dict) and row.get("role") == "flake_relation_evidence_json"
    ]
    if len(roles) != 1:
        raise ValueError("bundle lacks exactly one Flake evidence artifact")
    row = roles[0]
    contract = row.get("contract")
    if contract != {"id": KIND, "version": VERSION}:
        raise ValueError("bundle Flake role has an incompatible contract")
    relative = row.get("path")
    if (
        not isinstance(relative, str)
        or not relative or relative.startswith("/")
        or "\\" in relative or "\x00" in relative
        or any(segment in ("", ".", "..") for segment in relative.split("/"))
    ):
        raise ValueError("bundle Flake artifact path is not canonical")
    root = snapshot.resolved_path.parent.resolve(strict=True)
    candidate = root / relative
    if candidate.is_symlink() or candidate.resolve(strict=True).parent != root:
        raise ValueError("bundle Flake artifact escapes immutable generation")
    digest = row.get("sha256")
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise ValueError("bundle Flake artifact SHA-256 is missing")
    if not isinstance(row.get("bytes"), int) or row["bytes"] > _MAX_BYTES:
        raise ValueError("bundle Flake artifact size is invalid")
    pack = read_flake_evidence_pack(
        candidate, expected_repo=expected_repo, expected_commit=expected_commit,
        expected_file_sha256=digest,
    )
    if candidate.stat().st_size != row["bytes"]:
        raise ValueError("bundle Flake artifact byte count changed")
    return pack


def _remote_matches_repo(remote: Any, repo: str) -> bool:
    if not isinstance(remote, str) or not _REPO.fullmatch(repo):
        return False
    return remote in {
        f"git@github.com:{repo}.git",
        f"git@github.com:{repo}",
        f"https://github.com/{repo}.git",
        f"https://github.com/{repo}",
    }
