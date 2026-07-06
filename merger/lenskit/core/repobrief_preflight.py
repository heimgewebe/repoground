"""RepoBrief Agent Consumption Preflight (v1).

Deterministic, read-only readiness check an agent runs *before* consuming a
Brief Bundle for a task profile.  It answers one question: does the bundle
provide enough declared, file-backed evidence for this task profile, and is
any of that evidence degraded, stale, or unverifiable?

Layer separation (strict):

* Required Reading Protocol (``required_reading``) stays the sole expectation
  policy — the preflight resolves it, it does not define parallel role tables.
* Snapshot profile policy (``repobrief_profiles``) stays the sole
  generation-side policy — the preflight re-evaluates the recorded label, it
  does not redefine it.
* Health diagnostics (post-emit health, bundle surface validation,
  output health) are diagnostic signals.  The preflight surfaces their status;
  it never converts a degraded or skipped validation into success.
* Availability and freshness are metadata about the bundle, not statements
  about the repository or the answer.

The preflight performs no writes, no refresh, no Git access, no snapshot
creation.  It makes no truth claim: it does not establish that tests are
sufficient, runtime behavior is correct, a review is complete, a PR is
mergeable, or that forensic readiness exists.
"""
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from merger.lenskit.core.clock import now_utc
from merger.lenskit.core.path_security import resolve_secure_path
from merger.lenskit.core.post_emit_health import derive_post_health_path
from merger.lenskit.core.repobrief_access import snapshot_status
from merger.lenskit.core.repobrief_profiles import (
    evaluate_profile,
    present_roles_from_manifest,
    profile_names,
)
from merger.lenskit.core.required_reading import (
    default_required_reading_protocol,
    resolve_required_reading,
)

KIND = "repobrief.consumption_preflight"
VERSION = "v1"

STATUS_PASS = "pass"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_NA = "not_applicable"

_POST_EMIT_HEALTH_KIND = "lenskit.post_emit_health"
_POST_EMIT_HEALTH_VERSION = "1.0"
_POST_EMIT_HEALTH_STATUSES = {STATUS_PASS, STATUS_WARN, STATUS_FAIL, "blocked"}

SEVERITY_FAIL = "fail"
SEVERITY_WARN = "warn"
SEVERITY_INFO = "info"

REQUIREMENT_REQUIRED = "required"
REQUIREMENT_RECOMMENDED = "recommended"
REQUIREMENT_NA = "not_applicable"

AVAILABILITY_AVAILABLE = "available"
AVAILABILITY_MISSING = "missing"
AVAILABILITY_FILE_MISSING = "file_missing"

_LINKED_SIDECAR_ROLES = {
    "post_emit_health_path": "post_emit_health",
    "bundle_surface_validation_path": "bundle_surface_validation",
    "export_safety_report_path": "export_safety_report",
}

_AUTHORITY_LAYERS = (
    "canonical_content",
    "navigation_index",
    "retrieval_index",
    "diagnostic_signal",
    "runtime_cache",
    "runtime_observation",
)

DOES_NOT_ESTABLISH = (
    "truth",
    "correctness",
    "completeness",
    "runtime_behavior",
    "test_sufficiency",
    "regression_absence",
    "repo_understood",
    "claims_true",
    "forensic_ready",
    "freshness",
    "review_complete",
    "pr_mergeable",
)

MUTATION_BOUNDARY = {
    "writes": [],
    "does_not_mutate": [
        "git",
        "pull_requests",
        "patches",
        "source_working_tree",
        "brief_bundle_artifacts",
    ],
    "read_paths_do_not_refresh": True,
}


@dataclass(frozen=True)
class PreflightFinding:
    """One machine-readable defect or notice discovered by the preflight."""

    code: str
    severity: str
    area: str
    detail: str
    artifact: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "area": self.area,
            "detail": self.detail,
        }
        if self.artifact is not None:
            data["artifact"] = self.artifact
        return data


@dataclass(frozen=True)
class PreflightArtifactStatus:
    """Availability of one artifact role relative to the task profile."""

    role: str
    requirement: str
    availability: str
    file_exists: bool
    path: str | None = None
    resolved_path: str | None = None
    authority: str | None = None
    canonicality: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "requirement": self.requirement,
            "availability": self.availability,
            "file_exists": self.file_exists,
            "path": self.path,
            "resolved_path": self.resolved_path,
            "authority": self.authority,
            "canonicality": self.canonicality,
        }


@dataclass(frozen=True)
class PreflightInput:
    """Inputs for one consumption preflight run.

    ``used_citations`` and ``used_ranges`` are optional declarations of the
    evidence references the agent intends to rely on; when present they are
    resolved against the bundle.  ``declaration`` is an optional consumption
    self-report; when provided it must carry non-empty ``does_not_establish``
    boundaries.  ``max_age_seconds`` enables the staleness check; ``as_of``
    pins the reference time for reproducible staleness evaluation (defaults to
    the injectable lenskit clock).
    """

    bundle_manifest: str | Path
    task_profile: str = "basic_repo_question"
    used_citations: tuple[Any, ...] = ()
    used_ranges: tuple[Any, ...] = ()
    declaration: Mapping[str, Any] | None = None
    max_age_seconds: float | None = None
    as_of: datetime.datetime | None = None


@dataclass(frozen=True)
class PreflightResult:
    """Typed preflight verdict plus the full v1 payload dict."""

    status: str
    task_profile: str
    bundle_manifest: str
    findings: tuple[PreflightFinding, ...]
    artifacts: tuple[PreflightArtifactStatus, ...]
    checks: tuple[Mapping[str, Any], ...]
    data: Mapping[str, Any] = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.data))


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    except UnicodeError as exc:
        raise ValueError(f"{label} is not valid UTF-8 text: {path}") from exc
    except OSError as exc:
        raise ValueError(f"{label} cannot be read: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a JSON object")
    return data


def _load_json_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, "file not found"
    if not path.is_file():
        return None, "not a regular file"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        return None, str(exc)
    if not isinstance(data, dict):
        return None, "JSON root must be an object"
    return data, None


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _parse_created_at(value: Any) -> datetime.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _normalize_citation_ids(values: Sequence[Any]) -> tuple[list[str], list[str]]:
    """Return (sorted unique citation ids, invalid entries as reprs)."""
    ids: set[str] = set()
    invalid: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip():
            ids.add(value.strip())
        elif isinstance(value, Mapping) and isinstance(value.get("citation_id"), str) and value["citation_id"].strip():
            ids.add(value["citation_id"].strip())
        else:
            invalid.append(repr(value))
    return sorted(ids), invalid


def _line_bounds(range_ref: Mapping[str, Any]) -> tuple[int, int, bool] | None:
    """Extract (start_line, end_line, artifact_anchored) from a range ref."""
    if isinstance(range_ref.get("artifact_line_start"), int) and isinstance(range_ref.get("artifact_line_end"), int):
        return range_ref["artifact_line_start"], range_ref["artifact_line_end"], True
    if isinstance(range_ref.get("start_line"), int) and isinstance(range_ref.get("end_line"), int):
        return range_ref["start_line"], range_ref["end_line"], False
    return None


def _count_lines(path: Path) -> int | None:
    try:
        with path.open("rb") as handle:
            count = 0
            saw_bytes = False
            for chunk in iter(lambda: handle.read(65536), b""):
                saw_bytes = True
                count += chunk.count(b"\n")
                last_chunk = chunk
            if saw_bytes and not last_chunk.endswith(b"\n"):
                count += 1
            return count
    except OSError:
        return None


def _resolve_link_path(manifest_dir: Path, raw: Any) -> tuple[Path | None, str | None]:
    if not isinstance(raw, str) or not raw:
        return None, None
    try:
        return resolve_secure_path(manifest_dir, raw), None
    except ValueError as exc:
        return None, str(exc)


def _post_emit_health_binding_error(
    post_doc: Mapping[str, Any],
    *,
    manifest_path: Path,
    manifest_run_id: Any,
) -> str | None:
    kind = post_doc.get("kind")
    if kind != _POST_EMIT_HEALTH_KIND:
        return f"post-emit health kind mismatch: expected {_POST_EMIT_HEALTH_KIND!r} got {kind!r}"

    version = post_doc.get("version")
    if version != _POST_EMIT_HEALTH_VERSION:
        return f"post-emit health version mismatch: expected {_POST_EMIT_HEALTH_VERSION!r} got {version!r}"

    status = post_doc.get("status")
    if not isinstance(status, str) or status not in _POST_EMIT_HEALTH_STATUSES:
        return f"post-emit health has invalid status: {status!r}"

    manifest_path_value = post_doc.get("bundle_manifest_path")
    if not isinstance(manifest_path_value, str) or not manifest_path_value.strip():
        return "post-emit health bundle_manifest_path is missing or empty"
    try:
        post_manifest_path = Path(manifest_path_value).expanduser().resolve()
    except OSError as exc:
        return f"post-emit health bundle_manifest_path cannot be resolved: {exc}"
    if post_manifest_path != manifest_path:
        return "post-emit health bundle_manifest_path does not match the evaluated manifest"

    if status == STATUS_PASS:
        if not isinstance(manifest_run_id, str) or not manifest_run_id.strip():
            return "manifest run_id is missing or empty; cannot bind post-emit health"
        post_bundle_run_id = post_doc.get("bundle_run_id")
        if not isinstance(post_bundle_run_id, str) or not post_bundle_run_id.strip():
            return "post-emit health bundle_run_id is missing or empty"
        if post_bundle_run_id != manifest_run_id:
            return "post-emit health bundle_run_id does not match manifest run_id"
    return None


def consumption_preflight(preflight_input: PreflightInput) -> PreflightResult:
    """Run the RepoBrief agent consumption preflight for one bundle manifest.

    Raises ``ValueError`` when the bundle manifest itself is unreadable; every
    other condition is reported as a structured finding, never an exception.
    """
    manifest_path = Path(preflight_input.bundle_manifest).expanduser().resolve()
    manifest = _read_json_object(manifest_path, label="bundle manifest")
    manifest_dir = manifest_path.parent
    manifest_run_id = manifest.get("run_id")
    status_report = snapshot_status(manifest_path)
    records = [a for a in status_report["artifacts"] if isinstance(a, dict)]

    findings: list[PreflightFinding] = []
    checks: list[dict[str, str]] = []

    def add(code: str, severity: str, area: str, detail: str, artifact: str | None = None) -> None:
        findings.append(PreflightFinding(code=code, severity=severity, area=area, detail=detail, artifact=artifact))

    # ── Effective availability: manifest role + file on disk ────────────────
    records_by_role: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        role = record.get("role")
        if isinstance(role, str) and role:
            records_by_role.setdefault(role, []).append(record)

    linked_paths: dict[str, Path | None] = {}
    links = manifest.get("links") if isinstance(manifest.get("links"), dict) else {}
    for link_key, role in _LINKED_SIDECAR_ROLES.items():
        resolved, error = _resolve_link_path(manifest_dir, links.get(link_key))
        if error is not None:
            add(
                "sidecar_path_rejected",
                SEVERITY_WARN,
                "availability",
                f"link {link_key} rejected: {error}",
                artifact=role,
            )
        if resolved is not None and role not in linked_paths:
            linked_paths[role] = resolved
    if "post_emit_health" not in linked_paths:
        derived = derive_post_health_path(manifest_path)
        if derived.is_file():
            linked_paths["post_emit_health"] = derived

    # Central role -> file map used by validation and range checks.
    artifact_paths_by_role: dict[str, Path] = {"bundle_manifest": manifest_path}
    for role, role_records in records_by_role.items():
        for record in role_records:
            candidate: Path | None = None
            absolute_path = record.get("absolute_path")
            if isinstance(absolute_path, str) and absolute_path:
                candidate = Path(absolute_path)
            else:
                relative_path = record.get("path")
                if isinstance(relative_path, str) and relative_path:
                    try:
                        candidate = resolve_secure_path(manifest_dir, relative_path)
                    except ValueError:
                        candidate = None
            if candidate is not None:
                if candidate.is_file():
                    artifact_paths_by_role[role] = candidate
                    break
                artifact_paths_by_role.setdefault(role, candidate)
    for role, path in linked_paths.items():
        if path is not None:
            artifact_paths_by_role[role] = path

    available_roles: set[str] = {"bundle_manifest"}
    file_missing_roles: set[str] = set()
    for role, role_records in records_by_role.items():
        artifact_path = artifact_paths_by_role.get(role)
        if any(record.get("file_exists") for record in role_records) and (
            artifact_path is None or artifact_path.is_file()
        ):
            available_roles.add(role)
        else:
            file_missing_roles.add(role)
    for role, path in linked_paths.items():
        if role in available_roles:
            continue
        if path is not None and path.is_file():
            available_roles.add(role)
        elif role in _LINKED_SIDECAR_ROLES.values() and any(
            links.get(key) for key, mapped in _LINKED_SIDECAR_ROLES.items() if mapped == role
        ):
            file_missing_roles.add(role)
    file_missing_roles -= available_roles

    # ── Task profile expectation (Required Reading Protocol, reused) ────────
    protocol = default_required_reading_protocol()
    required_reading = resolve_required_reading(protocol, available_roles, preflight_input.task_profile)
    task_profile_known = required_reading["status"] != STATUS_NA

    if task_profile_known:
        checks.append(_check("task_profile", STATUS_PASS, f"task profile '{preflight_input.task_profile}' resolved"))
    else:
        checks.append(
            _check("task_profile", STATUS_NA, f"task profile '{preflight_input.task_profile}' is not in the Required Reading Protocol")
        )
        add(
            "task_profile_unknown",
            SEVERITY_INFO,
            "task_profile",
            f"task profile '{preflight_input.task_profile}' is not in the Required Reading Protocol; "
            f"known profiles: {', '.join(sorted(protocol['task_profiles']))}",
        )

    required_roles = list(required_reading["required"])
    recommended_roles = list(required_reading["recommended"])
    missing_required = list(required_reading["missing_required"])
    missing_recommended = list(required_reading["missing_recommended"])
    required_role_set = set(required_roles)
    recommended_role_set = set(recommended_roles)

    def add_sidecar_read_failure(role: str, detail: str) -> None:
        if role in required_role_set:
            add("validation_required_sidecar_unreadable", SEVERITY_FAIL, "validation", detail, artifact=role)
        else:
            add("validation_unreadable", SEVERITY_WARN, "validation", detail, artifact=role)

    for role in missing_required:
        if role in file_missing_roles:
            detail = f"required artifact '{role}' is listed in the manifest but its file is missing"
        else:
            detail = f"required artifact '{role}' is not present in the bundle"
        add("missing_required_artifact", SEVERITY_FAIL, "required_artifacts", detail, artifact=role)
    for role in missing_recommended:
        if role in file_missing_roles:
            detail = f"recommended artifact '{role}' is listed in the manifest but its file is missing"
        else:
            detail = f"recommended artifact '{role}' is not present in the bundle"
        add("missing_recommended_artifact", SEVERITY_WARN, "recommended_artifacts", detail, artifact=role)

    if not task_profile_known:
        checks.append(_check("required_artifacts", STATUS_NA, "no expectation without a known task profile"))
        checks.append(_check("recommended_artifacts", STATUS_NA, "no expectation without a known task profile"))
    else:
        checks.append(
            _check(
                "required_artifacts",
                STATUS_FAIL if missing_required else STATUS_PASS,
                f"missing required: {', '.join(missing_required) if missing_required else 'none'}",
            )
        )
        checks.append(
            _check(
                "recommended_artifacts",
                STATUS_WARN if missing_recommended else STATUS_PASS,
                f"missing recommended: {', '.join(missing_recommended) if missing_recommended else 'none'}",
            )
        )

    # Manifest-listed roles whose files are gone degrade the bundle even when
    # the task profile does not need them.
    needed = required_role_set | recommended_role_set
    for role in sorted(file_missing_roles - needed):
        add(
            "artifact_file_missing",
            SEVERITY_WARN,
            "availability",
            f"artifact '{role}' is listed in the manifest but its file is missing",
            artifact=role,
        )
    if file_missing_roles:
        artifact_files_status = STATUS_FAIL if file_missing_roles & required_role_set else STATUS_WARN
    else:
        artifact_files_status = STATUS_PASS
    checks.append(
        _check(
            "artifact_files",
            artifact_files_status,
            f"manifest-listed roles without files: {', '.join(sorted(file_missing_roles)) if file_missing_roles else 'none'}",
        )
    )

    # ── Per-role artifact statuses relative to the task profile ─────────────
    artifact_statuses: list[PreflightArtifactStatus] = []
    listed_roles = set(records_by_role) | set(linked_paths) | {"bundle_manifest"}
    for role in sorted(required_role_set | recommended_role_set | listed_roles):
        if role in required_role_set:
            requirement = REQUIREMENT_REQUIRED
        elif role in recommended_role_set:
            requirement = REQUIREMENT_RECOMMENDED
        else:
            requirement = REQUIREMENT_NA
        role_records = records_by_role.get(role)
        record = role_records[0] if role_records else {}
        if role == "bundle_manifest" and not record:
            record = {"path": manifest_path.name, "file_exists": True}
        linked = linked_paths.get(role)
        if role in available_roles:
            availability = AVAILABILITY_AVAILABLE
        elif role in file_missing_roles:
            availability = AVAILABILITY_FILE_MISSING
        else:
            availability = AVAILABILITY_MISSING
        mapped_path = artifact_paths_by_role.get(role)
        resolved_path_value = str(mapped_path) if mapped_path is not None else None
        path_value = record.get("path")
        if path_value is None and linked is not None:
            path_value = str(linked)
        artifact_statuses.append(
            PreflightArtifactStatus(
                role=role,
                requirement=requirement,
                availability=availability,
                file_exists=availability == AVAILABILITY_AVAILABLE,
                path=path_value if isinstance(path_value, str) else None,
                resolved_path=resolved_path_value,
                authority=record.get("authority") if isinstance(record.get("authority"), str) else None,
                canonicality=record.get("canonicality") if isinstance(record.get("canonicality"), str) else None,
            )
        )

    evidence_layers: dict[str, list[str]] = {layer: [] for layer in _AUTHORITY_LAYERS}
    evidence_layers["unspecified"] = []
    for status in artifact_statuses:
        if status.availability != AVAILABILITY_AVAILABLE:
            continue
        layer = status.authority if status.authority in _AUTHORITY_LAYERS else "unspecified"
        evidence_layers[layer].append(status.role)

    # ── Snapshot profile policy (generation-side, re-evaluated) ─────────────
    capabilities = manifest.get("capabilities") if isinstance(manifest.get("capabilities"), dict) else {}
    snapshot_profile = capabilities.get("repobrief_profile")
    snapshot_profile_evaluation: dict[str, Any] | None = None
    if not isinstance(snapshot_profile, str) or not snapshot_profile:
        snapshot_profile = None
        checks.append(_check("snapshot_profile_policy", STATUS_NA, "manifest carries no repobrief_profile label"))
    elif snapshot_profile not in profile_names():
        checks.append(_check("snapshot_profile_policy", STATUS_WARN, f"unknown snapshot profile label '{snapshot_profile}'"))
        add(
            "snapshot_profile_unknown",
            SEVERITY_WARN,
            "validation",
            f"manifest labels an unknown RepoBrief snapshot profile '{snapshot_profile}'",
        )
    else:
        snapshot_profile_evaluation = evaluate_profile(snapshot_profile, present_roles_from_manifest(manifest))
        profile_status = snapshot_profile_evaluation["status"]
        checks.append(
            _check(
                "snapshot_profile_policy",
                profile_status if profile_status in {STATUS_PASS, STATUS_WARN, STATUS_FAIL} else STATUS_WARN,
                f"snapshot profile '{snapshot_profile}' evaluated {profile_status}",
            )
        )
        for role in snapshot_profile_evaluation["missing_required"]:
            add(
                "snapshot_profile_missing_required",
                SEVERITY_FAIL,
                "validation",
                f"snapshot profile '{snapshot_profile}' requires artifact '{role}' but the manifest does not provide it",
                artifact=role,
            )
        for role in snapshot_profile_evaluation["profile_excluded_present"]:
            add(
                "snapshot_profile_excluded_present",
                SEVERITY_FAIL,
                "validation",
                f"snapshot profile '{snapshot_profile}' excludes artifact '{role}' but the manifest still lists it",
                artifact=role,
            )
        for role in snapshot_profile_evaluation["missing_recommended"]:
            add(
                "snapshot_profile_missing_recommended",
                SEVERITY_WARN,
                "validation",
                f"snapshot profile '{snapshot_profile}' recommends artifact '{role}' but the manifest does not provide it",
                artifact=role,
            )

    # ── Degraded validation states (diagnostic layer, never hidden) ─────────
    validation: dict[str, Any] = {}

    post_path = linked_paths.get("post_emit_health")
    post_doc: dict[str, Any] | None = None
    post_error: str | None = None
    if post_path is not None:
        post_doc, post_error = _load_json_file(post_path)
    skipped_checks: list[str] = []
    if post_path is None:
        validation["post_emit_health"] = {"present": False, "status": None, "skipped_checks": [], "path": None}
        add(
            "validation_unavailable",
            SEVERITY_WARN,
            "validation",
            "no post-emit health sidecar is linked or discoverable; bundle validation state is unknown",
            artifact="post_emit_health",
        )
    elif post_doc is None:
        validation["post_emit_health"] = {"present": False, "status": None, "skipped_checks": [], "path": str(post_path)}
        add_sidecar_read_failure(
            "post_emit_health",
            f"post-emit health sidecar cannot be read: {post_error}",
        )
    else:
        post_status = post_doc.get("status")
        for item in post_doc.get("checks") or []:
            if isinstance(item, dict) and item.get("status") == "skipped" and isinstance(item.get("name"), str):
                skipped_checks.append(item["name"])
        skipped_checks.sort()
        post_binding_error = _post_emit_health_binding_error(
            post_doc,
            manifest_path=manifest_path,
            manifest_run_id=manifest_run_id,
        )
        validation["post_emit_health"] = {
            "present": True,
            "status": post_status if isinstance(post_status, str) else None,
            "skipped_checks": skipped_checks,
            "path": str(post_path),
            "binding_status": "fail" if post_binding_error else "pass",
            "binding_error": post_binding_error,
        }
        if post_binding_error is not None:
            add_sidecar_read_failure("post_emit_health", post_binding_error)
        if post_status == STATUS_WARN:
            add("validation_degraded", SEVERITY_WARN, "validation", "post-emit health reports status=warn", artifact="post_emit_health")
        elif post_status in {STATUS_FAIL, "blocked"}:
            add(
                "validation_failed",
                SEVERITY_FAIL,
                "validation",
                f"post-emit health reports status={post_status}",
                artifact="post_emit_health",
            )
        elif post_status != STATUS_PASS:
            add(
                "validation_unreadable",
                SEVERITY_WARN,
                "validation",
                f"post-emit health reports invalid status {post_status!r}",
                artifact="post_emit_health",
            )
        if skipped_checks:
            add(
                "validation_checks_skipped",
                SEVERITY_WARN,
                "validation",
                "post-emit health skipped checks: " + ", ".join(skipped_checks),
                artifact="post_emit_health",
            )

    recorded_surface_status = links.get("bundle_surface_validation_status")
    surface_path = linked_paths.get("bundle_surface_validation")
    surface_sidecar_status: str | None = None
    if surface_path is not None:
        surface_doc, surface_error = _load_json_file(surface_path)
        if surface_doc is None:
            add_sidecar_read_failure(
                "bundle_surface_validation",
                f"bundle surface validation sidecar cannot be read: {surface_error}",
            )
        elif isinstance(surface_doc.get("status"), str):
            surface_sidecar_status = surface_doc["status"]
        else:
            add_sidecar_read_failure(
                "bundle_surface_validation",
                "bundle surface validation sidecar carries no string status",
            )
    surface_status = surface_sidecar_status
    if surface_status is None and isinstance(recorded_surface_status, str):
        surface_status = recorded_surface_status
    validation["bundle_surface_validation"] = {
        "status": surface_status if isinstance(surface_status, str) else None,
        "recorded_status": recorded_surface_status if isinstance(recorded_surface_status, str) else None,
        "sidecar_status": surface_sidecar_status,
        "path": str(linked_paths["bundle_surface_validation"]) if linked_paths.get("bundle_surface_validation") else None,
    }
    if (
        isinstance(recorded_surface_status, str)
        and surface_sidecar_status is not None
        and recorded_surface_status != surface_sidecar_status
    ):
        add(
            "validation_surface_status_mismatch",
            SEVERITY_WARN,
            "validation",
            f"bundle surface validation recorded status={recorded_surface_status} but sidecar status={surface_sidecar_status}",
            artifact="bundle_surface_validation",
        )
    if surface_status == STATUS_WARN:
        add(
            "validation_degraded",
            SEVERITY_WARN,
            "validation",
            "bundle surface validation status=warn",
            artifact="bundle_surface_validation",
        )
    elif surface_status in {STATUS_FAIL, "blocked"}:
        add(
            "validation_failed",
            SEVERITY_FAIL,
            "validation",
            f"bundle surface validation status={surface_status}",
            artifact="bundle_surface_validation",
        )

    output_health_verdict: str | None = None
    output_health_path = artifact_paths_by_role.get("output_health")
    output_health_present = output_health_path is not None and output_health_path.is_file()
    if output_health_present:
        output_doc, output_error = _load_json_file(output_health_path)
        if output_doc is None:
            add(
                "validation_unreadable",
                SEVERITY_WARN,
                "validation",
                f"output health artifact cannot be read: {output_error}",
                artifact="output_health",
            )
        else:
            verdict = output_doc.get("verdict")
            output_health_verdict = verdict if isinstance(verdict, str) else None
            if verdict == STATUS_WARN:
                add("validation_degraded", SEVERITY_WARN, "validation", "output health verdict=warn", artifact="output_health")
            elif verdict == STATUS_FAIL:
                add("validation_failed", SEVERITY_FAIL, "validation", "output health verdict=fail", artifact="output_health")
            elif verdict != STATUS_PASS:
                add(
                    "validation_unreadable",
                    SEVERITY_WARN,
                    "validation",
                    f"output health verdict invalid: {verdict!r}",
                    artifact="output_health",
                )
    validation["output_health"] = {"present": output_health_present, "verdict": output_health_verdict}
    validation["snapshot_profile_evaluation"] = snapshot_profile_evaluation

    validation_findings = [f for f in findings if f.area == "validation"]
    if any(f.severity == SEVERITY_FAIL for f in validation_findings):
        validation_status = STATUS_FAIL
    elif validation_findings:
        validation_status = STATUS_WARN
    else:
        validation_status = STATUS_PASS
    checks.append(
        _check(
            "validation_state",
            validation_status,
            "degraded validation findings: " + (", ".join(sorted({f.code for f in validation_findings})) if validation_findings else "none"),
        )
    )

    # ── Freshness / provenance visibility ───────────────────────────────────
    created_at_raw = manifest.get("created_at")
    created_at = _parse_created_at(created_at_raw)
    generator = manifest.get("generator") if isinstance(manifest.get("generator"), dict) else {}
    runtime = generator.get("runtime") if isinstance(generator.get("runtime"), dict) else None
    git_commit = runtime.get("git_commit") if isinstance(runtime, dict) else None
    snapshot_provenance = manifest.get("snapshot_provenance")
    snapshot_repositories = (
        snapshot_provenance.get("repositories")
        if isinstance(snapshot_provenance, dict)
        else None
    )
    if not isinstance(snapshot_repositories, list):
        snapshot_repositories = []
    snapshot_present_repos = [
        repo
        for repo in snapshot_repositories
        if isinstance(repo, dict)
        and repo.get("provenance_status") == "present"
        and isinstance(repo.get("git_commit"), str)
        and repo.get("git_commit")
    ]

    freshness: dict[str, Any] = {
        "created_at": created_at_raw if isinstance(created_at_raw, str) else None,
        "status": "recorded",
        "age_seconds": None,
        "max_age_seconds": preflight_input.max_age_seconds,
        "as_of": None,
        "generator_runtime_recorded": runtime is not None,
        "generator_git_commit": git_commit if isinstance(git_commit, str) else None,
        "snapshot_provenance_recorded": isinstance(snapshot_provenance, dict),
        "snapshot_repository_count": len(snapshot_repositories),
        "snapshot_present_repository_count": len(snapshot_present_repos),
        "snapshot_freshness_basis": "git_commit" if snapshot_present_repos else "unknown",
    }
    if created_at is None:
        freshness["status"] = "unknown"
        add(
            "freshness_unknown",
            SEVERITY_WARN,
            "freshness",
            "bundle manifest carries no parseable created_at; snapshot freshness is unknown",
        )
    elif preflight_input.max_age_seconds is not None:
        as_of = preflight_input.as_of or now_utc()
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=datetime.timezone.utc)
        age = (as_of - created_at).total_seconds()
        freshness["as_of"] = as_of.strftime("%Y-%m-%dT%H:%M:%SZ")
        if age < 0:
            freshness["status"] = "unknown"
            add(
                "freshness_unknown",
                SEVERITY_WARN,
                "freshness",
                "bundle created_at is in the future relative to the as-of time; snapshot freshness is unknown",
            )
        else:
            freshness["age_seconds"] = int(age)
            if age > preflight_input.max_age_seconds:
                freshness["status"] = "stale"
                add(
                    "snapshot_stale",
                    SEVERITY_WARN,
                    "freshness",
                    f"snapshot age {int(age)}s exceeds max age {int(preflight_input.max_age_seconds)}s",
                )
            else:
                freshness["status"] = "fresh"
    if not isinstance(snapshot_provenance, dict):
        freshness["status"] = "unknown"
        add(
            "snapshot_provenance_missing",
            SEVERITY_WARN,
            "freshness",
            "bundle manifest records no snapshot_provenance; source snapshot freshness is unknown",
        )
    elif not snapshot_repositories:
        freshness["status"] = "unknown"
        add(
            "snapshot_repository_provenance_missing",
            SEVERITY_WARN,
            "freshness",
            "snapshot_provenance contains no repository entries; source snapshot freshness is unknown",
        )
    elif not snapshot_present_repos:
        freshness["status"] = "unknown"
        add(
            "snapshot_git_commit_missing",
            SEVERITY_WARN,
            "freshness",
            "snapshot_provenance records no repository with provenance_status=present and git_commit; source snapshot freshness is unknown",
        )
    if runtime is None:
        freshness["status"] = "unknown"
        add(
            "generator_provenance_missing",
            SEVERITY_WARN,
            "freshness",
            "bundle manifest records no generator runtime provenance; snapshot freshness is unknown",
        )
    elif not isinstance(git_commit, str) or not git_commit:
        freshness["status"] = "unknown"
        add(
            "generator_git_commit_missing",
            SEVERITY_WARN,
            "freshness",
            "bundle manifest records generator runtime provenance without a git_commit; snapshot freshness is unknown",
        )
    freshness_status = STATUS_WARN if freshness["status"] in {"unknown", "stale"} else STATUS_PASS
    checks.append(_check("freshness", freshness_status, f"freshness {freshness['status']}"))

    # ── Consumption declaration (negative semantics are mandatory) ──────────
    declaration = preflight_input.declaration
    used_citations_input = list(preflight_input.used_citations)
    used_ranges_input = list(preflight_input.used_ranges)
    if declaration is not None:
        if isinstance(declaration.get("used_citations"), list):
            used_citations_input.extend(declaration["used_citations"])
        if isinstance(declaration.get("used_ranges"), list):
            used_ranges_input.extend(declaration["used_ranges"])
        boundaries = declaration.get("does_not_establish")
        required_boundaries = set(DOES_NOT_ESTABLISH)
        if isinstance(boundaries, list):
            provided_boundaries = {item for item in boundaries if isinstance(item, str) and item}
        else:
            provided_boundaries = set()
        boundaries_ok = required_boundaries <= provided_boundaries
        if not boundaries_ok:
            add(
                "declaration_missing_negative_semantics",
                SEVERITY_FAIL,
                "declaration",
                "consumption declaration must include all required does_not_establish boundaries",
            )
        checks.append(
            _check(
                "does_not_establish",
                STATUS_PASS if boundaries_ok else STATUS_FAIL,
                "declaration carries negative semantics" if boundaries_ok else "declaration lacks required does_not_establish boundaries",
            )
        )
    else:
        checks.append(_check("does_not_establish", STATUS_NA, "no consumption declaration provided"))
    declaration_block = {
        "provided": declaration is not None,
        "does_not_establish_present": bool(declaration is not None and declaration.get("does_not_establish")),
    }

    # ── Used citations: resolve against the citation map ────────────────────
    citation_ids, invalid_citations = _normalize_citation_ids(used_citations_input)
    used_citations_block: dict[str, Any] = {
        "declared": citation_ids,
        "resolved": [],
        "unresolved": [],
        "invalid": invalid_citations,
        "citation_map_available": "citation_map_jsonl" in available_roles,
    }
    if not citation_ids and not invalid_citations:
        checks.append(_check("used_citations", STATUS_NA, "no used citations declared"))
    else:
        for entry in invalid_citations:
            add(
                "used_citation_invalid",
                SEVERITY_FAIL,
                "used_citations",
                f"used citation entry is not a citation id or citation declaration: {entry}",
            )
        known_ids: set[str] | None = None
        if "citation_map_jsonl" not in available_roles:
            add(
                "used_citations_unverifiable",
                SEVERITY_FAIL,
                "used_citations",
                "used citations were declared but no citation_map_jsonl artifact is available to resolve them",
                artifact="citation_map_jsonl",
            )
        else:
            known_ids = set()
            unparseable_lines = 0
            map_path = artifact_paths_by_role.get("citation_map_jsonl")
            if map_path is None or not map_path.is_file():
                known_ids = None
                add(
                    "used_citations_unverifiable",
                    SEVERITY_FAIL,
                    "used_citations",
                    "citation map is marked available but no readable file path was resolved",
                    artifact="citation_map_jsonl",
                )
            else:
                try:
                    with map_path.open("r", encoding="utf-8") as handle:
                        for line in handle:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                entry = json.loads(line)
                            except json.JSONDecodeError:
                                unparseable_lines += 1
                                continue
                            if isinstance(entry, dict) and isinstance(entry.get("citation_id"), str):
                                known_ids.add(entry["citation_id"])
                except OSError as exc:
                    known_ids = None
                    add(
                        "used_citations_unverifiable",
                        SEVERITY_FAIL,
                        "used_citations",
                        f"citation map cannot be read: {exc}",
                        artifact="citation_map_jsonl",
                    )
            if unparseable_lines and known_ids is not None:
                add(
                    "citation_map_lines_unparseable",
                    SEVERITY_WARN,
                    "used_citations",
                    f"citation map contains {unparseable_lines} unparseable line(s)",
                    artifact="citation_map_jsonl",
                )
        if known_ids is not None:
            for citation_id in citation_ids:
                if citation_id in known_ids:
                    used_citations_block["resolved"].append(citation_id)
                else:
                    used_citations_block["unresolved"].append(citation_id)
                    add(
                        "used_citation_unresolved",
                        SEVERITY_FAIL,
                        "used_citations",
                        f"used citation '{citation_id}' does not resolve in the citation map",
                    )
        citation_fail = any(f.area == "used_citations" and f.severity == SEVERITY_FAIL for f in findings)
        citation_warn = any(f.area == "used_citations" and f.severity == SEVERITY_WARN for f in findings)
        checks.append(
            _check(
                "used_citations",
                STATUS_FAIL if citation_fail else STATUS_WARN if citation_warn else STATUS_PASS,
                f"declared={len(citation_ids)} resolved={len(used_citations_block['resolved'])} "
                f"unresolved={len(used_citations_block['unresolved'])}",
            )
        )

    # ── Used ranges: bind to available artifacts and line bounds ────────────
    used_ranges_block: dict[str, Any] = {"declared": len(used_ranges_input), "resolved": [], "unresolved": []}
    if not used_ranges_input:
        checks.append(_check("used_ranges", STATUS_NA, "no used ranges declared"))
    else:
        line_counts: dict[str, int | None] = {}
        for index, raw in enumerate(used_ranges_input):
            label = f"used_ranges[{index}]"

            def unresolved(detail: str, artifact: str | None = None) -> None:
                used_ranges_block["unresolved"].append({"index": index, "detail": detail})
                add("used_range_unresolved", SEVERITY_FAIL, "used_ranges", f"{label}: {detail}", artifact=artifact)

            if not isinstance(raw, Mapping):
                unresolved("range declaration must be an object with artifact and range_ref")
                continue
            role = raw.get("artifact")
            range_ref = raw.get("range_ref")
            if not isinstance(role, str) or not role:
                unresolved("range declaration lacks an artifact role")
                continue
            if not isinstance(range_ref, Mapping):
                unresolved(f"range declaration for '{role}' lacks a range_ref object", artifact=role)
                continue
            if role not in available_roles:
                unresolved(f"artifact '{role}' is not available in the bundle", artifact=role)
                continue
            bounds = _line_bounds(range_ref)
            if bounds is None:
                unresolved(f"range_ref for '{role}' carries no integer line bounds", artifact=role)
                continue
            start_line, end_line, _artifact_anchored = bounds
            if start_line < 1 or end_line < start_line:
                unresolved(f"range_ref for '{role}' has invalid line bounds {start_line}..{end_line}", artifact=role)
                continue
            if role not in line_counts:
                path = artifact_paths_by_role.get(role)
                line_counts[role] = _count_lines(path) if path is not None else None
            total_lines = line_counts[role]
            if total_lines is None:
                unresolved(f"artifact '{role}' file cannot be read to verify line bounds", artifact=role)
                continue
            if end_line > total_lines:
                unresolved(
                    f"range {start_line}..{end_line} exceeds artifact '{role}' length of {total_lines} line(s)",
                    artifact=role,
                )
                continue
            resolution = "artifact_lines_verified"
            used_ranges_block["resolved"].append(
                {"index": index, "artifact": role, "start_line": start_line, "end_line": end_line, "resolution": resolution}
            )
        checks.append(
            _check(
                "used_ranges",
                STATUS_FAIL if used_ranges_block["unresolved"] else STATUS_PASS,
                f"declared={len(used_ranges_input)} resolved={len(used_ranges_block['resolved'])} "
                f"unresolved={len(used_ranges_block['unresolved'])}",
            )
        )

    # ── Aggregate: fail > not_applicable (unknown profile) > warn > pass ────
    severity_order = {SEVERITY_FAIL: 0, SEVERITY_WARN: 1, SEVERITY_INFO: 2}
    ordered_findings = tuple(
        sorted(findings, key=lambda f: (severity_order[f.severity], f.code, f.artifact or "", f.detail))
    )
    if any(f.severity == SEVERITY_FAIL for f in ordered_findings):
        overall = STATUS_FAIL
    elif not task_profile_known:
        overall = STATUS_NA
    elif any(f.severity == SEVERITY_WARN for f in ordered_findings):
        overall = STATUS_WARN
    else:
        overall = STATUS_PASS

    check_order = {name: i for i, name in enumerate(
        (
            "task_profile",
            "required_artifacts",
            "recommended_artifacts",
            "artifact_files",
            "snapshot_profile_policy",
            "validation_state",
            "freshness",
            "used_citations",
            "used_ranges",
            "does_not_establish",
        )
    )}
    ordered_checks = tuple(sorted(checks, key=lambda c: check_order.get(c["name"], len(check_order))))

    data: dict[str, Any] = {
        "kind": KIND,
        "version": VERSION,
        "status": overall,
        "bundle_manifest": str(manifest_path),
        "bundle_run_id": status_report.get("bundle_run_id"),
        "snapshot_profile": snapshot_profile,
        "task_profile": preflight_input.task_profile,
        "task_profile_known": task_profile_known,
        "citation_required": required_reading["citation_required"],
        "required_artifacts": required_roles,
        "recommended_artifacts": recommended_roles,
        "available_artifacts": sorted(available_roles),
        "missing_required_artifacts": missing_required,
        "missing_recommended_artifacts": missing_recommended,
        "artifact_statuses": [s.to_dict() for s in artifact_statuses],
        "evidence_layers": {layer: sorted(roles) for layer, roles in evidence_layers.items()},
        "validation": validation,
        "freshness": freshness,
        "used_citations": used_citations_block,
        "used_ranges": used_ranges_block,
        "declaration": declaration_block,
        "required_reading": required_reading,
        "checks": list(ordered_checks),
        "findings": [f.to_dict() for f in ordered_findings],
        "finding_counts": {
            SEVERITY_FAIL: sum(1 for f in ordered_findings if f.severity == SEVERITY_FAIL),
            SEVERITY_WARN: sum(1 for f in ordered_findings if f.severity == SEVERITY_WARN),
            SEVERITY_INFO: sum(1 for f in ordered_findings if f.severity == SEVERITY_INFO),
        },
        "mutation_boundary": json.loads(json.dumps(MUTATION_BOUNDARY)),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }

    return PreflightResult(
        status=overall,
        task_profile=preflight_input.task_profile,
        bundle_manifest=str(manifest_path),
        findings=ordered_findings,
        artifacts=tuple(artifact_statuses),
        checks=ordered_checks,
        data=data,
    )


def run_consumption_preflight(
    bundle_manifest: str | Path,
    task_profile: str = "basic_repo_question",
    *,
    used_citations: Sequence[Any] = (),
    used_ranges: Sequence[Any] = (),
    declaration: Mapping[str, Any] | None = None,
    max_age_seconds: float | None = None,
    as_of: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Dict-level convenience wrapper around :func:`consumption_preflight`."""
    result = consumption_preflight(
        PreflightInput(
            bundle_manifest=bundle_manifest,
            task_profile=task_profile,
            used_citations=tuple(used_citations),
            used_ranges=tuple(used_ranges),
            declaration=declaration,
            max_age_seconds=max_age_seconds,
            as_of=as_of,
        )
    )
    return result.to_dict()
