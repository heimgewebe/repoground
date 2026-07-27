"""Shared validation for post-emit health records bound to one bundle manifest."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

_SHA256_LEN = 64


def _is_lower_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LEN
        and all(char in "0123456789abcdef" for char in value)
    )


def _resolve(path: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve()


def _hash_binding_status(
    post_doc: Mapping[str, Any],
    manifest_sha256: str | None,
) -> tuple[str, str, bool]:
    declared_sha256 = post_doc.get("bundle_manifest_sha256")
    if declared_sha256 is None:
        return "pass", "post_emit_health has no manifest hash binding", False
    if not _is_lower_sha256(declared_sha256):
        return "fail", "post_emit_health bundle_manifest_sha256 is invalid", True
    if manifest_sha256 is None:
        return (
            "blocked",
            "requested manifest could not be hashed for post_emit_health binding",
            True,
        )
    if declared_sha256 != manifest_sha256:
        return (
            "fail",
            "post_emit_health bundle_manifest_sha256 does not match requested manifest",
            True,
        )
    return "pass", "post_emit_health hash matches requested manifest", True


def post_health_binding_status(
    post_doc: Mapping[str, Any],
    *,
    resolved_manifest: Path,
    manifest_run_id: Any,
    manifest_sha256: str | None,
) -> tuple[str, str]:
    """Validate path/hash/run bindings for one post-emit health record."""
    post_manifest_path = post_doc.get("bundle_manifest_path")
    if not isinstance(post_manifest_path, str) or not post_manifest_path:
        return "blocked", "post_emit_health missing bundle_manifest_path binding"
    hash_status, hash_detail, hash_bound = _hash_binding_status(
        post_doc, manifest_sha256
    )
    if hash_status != "pass":
        return hash_status, hash_detail
    path_bound = _resolve(post_manifest_path) == resolved_manifest.resolve()
    if not path_bound and not hash_bound:
        return (
            "fail",
            "post_emit_health bundle_manifest_path does not match requested manifest",
        )
    if isinstance(manifest_run_id, str):
        post_bundle_run_id = post_doc.get("bundle_run_id")
        if not isinstance(post_bundle_run_id, str) or not post_bundle_run_id:
            return "blocked", "post_emit_health missing bundle_run_id binding"
        if post_bundle_run_id != manifest_run_id:
            return (
                "fail",
                "post_emit_health bundle_run_id does not match manifest run_id",
            )
    if path_bound and hash_bound:
        return (
            "pass",
            "post_emit_health path-bound and hash-verified against requested manifest",
        )
    if path_bound:
        return "pass", "post_emit_health path-bound to requested manifest"
    return "pass", "post_emit_health hash-bound to requested manifest bytes"
