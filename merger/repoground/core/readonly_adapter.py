"""Protocol-neutral, fail-closed access to existing RepoGround bundles.

The adapter is deliberately narrower than the RepoGround CLI and independent of
MCP transport.  Its configuration names exact bundle manifests beneath explicit
roots.  Reads never discover repositories, refresh snapshots, invoke Git, or
write bundle state.
"""

from __future__ import annotations

from .bundle_identity import is_bundle_manifest

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from merger.repoground.core import bundle_access

KIND = "repobrief.readonly_adapter_response"
VERSION = "1.0"
CONFIG_KIND = "repobrief.readonly_adapter_config"
CONFIG_VERSION = "1.0"
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

WORKBENCH_ROLES = frozenset(
    {
        "agent_entry_manifest_json",
        "agent_reading_pack",
        "architecture_graph_json",
        "chunk_index_jsonl",
        "citation_map_jsonl",
        "claim_evidence_map_json",
        "concept_cards_jsonl",
        "lens_cards_jsonl",
        "python_symbol_index_json",
        "relation_cards_jsonl",
        "required_reading_protocol_json",
    }
)
RUNTIME_ROLES = frozenset(
    {
        "agent_export_gate",
        "availability_model",
        "bundle_surface_validation",
        "export_safety_report",
        "output_health",
        "post_emit_health",
    }
)
FORBIDDEN_OPERATIONS = (
    "clone_repository",
    "git_fetch",
    "git_pull",
    "git_push",
    "run_shell",
    "create_snapshot",
    "refresh_snapshot",
    "write_bundle",
    "apply_patch",
    "create_pull_request",
    "read_secrets",
)
DOES_NOT_ESTABLISH = (
    "truth",
    "correctness",
    "completeness",
    "runtime_behavior",
    "test_sufficiency",
    "regression_absence",
    "repository_understanding",
    "freshness_against_remote",
    "review_completeness",
    "merge_readiness",
    "agent_quality_improvement",
    "atomic protection against a hostile process that replaces and restores an index between integrity checks",
)


class RepoGroundReadonlyAdapterError(ValueError):
    """Raised when adapter configuration is invalid or escapes its boundary."""


@dataclass(frozen=True)
class SnapshotRegistration:
    snapshot_id: str
    manifest: Path


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


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RepoGroundReadonlyAdapterError(f"{label} does not exist: {path}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RepoGroundReadonlyAdapterError(f"{label} is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise RepoGroundReadonlyAdapterError(f"{label} must be a JSON object: {path}")
    return value


def _within(path: Path, roots: tuple[Path, ...]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        return True
    return False


def _resolve_config_path(base: Path, raw: Any, *, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise RepoGroundReadonlyAdapterError(f"{label} must be a non-empty path string")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def _validate_manifest(path: Path) -> None:
    if not path.is_file() or not path.name.endswith(".bundle.manifest.json"):
        raise RepoGroundReadonlyAdapterError(
            f"snapshot manifest is not a RepoGround bundle manifest file: {path}"
        )
    document = _json_object(path, label="snapshot manifest")
    if (
        not is_bundle_manifest(document)
        or not isinstance(document.get("run_id"), str)
        or not isinstance(document.get("artifacts"), list)
    ):
        raise RepoGroundReadonlyAdapterError(
            f"snapshot manifest has an invalid RepoGround identity: {path}"
        )


def _base_response(
    action: str,
    *,
    status: str,
    snapshot_id: str | None = None,
    manifest: Path | None = None,
) -> dict[str, Any]:
    return {
        "kind": KIND,
        "version": VERSION,
        "action": action,
        "status": status,
        "snapshot_id": snapshot_id,
        "bundle_manifest": str(manifest) if manifest else None,
        "mutation_boundary": _read_only_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


class RepoGroundReadonlyAdapter:
    """Read-only facade over an explicit set of existing bundle manifests."""

    def __init__(
        self,
        *,
        config_path: Path,
        allowed_roots: tuple[Path, ...],
        snapshots: tuple[SnapshotRegistration, ...],
    ) -> None:
        self.config_path = config_path
        self.allowed_roots = allowed_roots
        self._snapshots = {item.snapshot_id: item for item in snapshots}
        self.config_sha256 = _sha256_bytes(config_path.read_bytes())

    @classmethod
    def from_config(cls, config_path: str | Path) -> "RepoGroundReadonlyAdapter":
        path = Path(config_path).expanduser().resolve()
        document = _json_object(path, label="adapter config")
        if document.get("kind") != CONFIG_KIND or document.get("version") != CONFIG_VERSION:
            raise RepoGroundReadonlyAdapterError(
                f"adapter config must be {CONFIG_KIND} version {CONFIG_VERSION}"
            )
        base = path.parent
        raw_roots = document.get("allowed_roots")
        if not isinstance(raw_roots, list) or not raw_roots:
            raise RepoGroundReadonlyAdapterError("allowed_roots must be a non-empty array")
        roots = tuple(
            _resolve_config_path(base, value, label="allowed root") for value in raw_roots
        )
        for root in roots:
            if not root.is_dir():
                raise RepoGroundReadonlyAdapterError(
                    f"allowed root does not exist or is not a directory: {root}"
                )

        raw_snapshots = document.get("snapshots")
        if not isinstance(raw_snapshots, list) or not raw_snapshots:
            raise RepoGroundReadonlyAdapterError("snapshots must be a non-empty array")
        registrations: list[SnapshotRegistration] = []
        seen_ids: set[str] = set()
        for raw in raw_snapshots:
            if not isinstance(raw, dict):
                raise RepoGroundReadonlyAdapterError("snapshot registration must be an object")
            snapshot_id = raw.get("id")
            if not isinstance(snapshot_id, str) or not snapshot_id.strip():
                raise RepoGroundReadonlyAdapterError("snapshot id must be a non-empty string")
            if snapshot_id in seen_ids:
                raise RepoGroundReadonlyAdapterError(f"duplicate snapshot id: {snapshot_id}")
            manifest = _resolve_config_path(
                base,
                raw.get("manifest"),
                label=f"snapshot {snapshot_id} manifest",
            )
            if not _within(manifest, roots):
                raise RepoGroundReadonlyAdapterError(
                    f"snapshot manifest escapes allowed roots: {manifest}"
                )
            _validate_manifest(manifest)
            seen_ids.add(snapshot_id)
            registrations.append(SnapshotRegistration(snapshot_id, manifest))
        return cls(
            config_path=path,
            allowed_roots=roots,
            snapshots=tuple(registrations),
        )

    def _registration(self, snapshot_id: Any) -> SnapshotRegistration:
        if not isinstance(snapshot_id, str) or not snapshot_id:
            raise RepoGroundReadonlyAdapterError("snapshot_id must be a non-empty string")
        try:
            return self._snapshots[snapshot_id]
        except KeyError as exc:
            raise RepoGroundReadonlyAdapterError(
                f"snapshot_id is not registered: {snapshot_id}"
            ) from exc

    def manifest_for(self, snapshot_id: Any) -> Path:
        """Return the validated manifest path for one registered snapshot."""

        return self._registration(snapshot_id).manifest

    def snapshot_list(self) -> dict[str, Any]:
        snapshots: list[dict[str, Any]] = []
        for registration in self._snapshots.values():
            status = bundle_access.snapshot_status(registration.manifest)
            snapshots.append(
                {
                    "snapshot_id": registration.snapshot_id,
                    "bundle_manifest": str(registration.manifest),
                    "bundle_run_id": status.get("bundle_run_id"),
                    "profile": status.get("profile"),
                    "artifact_count": status.get("artifact_count"),
                    "freshness": status.get("freshness"),
                    "availability_model": status.get("availability_model"),
                }
            )
        result = _base_response("snapshot_list", status="available")
        result.update(
            {
                "config_path": str(self.config_path),
                "config_sha256": self.config_sha256,
                "snapshot_count": len(snapshots),
                "snapshots": snapshots,
                "discovery": "explicit_config_only",
            }
        )
        return result

    def snapshot_status(self, snapshot_id: Any) -> dict[str, Any]:
        registration = self._registration(snapshot_id)
        result = _base_response(
            "snapshot_status",
            status="available",
            snapshot_id=registration.snapshot_id,
            manifest=registration.manifest,
        )
        result["snapshot"] = bundle_access.snapshot_status(registration.manifest)
        return result

    def _verify_registered_artifact(
        self,
        registration: SnapshotRegistration,
        role: str,
    ) -> dict[str, Any]:
        """Verify one manifest artifact before or after a delegated read."""

        reference = bundle_access.get_artifact(registration.manifest, role)
        artifact = reference.get("artifact")
        if reference.get("status") != "available" or not isinstance(artifact, dict):
            return {
                "status": reference.get("status", "missing"),
                "error_code": "artifact_unavailable",
                "artifact": artifact,
            }
        raw_path = artifact.get("absolute_path")
        if not isinstance(raw_path, str):
            return {
                "status": "blocked",
                "error_code": "artifact_path_missing",
                "artifact": artifact,
            }
        artifact_path = Path(raw_path).resolve()
        try:
            artifact_path.relative_to(registration.manifest.parent.resolve())
        except ValueError:
            return {
                "status": "blocked",
                "error_code": "artifact_path_escape",
                "artifact": artifact,
            }
        expected_bytes = artifact.get("bytes")
        expected_sha = artifact.get("sha256")
        if (
            not isinstance(expected_bytes, int)
            or not isinstance(expected_sha, str)
            or _SHA256_RE.fullmatch(expected_sha) is None
        ):
            return {
                "status": "blocked",
                "error_code": "artifact_integrity_unavailable",
                "artifact": artifact,
            }
        digest = hashlib.sha256()
        actual_bytes = 0
        try:
            with artifact_path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    actual_bytes += len(chunk)
                    digest.update(chunk)
        except OSError as exc:
            return {
                "status": "missing",
                "error_code": "artifact_file_unavailable",
                "error": str(exc),
                "artifact": artifact,
            }
        actual_sha = digest.hexdigest()
        if actual_bytes != expected_bytes or actual_sha != expected_sha:
            return {
                "status": "blocked",
                "error_code": "artifact_integrity_mismatch",
                "artifact": artifact,
                "actual_bytes": actual_bytes,
                "actual_sha256": actual_sha,
            }
        return {
            "status": "available",
            "artifact": artifact,
            "actual_bytes": actual_bytes,
            "actual_sha256": actual_sha,
        }

    def artifact_get(
        self,
        snapshot_id: Any,
        role: Any,
        *,
        include_content: bool = True,
    ) -> dict[str, Any]:
        registration = self._registration(snapshot_id)
        if not isinstance(role, str) or not role:
            raise RepoGroundReadonlyAdapterError("role must be a non-empty string")
        result = _base_response(
            "artifact_get",
            status="missing",
            snapshot_id=registration.snapshot_id,
            manifest=registration.manifest,
        )
        if role == "bundle_manifest":
            artifact = {
                "role": role,
                "path": registration.manifest.name,
                "absolute_path": str(registration.manifest),
                "file_exists": True,
                "content_type": "application/json",
                "bytes": registration.manifest.stat().st_size,
                "sha256": _sha256_bytes(registration.manifest.read_bytes()),
                "authority": "bundle_manifest",
                "canonicality": "bundle_root",
            }
        elif role == "availability_model":
            status = bundle_access.snapshot_status(registration.manifest)
            result.update(
                {
                    "status": "available",
                    "role": role,
                    "artifact": None,
                    "content_json": status.get("availability_model"),
                    "content_type": "application/json",
                    "synthetic_projection": True,
                }
            )
            return result
        else:
            reference = bundle_access.get_artifact(registration.manifest, role)
            artifact = reference.get("artifact")
            if reference.get("status") != "available" or not isinstance(artifact, dict):
                result.update({"role": role, "artifact": artifact})
                return result

        result.update({"status": "available", "role": role, "artifact": artifact})
        if not include_content:
            return result
        raw_path = artifact.get("absolute_path")
        if not isinstance(raw_path, str):
            result.update(
                {
                    "status": "blocked",
                    "error_code": "artifact_path_missing",
                    "error": "artifact does not expose a resolved path",
                }
            )
            return result
        artifact_path = Path(raw_path).resolve()
        try:
            artifact_path.relative_to(registration.manifest.parent.resolve())
        except ValueError:
            result.update(
                {
                    "status": "blocked",
                    "error_code": "artifact_path_escape",
                    "error": "artifact path escapes the registered bundle root",
                }
            )
            return result
        try:
            with artifact_path.open("rb") as handle:
                payload = handle.read(MAX_ARTIFACT_BYTES + 1)
        except OSError as exc:
            result.update(
                {
                    "status": "missing",
                    "error_code": "artifact_file_unavailable",
                    "error": str(exc),
                }
            )
            return result
        if len(payload) > MAX_ARTIFACT_BYTES:
            result.update(
                {
                    "status": "blocked",
                    "error_code": "artifact_too_large",
                    "max_bytes": MAX_ARTIFACT_BYTES,
                }
            )
            return result
        expected_bytes = artifact.get("bytes")
        expected_sha = artifact.get("sha256")
        if (
            not isinstance(expected_bytes, int)
            or not isinstance(expected_sha, str)
            or _SHA256_RE.fullmatch(expected_sha) is None
        ):
            result.update(
                {
                    "status": "blocked",
                    "error_code": "artifact_integrity_unavailable",
                    "error": "manifest bytes and sha256 are required for content reads",
                }
            )
            return result
        actual_sha = _sha256_bytes(payload)
        if len(payload) != expected_bytes or actual_sha != expected_sha:
            result.update(
                {
                    "status": "blocked",
                    "error_code": "artifact_integrity_mismatch",
                    "actual_bytes": len(payload),
                    "actual_sha256": actual_sha,
                }
            )
            return result
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            result.update(
                {
                    "status": "blocked",
                    "error_code": "binary_content_not_exposed",
                    "content_bytes": len(payload),
                    "content_sha256": actual_sha,
                }
            )
            return result
        result.update(
            {
                "content_text": text,
                "content_bytes": len(payload),
                "content_sha256": actual_sha,
            }
        )
        try:
            result["content_json"] = json.loads(text)
        except json.JSONDecodeError:
            # Plain UTF-8 text is a valid artifact response; JSON is optional.
            pass
        return result

    def canonical_range_get(self, snapshot_id: Any, range_ref: Any) -> dict[str, Any]:
        registration = self._registration(snapshot_id)
        result = _base_response(
            "canonical_range_get",
            status="available",
            snapshot_id=registration.snapshot_id,
            manifest=registration.manifest,
        )
        result["range_result"] = bundle_access.range_get(
            registration.manifest,
            range_ref,
        )
        result["status"] = result["range_result"].get("status", "invalid")
        return result

    def required_reading_resolve(
        self,
        snapshot_id: Any,
        task_profile: Any,
    ) -> dict[str, Any]:
        registration = self._registration(snapshot_id)
        if not isinstance(task_profile, str) or not task_profile:
            raise RepoGroundReadonlyAdapterError(
                "task_profile must be a non-empty string"
            )
        result = _base_response(
            "required_reading_resolve",
            status="available",
            snapshot_id=registration.snapshot_id,
            manifest=registration.manifest,
        )
        result["required_reading"] = bundle_access.resolve_required_reading_for_bundle(
            registration.manifest,
            task_profile,
        )
        result["status"] = result["required_reading"].get("status", "invalid")
        return result

    def query_existing_index(
        self,
        snapshot_id: Any,
        query: Any,
        *,
        k: Any = 10,
        filters: Any = None,
        resolve_evidence: Any = True,
        project_sources: Any = True,
    ) -> dict[str, Any]:
        registration = self._registration(snapshot_id)
        result = _base_response(
            "query_existing_index",
            status="available",
            snapshot_id=registration.snapshot_id,
            manifest=registration.manifest,
        )
        preflight = self._verify_registered_artifact(registration, "sqlite_index")
        result["index_integrity_preflight"] = preflight
        if preflight.get("status") != "available":
            result["status"] = preflight.get("status", "blocked")
            result["error_code"] = preflight.get(
                "error_code",
                "index_integrity_preflight_failed",
            )
            return result
        result["query"] = bundle_access.query_existing_index(
            registration.manifest,
            query,
            k=k,
            filters=filters if isinstance(filters, dict) else {},
            resolve_evidence=resolve_evidence,
            project_sources=project_sources,
        )
        postflight = self._verify_registered_artifact(registration, "sqlite_index")
        result["index_integrity_postflight"] = postflight
        if postflight.get("status") != "available":
            result["status"] = postflight.get("status", "blocked")
            result["error_code"] = postflight.get(
                "error_code",
                "index_integrity_postflight_failed",
            )
            result.pop("query", None)
            return result
        result["status"] = result["query"].get("status", "invalid")
        return result

    def symbol_search(
        self,
        snapshot_id: Any,
        query: Any = "",
        *,
        k: Any = 25,
        kind: Any = None,
        path: Any = None,
    ) -> dict[str, Any]:
        registration = self._registration(snapshot_id)
        result = _base_response(
            "symbol_search",
            status="available",
            snapshot_id=registration.snapshot_id,
            manifest=registration.manifest,
        )
        preflight = self._verify_registered_artifact(
            registration,
            "python_symbol_index_json",
        )
        result["symbol_integrity_preflight"] = preflight
        if preflight.get("status") != "available":
            result["status"] = preflight.get("status", "blocked")
            result["error_code"] = preflight.get(
                "error_code",
                "symbol_integrity_preflight_failed",
            )
            return result
        result["symbol_search"] = bundle_access.search_symbol_index(
            registration.manifest,
            query,
            k=k,
            kind=kind,
            path=path,
        )
        postflight = self._verify_registered_artifact(
            registration,
            "python_symbol_index_json",
        )
        result["symbol_integrity_postflight"] = postflight
        if postflight.get("status") != "available":
            result["status"] = postflight.get("status", "blocked")
            result["error_code"] = postflight.get(
                "error_code",
                "symbol_integrity_postflight_failed",
            )
            result.pop("symbol_search", None)
            return result
        result["status"] = result["symbol_search"].get("status", "invalid")
        return result

    def workbench_artifact_get(self, snapshot_id: Any, role: Any) -> dict[str, Any]:
        if role not in WORKBENCH_ROLES:
            raise RepoGroundReadonlyAdapterError(
                f"role is not a bounded workbench artifact: {role}"
            )
        result = self.artifact_get(snapshot_id, role)
        result["action"] = "workbench_artifact_get"
        result["role_boundary"] = sorted(WORKBENCH_ROLES)
        return result

    def runtime_artifact_get(self, snapshot_id: Any, role: Any) -> dict[str, Any]:
        if role not in RUNTIME_ROLES:
            raise RepoGroundReadonlyAdapterError(
                f"role is not a bounded runtime artifact: {role}"
            )
        result = self.artifact_get(snapshot_id, role)
        result["action"] = "runtime_artifact_get"
        result["role_boundary"] = sorted(RUNTIME_ROLES)
        return result

    def dispatch(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, dict):
            return self._invalid("unknown", "request must be a JSON object")
        action = request.get("action")
        if not isinstance(action, str):
            return self._invalid("unknown", "action must be a string")
        try:
            if action == "snapshot_list":
                return self.snapshot_list()
            snapshot_id = request.get("snapshot_id")
            if action == "snapshot_status":
                return self.snapshot_status(snapshot_id)
            if action == "artifact_get":
                return self.artifact_get(
                    snapshot_id,
                    request.get("role"),
                    include_content=request.get("include_content", True),
                )
            if action == "canonical_range_get":
                return self.canonical_range_get(snapshot_id, request.get("range_ref"))
            if action == "required_reading_resolve":
                return self.required_reading_resolve(
                    snapshot_id,
                    request.get("task_profile"),
                )
            if action == "query_existing_index":
                return self.query_existing_index(
                    snapshot_id,
                    request.get("query"),
                    k=request.get("k", 10),
                    filters=request.get("filters"),
                    resolve_evidence=request.get("resolve_evidence", True),
                    project_sources=request.get("project_sources", True),
                )
            if action == "symbol_search":
                return self.symbol_search(
                    snapshot_id,
                    request.get("query", ""),
                    k=request.get("k", 25),
                    kind=request.get("kind"),
                    path=request.get("path"),
                )
            if action == "workbench_artifact_get":
                return self.workbench_artifact_get(snapshot_id, request.get("role"))
            if action == "runtime_artifact_get":
                return self.runtime_artifact_get(snapshot_id, request.get("role"))
        except (RepoGroundReadonlyAdapterError, ValueError) as exc:
            return self._invalid(action, str(exc), snapshot_id=snapshot_id)
        return self._invalid(action, f"unsupported adapter action: {action}")

    def _invalid(
        self,
        action: str,
        error: str,
        *,
        snapshot_id: Any = None,
    ) -> dict[str, Any]:
        result = _base_response(
            action,
            status="invalid",
            snapshot_id=snapshot_id if isinstance(snapshot_id, str) else None,
        )
        result.update({"error_code": "adapter_request_invalid", "error": error})
        return result


# Bounded source-compatibility class aliases.
RepoBriefReadonlyAdapterError = RepoGroundReadonlyAdapterError
RepoBriefReadonlyAdapter = RepoGroundReadonlyAdapter
