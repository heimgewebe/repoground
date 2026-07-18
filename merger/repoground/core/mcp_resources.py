from __future__ import annotations

from .bundle_identity import is_bundle_manifest

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from merger.repoground.core import bundle_access

KIND = "repoground.mcp.resource_read"
LIST_KIND = "repoground.mcp.resource_list"
LEGACY_KIND = "repobrief.mcp.resource_read"
LEGACY_LIST_KIND = "repobrief.mcp.resource_list"
VERSION = "v1"
RESOURCE_PREFIX = "repoground://snapshot/"
LEGACY_RESOURCE_PREFIX = "repobrief://snapshot/"
MANIFEST_SUFFIX = ".bundle.manifest.json"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_RESOURCE_BYTES = 16 * 1024 * 1024
_SHA256_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
FIXED_RESOURCE_KINDS = {
    "manifest": "bundle_manifest",
    "canonical": "canonical_md",
    "reading-pack": "agent_reading_pack",
    "health": "post_emit_health",
    "availability": "availability_model",
}
FORBIDDEN_OPERATIONS = [
    "git_push",
    "git_pull",
    "git_fetch",
    "create_pr",
    "apply_patch",
    "run_shell",
    "auto_review",
    "auto_fix",
    "auto_merge",
    "secret_read",
    "snapshot_create_side_effect",
]
DOES_NOT_ESTABLISH = [
    "truth",
    "correctness",
    "completeness",
    "runtime_behavior",
    "test_sufficiency",
    "regression_absence",
    "repo_understood",
    "claims_true",
    "forensic_ready",
    "review_complete",
    "pr_mergeable",
    "mcp_server_available",
    "transport_security",
    "authentication_correctness",
]


class RepoGroundMcpResourceError(ValueError):
    """Raised for invalid RepoGround MCP resource addresses."""


def _read_only_boundary() -> dict[str, Any]:
    return {
        "writes": [],
        "does_not_mutate": [
            "git",
            "pull_requests",
            "patches",
            "source_working_tree",
            "brief_bundle_artifacts",
            "secrets",
        ],
        "read_paths_do_not_refresh": True,
        "does_not_create_snapshots": True,
        "forbidden_operations": list(FORBIDDEN_OPERATIONS),
    }


def _manifest_stem(path: Path) -> str:
    name = path.name
    if name.endswith(MANIFEST_SUFFIX):
        return name[: -len(MANIFEST_SUFFIX)]
    return path.stem


def _bytes_issue(status: str, reason: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"status": status, "reason": reason}
    issue.update(extra)
    return issue


def _read_bounded_bytes(
    path: Path,
    *,
    max_bytes: int,
    too_large_reason: str,
    unavailable_reason: str = "artifact file unavailable",
) -> tuple[bytes | None, dict[str, Any] | None]:
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
    except OSError as exc:
        return None, _bytes_issue("missing", f"{unavailable_reason}: {exc}")
    if len(data) > max_bytes:
        return None, _bytes_issue(
            "blocked",
            too_large_reason,
            bytes_lower_bound=len(data),
            max_bytes=max_bytes,
        )
    return data, None


def _decode_json_bytes(
    data: bytes,
    *,
    invalid_utf8_reason: str = "artifact is not valid UTF-8 text",
    invalid_json_reason: str | None = None,
) -> tuple[str | None, Any | None, dict[str, Any] | None]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, None, _bytes_issue("blocked", invalid_utf8_reason)
    try:
        return text, json.loads(text), None
    except json.JSONDecodeError:
        if invalid_json_reason is not None:
            return text, None, _bytes_issue("blocked", invalid_json_reason)
        return text, None, None


def _bundle_manifest_validation_issue(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or not path.name.endswith(MANIFEST_SUFFIX):
        return _bytes_issue("blocked", "bundle root is not a RepoLens bundle manifest file")
    data, issue = _read_bounded_bytes(
        path,
        max_bytes=MAX_MANIFEST_BYTES,
        too_large_reason="bundle manifest exceeds MCP manifest size limit",
        unavailable_reason="bundle manifest unavailable",
    )
    if issue is not None:
        return issue
    assert data is not None
    _text, parsed, parse_issue = _decode_json_bytes(
        data,
        invalid_utf8_reason="bundle manifest is not valid UTF-8 text",
        invalid_json_reason="bundle manifest is not valid JSON",
    )
    if parse_issue is not None:
        return parse_issue
    if not isinstance(parsed, dict):
        return _bytes_issue("blocked", "bundle manifest must be a JSON object")
    if (
        not is_bundle_manifest(parsed)
        or not isinstance(parsed.get("run_id"), str)
        or not isinstance(parsed.get("artifacts"), list)
    ):
        return _bytes_issue("blocked", "bundle root is not a valid RepoLens bundle manifest")
    return None


def _is_bundle_manifest_file(path: Path) -> bool:
    return _bundle_manifest_validation_issue(path) is None


def _manifest_candidates(bundle_root: str | Path) -> list[Path]:
    root = Path(bundle_root).expanduser().resolve()
    if root.is_file():
        return [root] if _is_bundle_manifest_file(root) else []
    if not root.exists() or not root.is_dir():
        return []
    return [path for path in sorted(root.glob(f"*{MANIFEST_SUFFIX}")) if _is_bundle_manifest_file(path)]


def _find_manifest(bundle_root: str | Path, stem: str) -> Path | None:
    for path in _manifest_candidates(bundle_root):
        if _manifest_stem(path) == stem:
            return path
    return None


def _bundle_root_file_issue(bundle_root: str | Path, stem: str) -> dict[str, Any] | None:
    root = Path(bundle_root).expanduser().resolve()
    if not root.exists() or not root.is_file():
        return None
    if not root.name.endswith(MANIFEST_SUFFIX):
        return _bundle_manifest_validation_issue(root)
    root_stem = _manifest_stem(root)
    if root_stem != stem:
        return _bytes_issue(
            "blocked",
            "bundle root file stem does not match requested snapshot stem",
            bundle_root_stem=root_stem,
            requested_stem=stem,
        )
    return _bundle_manifest_validation_issue(root)


def _resource_uri(stem: str, suffix: str) -> str:
    return f"{RESOURCE_PREFIX}{stem}/{suffix}"


def _parse_resource_uri(uri: str) -> tuple[str, str, str | None]:
    parsed = urlparse(uri)
    if parsed.scheme not in {"repoground", "repobrief"} or parsed.netloc != "snapshot":
        raise RepoGroundMcpResourceError(
            "resource URI must start with repoground://snapshot/ "
            "(legacy repobrief://snapshot/ remains accepted temporarily)"
        )
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise RepoGroundMcpResourceError("resource URI must include snapshot stem and resource name")
    stem, resource_name = parts[0], parts[1]
    if not stem or ".." in stem or "/" in stem:
        raise RepoGroundMcpResourceError("resource stem is invalid")
    if resource_name == "artifact":
        if len(parts) != 3 or not parts[2] or "/" in parts[2] or ".." in parts[2]:
            raise RepoGroundMcpResourceError("artifact resource URI must include one artifact role")
        return stem, resource_name, parts[2]
    if len(parts) != 2 or resource_name not in FIXED_RESOURCE_KINDS:
        raise RepoGroundMcpResourceError("unsupported RepoGround MCP resource URI")
    return stem, resource_name, None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _artifact_integrity_issue(data: bytes, artifact: dict[str, Any]) -> dict[str, Any] | None:
    expected_bytes = artifact.get("bytes")
    if not isinstance(expected_bytes, int):
        return _bytes_issue("integrity_unavailable", "artifact byte size is missing or invalid in manifest")
    actual_bytes = len(data)
    if actual_bytes != expected_bytes:
        return _bytes_issue(
            "integrity_mismatch",
            "artifact byte size does not match manifest",
            expected_bytes=expected_bytes,
            actual_bytes=actual_bytes,
        )
    expected_sha256 = artifact.get("sha256")
    if not isinstance(expected_sha256, str) or not _SHA256_RE.fullmatch(expected_sha256):
        return _bytes_issue("integrity_unavailable", "artifact sha256 is missing or invalid in manifest")
    expected_sha256_normalized = expected_sha256.lower()
    actual_sha256 = _sha256_bytes(data)
    if actual_sha256 != expected_sha256_normalized:
        return _bytes_issue(
            "integrity_mismatch",
            "artifact sha256 does not match manifest",
            expected_sha256=expected_sha256,
            actual_sha256=actual_sha256,
        )
    return None


def _apply_artifact_bytes(result: dict[str, Any], data: bytes) -> dict[str, Any]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        result["binary_unreadable"] = True
        return result
    result["content_text"] = text
    try:
        result["content_json"] = json.loads(text)
    except json.JSONDecodeError:
        pass
    return result


def _read_manifest_content(result: dict[str, Any], manifest: Path) -> dict[str, Any]:
    data, issue = _read_bounded_bytes(
        manifest,
        max_bytes=MAX_MANIFEST_BYTES,
        too_large_reason="bundle manifest exceeds MCP manifest size limit",
        unavailable_reason="bundle manifest unavailable",
    )
    if issue is not None:
        result.update(issue)
        return result
    assert data is not None
    return _apply_artifact_bytes(result, data)


def _context_for_manifest(manifest: Path | None, *, reason: str | None = None) -> dict[str, Any]:
    if manifest is None:
        return {
            "health": {"status": "unknown", "reason": reason or "manifest unavailable"},
            "freshness": {"status": "unknown", "reason": reason or "manifest unavailable"},
            "availability": {"status": "unknown", "reason": reason or "manifest unavailable"},
        }
    status = bundle_access.snapshot_status(manifest)
    health = bundle_access.get_artifact(manifest, "post_emit_health")
    availability_model = status.get("availability_model")
    freshness = status.get("freshness")
    return {
        "health": {
            "status": health.get("status", "unknown"),
            "artifact": health.get("artifact"),
        },
        "freshness": freshness if isinstance(freshness, dict) else {"status": "unknown"},
        "availability": availability_model if isinstance(availability_model, dict) else {"status": "unknown"},
    }


def _base_result(uri: str, manifest: Path | None, *, status: str, reason: str | None = None) -> dict[str, Any]:
    legacy_identity = urlparse(uri).scheme == "repobrief"
    return {
        "kind": KIND,
        "version": VERSION,
        "uri": uri,
        "identity": {
            "canonical_prefix": RESOURCE_PREFIX,
            "legacy_prefix_used": legacy_identity,
            "legacy_prefix": LEGACY_RESOURCE_PREFIX if legacy_identity else None,
        },
        "status": status,
        "bundle_manifest": str(manifest) if manifest else None,
        "snapshot_context": _context_for_manifest(manifest, reason=reason),
        "mutation_boundary": _read_only_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _safe_bundle_file(manifest: Path, artifact: dict[str, Any]) -> Path | None:
    raw_absolute_path = artifact.get("absolute_path")
    if not isinstance(raw_absolute_path, str) or not raw_absolute_path:
        return None
    path = Path(raw_absolute_path).expanduser().resolve()
    try:
        path.relative_to(manifest.parent.resolve())
    except ValueError:
        return None
    return path


def _read_artifact_resource(uri: str, manifest: Path, role: str) -> dict[str, Any]:
    if role == "bundle_manifest":
        result = _base_result(uri, manifest, status="available")
        result.update({
            "resource_role": "bundle_manifest",
            "content_type": "application/json",
            "artifact_ref": {
                "role": "bundle_manifest",
                "path": manifest.name,
                "absolute_path": str(manifest),
                "file_exists": manifest.is_file(),
                "bytes": manifest.stat().st_size if manifest.is_file() else None,
            },
        })
        return _read_manifest_content(result, manifest)

    ref = bundle_access.get_artifact(manifest, role)
    result = _base_result(uri, manifest, status=ref.get("status", "unknown"))
    result.update({"resource_role": role, "artifact_ref": ref.get("artifact")})
    artifact = ref.get("artifact")
    if not isinstance(artifact, dict) or not artifact.get("path"):
        result["reason"] = f"artifact role not available: {role}"
        return result
    path = _safe_bundle_file(manifest, artifact)
    if path is None:
        result["status"] = "blocked"
        result["reason"] = f"artifact path escapes bundle root for role: {role}"
        return result
    if not path.is_file():
        result["status"] = "missing"
        result["reason"] = f"artifact file missing: {path}"
        return result
    data, read_issue = _read_bounded_bytes(
        path,
        max_bytes=MAX_RESOURCE_BYTES,
        too_large_reason="artifact exceeds MCP resource size limit",
    )
    if read_issue is not None:
        result.update(read_issue)
        return result
    assert data is not None
    integrity_issue = _artifact_integrity_issue(data, artifact)
    if integrity_issue is not None:
        result.update(integrity_issue)
        return result
    result["content_type"] = artifact.get("content_type") or "application/octet-stream"
    return _apply_artifact_bytes(result, data)


def resource_templates() -> dict[str, Any]:
    return {
        "kind": "repoground.mcp.resource_templates",
        "version": VERSION,
        "templates": [
            "repoground://snapshot/{stem}/manifest",
            "repoground://snapshot/{stem}/canonical",
            "repoground://snapshot/{stem}/reading-pack",
            "repoground://snapshot/{stem}/health",
            "repoground://snapshot/{stem}/availability",
            "repoground://snapshot/{stem}/artifact/{role}",
        ],
        "legacy_templates": [
            "repobrief://snapshot/{stem}/manifest",
            "repobrief://snapshot/{stem}/canonical",
            "repobrief://snapshot/{stem}/reading-pack",
            "repobrief://snapshot/{stem}/health",
            "repobrief://snapshot/{stem}/availability",
            "repobrief://snapshot/{stem}/artifact/{role}",
        ],
        "mutation_boundary": _read_only_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def list_mcp_resources(bundle_root: str | Path) -> dict[str, Any]:
    resources: list[dict[str, Any]] = []
    for manifest in _manifest_candidates(bundle_root):
        stem = _manifest_stem(manifest)
        for suffix in ("manifest", "canonical", "reading-pack", "health", "availability"):
            resources.append({"uri": _resource_uri(stem, suffix), "snapshot_stem": stem, "resource": suffix})
        for role in bundle_access.available_roles(manifest):
            resources.append({
                "uri": _resource_uri(stem, f"artifact/{role}"),
                "snapshot_stem": stem,
                "resource": "artifact",
                "role": role,
            })
    return {
        "kind": LIST_KIND,
        "version": VERSION,
        "status": "ok",
        "bundle_root": str(Path(bundle_root).expanduser().resolve()),
        "resources": resources,
        "templates": resource_templates()["templates"],
        "legacy_templates": resource_templates()["legacy_templates"],
        "mutation_boundary": _read_only_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def read_mcp_resource(uri: str, *, bundle_root: str | Path) -> dict[str, Any]:
    stem, resource_name, role = _parse_resource_uri(uri)
    manifest = _find_manifest(bundle_root, stem)
    if manifest is None:
        bundle_root_issue = _bundle_root_file_issue(bundle_root, stem)
        if bundle_root_issue is not None:
            result = _base_result(uri, None, status=bundle_root_issue["status"], reason=bundle_root_issue["reason"])
            result.update(bundle_root_issue)
            return result
        return _base_result(uri, None, status="missing", reason=f"snapshot stem not found: {stem}")
    if resource_name == "manifest":
        return _read_artifact_resource(uri, manifest, "bundle_manifest")
    if resource_name == "availability":
        result = _base_result(uri, manifest, status="available")
        result.update({
            "resource_role": "availability_model",
            "content_type": "application/json",
            "content_json": result["snapshot_context"]["availability"],
            "content_text": json.dumps(result["snapshot_context"]["availability"], indent=2, sort_keys=True) + "\n",
        })
        return result
    if resource_name == "artifact":
        assert role is not None
        return _read_artifact_resource(uri, manifest, role)
    mapped_role = FIXED_RESOURCE_KINDS[resource_name]
    return _read_artifact_resource(uri, manifest, mapped_role)


# Bounded source-compatibility aliases. New code imports RepoGround names.
RepoBriefMcpResourceError = RepoGroundMcpResourceError
