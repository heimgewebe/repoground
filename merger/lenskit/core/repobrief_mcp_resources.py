from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from merger.lenskit.core import repobrief_access

KIND = "repobrief.mcp.resource_read"
LIST_KIND = "repobrief.mcp.resource_list"
VERSION = "v1"
RESOURCE_PREFIX = "repobrief://snapshot/"
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
    suffix = ".bundle.manifest.json"
    if name.endswith(suffix):
        return name[: -len(suffix)]
    return path.stem


def _manifest_candidates(bundle_root: str | Path) -> list[Path]:
    root = Path(bundle_root).expanduser().resolve()
    if root.is_file():
        return [root]
    if not root.exists():
        return []
    return sorted(root.glob("*.bundle.manifest.json"))


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


def _artifact_text(path: Path) -> tuple[str | None, dict[str, Any] | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None, None
    try:
        return text, json.loads(text)
    except json.JSONDecodeError:
        return text, None


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


def _read_artifact_resource(uri: str, manifest: Path, role: str) -> dict[str, Any]:
    ref = repobrief_access.get_artifact(manifest, role)
    result = _base_result(uri, manifest, status=ref.get("status", "unknown"))
    result.update({"resource_role": role, "artifact_ref": ref.get("artifact")})
    artifact = ref.get("artifact")
    if not isinstance(artifact, dict) or not artifact.get("path"):
        result["reason"] = f"artifact role not available: {role}"
        return result
    raw_path = Path(str(artifact["path"])).expanduser()
    path = raw_path if raw_path.is_absolute() else (manifest.parent / raw_path)
    path = path.resolve()
    if not path.is_file():
        result["status"] = "missing"
        result["reason"] = f"artifact file missing: {path}"
        return result
    text, parsed = _artifact_text(path)
    result["content_type"] = artifact.get("content_type") or "application/octet-stream"
    if text is not None:
        result["content_text"] = text
    else:
        result["binary_unreadable"] = True
    if parsed is not None:
        result["content_json"] = parsed
    return result


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
        text, parsed = _artifact_text(manifest)
        result = _base_result(uri, manifest, status="available")
        result.update({"resource_role": "bundle_manifest", "content_type": "application/json"})
        if text is not None:
            result["content_text"] = text
        if parsed is not None:
            result["content_json"] = parsed
        return result
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
