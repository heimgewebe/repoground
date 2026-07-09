from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from merger.lenskit.core import repobrief_access

KIND = "repobrief.mcp.resource_read"
LIST_KIND = "repobrief.mcp.resource_list"
VERSION = "v1"
RESOURCE_PREFIX = "repobrief://snapshot/"
MANIFEST_SUFFIX = ".bundle.manifest.json"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_RESOURCE_BYTES = 16 * 1024 * 1024
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


class RepoBriefMcpResourceError(ValueError):
    """Raised for invalid MCP resource addresses."""


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


def _is_bundle_manifest_file(path: Path) -> bool:
    if not path.is_file() or not path.name.endswith(MANIFEST_SUFFIX):
        return False
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(data, dict)
        and data.get("kind") == "repolens.bundle.manifest"
        and isinstance(data.get("run_id"), str)
        and isinstance(data.get("artifacts"), list)
    )


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


def _resource_uri(stem: str, suffix: str) -> str:
    return f"{RESOURCE_PREFIX}{stem}/{suffix}"


def _parse_resource_uri(uri: str) -> tuple[str, str, str | None]:
    parsed = urlparse(uri)
    if parsed.scheme != "repobrief" or parsed.netloc != "snapshot":
        raise RepoBriefMcpResourceError("resource URI must start with repobrief://snapshot/")
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise RepoBriefMcpResourceError("resource URI must include snapshot stem and resource name")
    stem, resource_name = parts[0], parts[1]
    if not stem or ".." in stem or "/" in stem:
        raise RepoBriefMcpResourceError("resource stem is invalid")
    if resource_name == "artifact":
        if len(parts) != 3 or not parts[2] or "/" in parts[2] or ".." in parts[2]:
            raise RepoBriefMcpResourceError("artifact resource URI must include one artifact role")
        return stem, resource_name, parts[2]
    if len(parts) != 2 or resource_name not in FIXED_RESOURCE_KINDS:
        raise RepoBriefMcpResourceError("unsupported RepoBrief MCP resource URI")
    return stem, resource_name, None


def _artifact_size_issue(path: Path) -> dict[str, Any] | None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        return {"status": "missing", "reason": f"artifact file unavailable: {exc}"}
    if size > MAX_RESOURCE_BYTES:
        return {
            "status": "blocked",
            "reason": "artifact exceeds MCP resource size limit",
            "bytes": size,
            "max_bytes": MAX_RESOURCE_BYTES,
        }
    return None


def _artifact_text(path: Path) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None]:
    size_issue = _artifact_size_issue(path)
    if size_issue is not None:
        return None, None, size_issue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None, None, None
    try:
        return text, json.loads(text), None
    except json.JSONDecodeError:
        return text, None, None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_integrity_issue(path: Path, artifact: dict[str, Any]) -> dict[str, Any] | None:
    expected_bytes = artifact.get("bytes")
    if isinstance(expected_bytes, int):
        actual_bytes = path.stat().st_size
        if actual_bytes != expected_bytes:
            return {
                "status": "integrity_mismatch",
                "reason": "artifact byte size does not match manifest",
                "expected_bytes": expected_bytes,
                "actual_bytes": actual_bytes,
            }
    expected_sha256 = artifact.get("sha256")
    if isinstance(expected_sha256, str) and expected_sha256:
        actual_sha256 = _sha256(path)
        if actual_sha256 != expected_sha256:
            return {
                "status": "integrity_mismatch",
                "reason": "artifact sha256 does not match manifest",
                "expected_sha256": expected_sha256,
                "actual_sha256": actual_sha256,
            }
    return None


def _apply_artifact_content(result: dict[str, Any], path: Path) -> dict[str, Any]:
    text, parsed, issue = _artifact_text(path)
    if issue is not None:
        result.update(issue)
        return result
    if text is not None:
        result["content_text"] = text
    else:
        result["binary_unreadable"] = True
    if parsed is not None:
        result["content_json"] = parsed
    return result


def _context_for_manifest(manifest: Path | None, *, reason: str | None = None) -> dict[str, Any]:
    if manifest is None:
        return {
            "health": {"status": "unknown", "reason": reason or "manifest unavailable"},
            "freshness": {"status": "unknown", "reason": reason or "manifest unavailable"},
            "availability": {"status": "unknown", "reason": reason or "manifest unavailable"},
        }
    status = repobrief_access.snapshot_status(manifest)
    health = repobrief_access.get_artifact(manifest, "post_emit_health")
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
    return {
        "kind": KIND,
        "version": VERSION,
        "uri": uri,
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
        return _apply_artifact_content(result, manifest)

    ref = repobrief_access.get_artifact(manifest, role)
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
    size_issue = _artifact_size_issue(path)
    if size_issue is not None:
        result.update(size_issue)
        return result
    integrity_issue = _artifact_integrity_issue(path, artifact)
    if integrity_issue is not None:
        result.update(integrity_issue)
        return result
    result["content_type"] = artifact.get("content_type") or "application/octet-stream"
    return _apply_artifact_content(result, path)


def resource_templates() -> dict[str, Any]:
    return {
        "kind": "repobrief.mcp.resource_templates",
        "version": VERSION,
        "templates": [
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
        for role in repobrief_access.available_roles(manifest):
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
        "mutation_boundary": _read_only_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def read_mcp_resource(uri: str, *, bundle_root: str | Path) -> dict[str, Any]:
    stem, resource_name, role = _parse_resource_uri(uri)
    manifest = _find_manifest(bundle_root, stem)
    if manifest is None:
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
