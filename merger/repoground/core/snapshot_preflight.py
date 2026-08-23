"""RepoGround Agent Consumption Preflight (v1).

Deterministic, read-only readiness check an agent runs *before* consuming a
Brief Bundle for a task profile.  It answers one question: does the bundle
provide enough declared, file-backed evidence for this task profile, and is
any of that evidence degraded, stale, or unverifiable?

Layer separation (strict):

* Required Reading Protocol (``required_reading``) stays the sole expectation
  policy — the preflight resolves it, it does not define parallel role tables.
* Snapshot profile policy (``snapshot_profiles``) stays the sole
  generation-side policy — the preflight re-evaluates the recorded label, it
  does not redefine it.
* Health diagnostics (post-emit health, bundle surface validation,
  output health) are diagnostic signals.  The preflight surfaces their status;
  it never converts a degraded or skipped validation into success.
* Availability and freshness are metadata about the bundle, not statements
  about the repository or the answer.

The preflight performs no writes, no refresh, and no snapshot creation.  Its
default historical/offline path performs no Git access.  An explicit live
repository enables one bounded, read-only remote-HEAD observation without a
fetch or local repository mutation.  It makes no truth claim: it does not
establish that tests are sufficient, runtime behavior is correct, a review is
complete, a PR is mergeable, or that forensic readiness exists.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from merger.repoground.core.clock import now_utc
from merger.repoground.core.path_security import resolve_secure_path
from merger.repoground.core.post_emit_health import derive_post_health_path
from merger.repoground.core.bundle_access import snapshot_status
from merger.repoground.core.snapshot_profiles import (
    evaluate_profile,
    present_roles_from_manifest,
    profile_names,
)
from merger.repoground.core.required_reading import (
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

_LIVE_HEAD_GIT_TIMEOUT_SECONDS = 10.0
_LIVE_HEAD_OUTPUT_LIMIT_BYTES = 8 * 1024
_FULL_GIT_COMMIT_RE = re.compile(r"\A(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")

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
    context: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "area": self.area,
            "detail": self.detail,
        }
        if self.artifact is not None:
            data["artifact"] = self.artifact
        if self.context is not None:
            data["context"] = dict(self.context)
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
    the injectable lenskit clock).  ``live_repo`` explicitly opts into a
    bounded read-only comparison with origin's advertised default HEAD; when
    omitted, the preflight runs no Git subprocess.
    """

    bundle_manifest: str | Path
    task_profile: str = "basic_repo_question"
    used_citations: tuple[Any, ...] = ()
    used_ranges: tuple[Any, ...] = ()
    declaration: Mapping[str, Any] | None = None
    max_age_seconds: float | None = None
    as_of: datetime.datetime | None = None
    live_repo: str | Path | None = None


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
        elif (
            isinstance(value, Mapping)
            and isinstance(value.get("citation_id"), str)
            and value["citation_id"].strip()
        ):
            ids.add(value["citation_id"].strip())
        else:
            invalid.append(repr(value))
    return sorted(ids), invalid


def _line_bounds(range_ref: Mapping[str, Any]) -> tuple[int, int, bool] | None:
    """Extract (start_line, end_line, artifact_anchored) from a range ref."""
    if isinstance(range_ref.get("artifact_line_start"), int) and isinstance(
        range_ref.get("artifact_line_end"), int
    ):
        return range_ref["artifact_line_start"], range_ref["artifact_line_end"], True
    if isinstance(range_ref.get("start_line"), int) and isinstance(
        range_ref.get("end_line"), int
    ):
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


def _post_emit_health_run_binding_error(
    post_doc: Mapping[str, Any],
    *,
    status: str,
    manifest_run_id: Any,
) -> str | None:
    if status != STATUS_PASS:
        return None
    if not isinstance(manifest_run_id, str) or not manifest_run_id.strip():
        return "manifest run_id is missing or empty; cannot bind post-emit health"
    post_bundle_run_id = post_doc.get("bundle_run_id")
    if not isinstance(post_bundle_run_id, str) or not post_bundle_run_id.strip():
        return "post-emit health bundle_run_id is missing or empty"
    if post_bundle_run_id != manifest_run_id:
        return "post-emit health bundle_run_id does not match manifest run_id"
    return None


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

    return _post_emit_health_run_binding_error(
        post_doc,
        status=status,
        manifest_run_id=manifest_run_id,
    )


def _evaluate_post_emit_health(
    *,
    linked_paths: Mapping[str, Path | None],
    manifest_path: Path,
    manifest_run_id: Any,
    add: Callable[..., None],
    add_sidecar_read_failure: Callable[[str, str], None],
) -> dict[str, Any]:
    post_path = linked_paths.get("post_emit_health")
    if post_path is None:
        add(
            "validation_unavailable",
            SEVERITY_WARN,
            "validation",
            "no post-emit health sidecar is linked or discoverable; bundle validation state is unknown",
            artifact="post_emit_health",
        )
        return {"present": False, "status": None, "skipped_checks": [], "path": None}

    post_doc, post_error = _load_json_file(post_path)
    if post_doc is None:
        add_sidecar_read_failure(
            "post_emit_health",
            f"post-emit health sidecar cannot be read: {post_error}",
        )
        return {
            "present": False,
            "status": None,
            "skipped_checks": [],
            "path": str(post_path),
        }

    post_status = post_doc.get("status")
    skipped_checks = sorted(
        item["name"]
        for item in post_doc.get("checks") or []
        if isinstance(item, dict)
        and item.get("status") == "skipped"
        and isinstance(item.get("name"), str)
    )
    post_binding_error = _post_emit_health_binding_error(
        post_doc,
        manifest_path=manifest_path,
        manifest_run_id=manifest_run_id,
    )
    result = {
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
        add(
            "validation_degraded",
            SEVERITY_WARN,
            "validation",
            "post-emit health reports status=warn",
            artifact="post_emit_health",
        )
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
    return result


def _evaluate_bundle_surface_validation(
    *,
    linked_paths: Mapping[str, Path | None],
    links: Mapping[str, Any],
    add: Callable[..., None],
    add_sidecar_read_failure: Callable[[str, str], None],
) -> dict[str, Any]:
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
    result = {
        "status": surface_status if isinstance(surface_status, str) else None,
        "recorded_status": recorded_surface_status
        if isinstance(recorded_surface_status, str)
        else None,
        "sidecar_status": surface_sidecar_status,
        "path": str(linked_paths["bundle_surface_validation"])
        if linked_paths.get("bundle_surface_validation")
        else None,
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
    return result


def _evaluate_output_health(
    *,
    artifact_paths_by_role: Mapping[str, Path],
    add: Callable[..., None],
) -> dict[str, Any]:
    output_health_verdict: str | None = None
    output_health_path = artifact_paths_by_role.get("output_health")
    output_health_present = (
        output_health_path is not None and output_health_path.is_file()
    )
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
                add(
                    "validation_degraded",
                    SEVERITY_WARN,
                    "validation",
                    "output health verdict=warn",
                    artifact="output_health",
                )
            elif verdict == STATUS_FAIL:
                add(
                    "validation_failed",
                    SEVERITY_FAIL,
                    "validation",
                    "output health verdict=fail",
                    artifact="output_health",
                )
            elif verdict != STATUS_PASS:
                add(
                    "validation_unreadable",
                    SEVERITY_WARN,
                    "validation",
                    f"output health verdict invalid: {verdict!r}",
                    artifact="output_health",
                )
    return {"present": output_health_present, "verdict": output_health_verdict}


def _evaluate_validation_state(
    *,
    linked_paths: Mapping[str, Path | None],
    links: Mapping[str, Any],
    artifact_paths_by_role: Mapping[str, Path],
    snapshot_profile_evaluation: Mapping[str, Any] | None,
    manifest_path: Path,
    manifest_run_id: Any,
    findings: list[PreflightFinding],
    checks: list[dict[str, str]],
    add: Callable[..., None],
    add_sidecar_read_failure: Callable[[str, str], None],
) -> dict[str, Any]:
    """Surface bundle validation sidecars without changing their semantics."""
    validation = {
        "post_emit_health": _evaluate_post_emit_health(
            linked_paths=linked_paths,
            manifest_path=manifest_path,
            manifest_run_id=manifest_run_id,
            add=add,
            add_sidecar_read_failure=add_sidecar_read_failure,
        ),
        "bundle_surface_validation": _evaluate_bundle_surface_validation(
            linked_paths=linked_paths,
            links=links,
            add=add,
            add_sidecar_read_failure=add_sidecar_read_failure,
        ),
        "output_health": _evaluate_output_health(
            artifact_paths_by_role=artifact_paths_by_role,
            add=add,
        ),
        "snapshot_profile_evaluation": snapshot_profile_evaluation,
    }
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
            "degraded validation findings: "
            + (
                ", ".join(sorted({f.code for f in validation_findings}))
                if validation_findings
                else "none"
            ),
        )
    )
    return validation


def _snapshot_present_repositories(
    snapshot_repositories: Sequence[Any],
) -> list[dict[str, Any]]:
    return [
        repo
        for repo in snapshot_repositories
        if isinstance(repo, dict)
        and repo.get("provenance_status") == "present"
        and isinstance(repo.get("git_commit"), str)
        and repo.get("git_commit")
    ]


def _normalize_git_commit(value: Any) -> str | None:
    if not isinstance(value, str) or not _FULL_GIT_COMMIT_RE.fullmatch(value):
        return None
    return value.lower()


def _snapshot_repository_for_live_repo(
    snapshot_repositories: Sequence[Any], repository: Path
) -> Mapping[str, Any] | None:
    candidates = [
        item
        for item in snapshot_repositories
        if isinstance(item, Mapping)
        and item.get("provenance_status") == "present"
        and _normalize_git_commit(item.get("git_commit")) is not None
    ]
    matching_roots: list[Mapping[str, Any]] = []
    for candidate in candidates:
        repo_root = candidate.get("repo_root")
        if not isinstance(repo_root, str) or not repo_root:
            continue
        try:
            recorded_root = Path(repo_root).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if recorded_root == repository:
            matching_roots.append(candidate)
    if len(matching_roots) == 1:
        return matching_roots[0]
    if not matching_roots and len(candidates) == 1:
        return candidates[0]
    return None


def _advertised_origin_head(repository: Path) -> tuple[str, str] | None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "ls-remote",
                "--exit-code",
                "--symref",
                "origin",
                "HEAD",
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_LIVE_HEAD_GIT_TIMEOUT_SECONDS,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    if (
        len(completed.stdout) > _LIVE_HEAD_OUTPUT_LIMIT_BYTES
        or len(completed.stderr) > _LIVE_HEAD_OUTPUT_LIMIT_BYTES
    ):
        return None
    try:
        lines = completed.stdout.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None

    advertised_refs: set[str] = set()
    advertised_commits: set[str] = set()
    for line in lines:
        fields = line.split()
        if (
            len(fields) == 3
            and fields[0] == "ref:"
            and fields[1].startswith("refs/heads/")
            and fields[2] == "HEAD"
        ):
            advertised_refs.add(fields[1])
        elif len(fields) == 2 and fields[1] == "HEAD":
            commit = _normalize_git_commit(fields[0])
            if commit is not None:
                advertised_commits.add(commit)
    if len(advertised_refs) != 1 or len(advertised_commits) != 1:
        return None
    return next(iter(advertised_refs)), next(iter(advertised_commits))


def _evaluate_live_head(
    *,
    live_repo: str | Path,
    snapshot_repositories: Sequence[Any],
    checks: list[dict[str, str]],
    add: Callable[..., None],
) -> dict[str, Any]:
    """Compare snapshot provenance with origin's advertised HEAD, read-only."""
    remediation = (
        "Verify the supplied local repository and origin's advertised default HEAD, "
        "then refresh or republish the bundle explicitly and rerun this preflight; "
        "no refresh was attempted."
    )
    try:
        repository = Path(live_repo).expanduser().resolve()
    except (OSError, RuntimeError):
        repository = Path(str(live_repo)).expanduser().absolute()
    result: dict[str, Any] = {
        "status": "unknown",
        "reason": "unproven",
        "snapshot_commit": None,
        "remote_commit": None,
        "remote_ref": None,
        "head_drift": None,
        "repository": str(repository),
    }

    snapshot_repository = _snapshot_repository_for_live_repo(
        snapshot_repositories, repository
    )
    if snapshot_repository is None:
        reason = "snapshot_repository_commit_unproven"
        detail = (
            "live-head mode could not select one full source snapshot git commit "
            "for the supplied repository"
        )
    else:
        result["snapshot_commit"] = _normalize_git_commit(
            snapshot_repository.get("git_commit")
        )
        if not repository.is_dir():
            reason = "live_repository_unavailable"
            detail = "live-head mode requires an existing local repository directory"
        else:
            advertised_head = _advertised_origin_head(repository)
            if advertised_head is None:
                reason = "origin_default_head_unproven"
                detail = (
                    "live-head mode could not prove origin's advertised default "
                    "branch and current commit"
                )
            else:
                remote_ref, remote_commit = advertised_head
                snapshot_commit = result["snapshot_commit"]
                head_drift = remote_commit != snapshot_commit
                result.update(
                    {
                        "status": "stale" if head_drift else "fresh",
                        "reason": "head_drift"
                        if head_drift
                        else "head_matches_snapshot_commit",
                        "remote_commit": remote_commit,
                        "remote_ref": remote_ref,
                        "head_drift": head_drift,
                    }
                )
                if not head_drift:
                    checks.append(
                        _check(
                            "live_head",
                            STATUS_PASS,
                            f"snapshot commit matches {remote_ref} at {remote_commit}",
                        )
                    )
                    return result
                stale_remediation = (
                    f"Refresh or republish the bundle explicitly from {remote_ref} "
                    f"at {remote_commit}, then rerun this preflight; no refresh was "
                    "attempted."
                )
                add(
                    "live_head_stale",
                    SEVERITY_FAIL,
                    "live_head",
                    f"snapshot commit {snapshot_commit} differs from origin's "
                    f"advertised {remote_ref} commit {remote_commit}",
                    context={**result, "remediation": stale_remediation},
                )
                checks.append(
                    _check(
                        "live_head",
                        STATUS_FAIL,
                        f"head drift: snapshot {snapshot_commit}, remote {remote_commit}",
                    )
                )
                return result

    result["reason"] = reason
    add(
        "live_head_unknown",
        SEVERITY_FAIL,
        "live_head",
        detail,
        context={**result, "remediation": remediation},
    )
    checks.append(_check("live_head", STATUS_FAIL, detail))
    return result


def _apply_age_freshness(
    freshness: dict[str, Any],
    *,
    created_at: datetime.datetime | None,
    preflight_input: PreflightInput,
    add: Callable[..., None],
) -> None:
    if created_at is None:
        freshness["status"] = "unknown"
        add(
            "freshness_unknown",
            SEVERITY_WARN,
            "freshness",
            "bundle manifest carries no parseable created_at; snapshot freshness is unknown",
        )
        return
    if preflight_input.max_age_seconds is None:
        return
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
        return
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


def _apply_provenance_freshness(
    freshness: dict[str, Any],
    *,
    snapshot_provenance: Any,
    snapshot_repositories: Sequence[Any],
    snapshot_present_repos: Sequence[Mapping[str, Any]],
    runtime: Any,
    git_commit: Any,
    add: Callable[..., None],
) -> None:
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


def _evaluate_freshness(
    *,
    manifest: Mapping[str, Any],
    preflight_input: PreflightInput,
    checks: list[dict[str, str]],
    add: Callable[..., None],
) -> dict[str, Any]:
    """Evaluate timestamp and provenance freshness signals."""
    created_at_raw = manifest.get("created_at")
    created_at = _parse_created_at(created_at_raw)
    generator = (
        manifest.get("generator") if isinstance(manifest.get("generator"), dict) else {}
    )
    runtime = (
        generator.get("runtime") if isinstance(generator.get("runtime"), dict) else None
    )
    git_commit = runtime.get("git_commit") if isinstance(runtime, dict) else None
    snapshot_provenance = manifest.get("snapshot_provenance")
    snapshot_repositories = (
        snapshot_provenance.get("repositories")
        if isinstance(snapshot_provenance, dict)
        else None
    )
    if not isinstance(snapshot_repositories, list):
        snapshot_repositories = []
    snapshot_present_repos = _snapshot_present_repositories(snapshot_repositories)
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
        "snapshot_freshness_basis": "git_commit"
        if snapshot_present_repos
        else "unknown",
    }
    _apply_age_freshness(
        freshness,
        created_at=created_at,
        preflight_input=preflight_input,
        add=add,
    )
    _apply_provenance_freshness(
        freshness,
        snapshot_provenance=snapshot_provenance,
        snapshot_repositories=snapshot_repositories,
        snapshot_present_repos=snapshot_present_repos,
        runtime=runtime,
        git_commit=git_commit,
        add=add,
    )
    freshness_status = (
        STATUS_WARN if freshness["status"] in {"unknown", "stale"} else STATUS_PASS
    )
    checks.append(
        _check("freshness", freshness_status, f"freshness {freshness['status']}")
    )
    return freshness


def _prepare_consumption_declaration(
    *,
    preflight_input: PreflightInput,
    checks: list[dict[str, str]],
    add: Callable[..., None],
) -> tuple[dict[str, Any], list[Any], list[Any]]:
    """Normalize the optional consumption declaration and evidence inputs."""
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
            provided_boundaries = {
                item for item in boundaries if isinstance(item, str) and item
            }
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
                "declaration carries negative semantics"
                if boundaries_ok
                else "declaration lacks required does_not_establish boundaries",
            )
        )
    else:
        checks.append(
            _check(
                "does_not_establish", STATUS_NA, "no consumption declaration provided"
            )
        )
    declaration_block = {
        "provided": declaration is not None,
        "does_not_establish_present": bool(
            declaration is not None and declaration.get("does_not_establish")
        ),
    }

    return declaration_block, used_citations_input, used_ranges_input


def _read_citation_map_ids(
    map_path: Path | None,
    *,
    add: Callable[..., None],
) -> set[str] | None:
    if map_path is None or not map_path.is_file():
        add(
            "used_citations_unverifiable",
            SEVERITY_FAIL,
            "used_citations",
            "citation map is marked available but no readable file path was resolved",
            artifact="citation_map_jsonl",
        )
        return None
    known_ids: set[str] = set()
    unparseable_lines = 0
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
                if isinstance(entry, dict) and isinstance(
                    entry.get("citation_id"), str
                ):
                    known_ids.add(entry["citation_id"])
    except OSError as exc:
        add(
            "used_citations_unverifiable",
            SEVERITY_FAIL,
            "used_citations",
            f"citation map cannot be read: {exc}",
            artifact="citation_map_jsonl",
        )
        return None
    if unparseable_lines:
        add(
            "citation_map_lines_unparseable",
            SEVERITY_WARN,
            "used_citations",
            f"citation map contains {unparseable_lines} unparseable line(s)",
            artifact="citation_map_jsonl",
        )
    return known_ids


def _resolve_citation_ids(
    citation_ids: Sequence[str],
    known_ids: set[str],
    used_citations_block: dict[str, Any],
    *,
    add: Callable[..., None],
) -> None:
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


def _evaluate_used_citations(
    *,
    used_citations_input: Sequence[Any],
    available_roles: set[str],
    artifact_paths_by_role: Mapping[str, Path],
    findings: list[PreflightFinding],
    checks: list[dict[str, str]],
    add: Callable[..., None],
) -> dict[str, Any]:
    """Resolve declared citations against the bundle citation map."""
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
        return used_citations_block
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
        known_ids = _read_citation_map_ids(
            artifact_paths_by_role.get("citation_map_jsonl"), add=add
        )
    if known_ids is not None:
        _resolve_citation_ids(citation_ids, known_ids, used_citations_block, add=add)
    citation_fail = any(
        f.area == "used_citations" and f.severity == SEVERITY_FAIL for f in findings
    )
    citation_warn = any(
        f.area == "used_citations" and f.severity == SEVERITY_WARN for f in findings
    )
    checks.append(
        _check(
            "used_citations",
            STATUS_FAIL
            if citation_fail
            else STATUS_WARN
            if citation_warn
            else STATUS_PASS,
            f"declared={len(citation_ids)} resolved={len(used_citations_block['resolved'])} "
            f"unresolved={len(used_citations_block['unresolved'])}",
        )
    )
    return used_citations_block


def _resolve_used_range(
    raw: Any,
    *,
    index: int,
    available_roles: set[str],
    artifact_paths_by_role: Mapping[str, Path],
    line_counts: dict[str, int | None],
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    if not isinstance(raw, Mapping):
        return (
            None,
            "range declaration must be an object with artifact and range_ref",
            None,
        )
    role = raw.get("artifact")
    range_ref = raw.get("range_ref")
    if not isinstance(role, str) or not role:
        return None, "range declaration lacks an artifact role", None
    if not isinstance(range_ref, Mapping):
        return None, f"range declaration for '{role}' lacks a range_ref object", role
    if role not in available_roles:
        return None, f"artifact '{role}' is not available in the bundle", role
    bounds = _line_bounds(range_ref)
    if bounds is None:
        return None, f"range_ref for '{role}' carries no integer line bounds", role
    start_line, end_line, _artifact_anchored = bounds
    if start_line < 1 or end_line < start_line:
        return (
            None,
            f"range_ref for '{role}' has invalid line bounds {start_line}..{end_line}",
            role,
        )
    if role not in line_counts:
        path = artifact_paths_by_role.get(role)
        line_counts[role] = _count_lines(path) if path is not None else None
    total_lines = line_counts[role]
    if total_lines is None:
        return (
            None,
            f"artifact '{role}' file cannot be read to verify line bounds",
            role,
        )
    if end_line > total_lines:
        return (
            None,
            f"range {start_line}..{end_line} exceeds artifact '{role}' length of {total_lines} line(s)",
            role,
        )
    return (
        {
            "index": index,
            "artifact": role,
            "start_line": start_line,
            "end_line": end_line,
            "resolution": "artifact_lines_verified",
        },
        None,
        None,
    )


def _evaluate_used_ranges(
    *,
    used_ranges_input: Sequence[Any],
    available_roles: set[str],
    artifact_paths_by_role: Mapping[str, Path],
    checks: list[dict[str, str]],
    add: Callable[..., None],
) -> dict[str, Any]:
    """Bind declared ranges to available artifacts and verify line bounds."""
    used_ranges_block: dict[str, Any] = {
        "declared": len(used_ranges_input),
        "resolved": [],
        "unresolved": [],
    }
    if not used_ranges_input:
        checks.append(_check("used_ranges", STATUS_NA, "no used ranges declared"))
        return used_ranges_block
    line_counts: dict[str, int | None] = {}
    for index, raw in enumerate(used_ranges_input):
        resolution, detail, artifact = _resolve_used_range(
            raw,
            index=index,
            available_roles=available_roles,
            artifact_paths_by_role=artifact_paths_by_role,
            line_counts=line_counts,
        )
        if detail is not None:
            used_ranges_block["unresolved"].append({"index": index, "detail": detail})
            add(
                "used_range_unresolved",
                SEVERITY_FAIL,
                "used_ranges",
                f"used_ranges[{index}]: {detail}",
                artifact=artifact,
            )
        elif resolution is not None:
            used_ranges_block["resolved"].append(resolution)
    checks.append(
        _check(
            "used_ranges",
            STATUS_FAIL if used_ranges_block["unresolved"] else STATUS_PASS,
            f"declared={len(used_ranges_input)} resolved={len(used_ranges_block['resolved'])} "
            f"unresolved={len(used_ranges_block['unresolved'])}",
        )
    )
    return used_ranges_block


def _records_by_role(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        role = record.get("role")
        if isinstance(role, str) and role:
            grouped.setdefault(role, []).append(dict(record))
    return grouped


def _resolve_linked_sidecar_paths(
    *,
    manifest_dir: Path,
    manifest_path: Path,
    links: Mapping[str, Any],
    add: Callable[..., None],
) -> dict[str, Path | None]:
    linked_paths: dict[str, Path | None] = {}
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
    return linked_paths


def _artifact_record_candidate(
    manifest_dir: Path, record: Mapping[str, Any]
) -> Path | None:
    absolute_path = record.get("absolute_path")
    if isinstance(absolute_path, str) and absolute_path:
        return Path(absolute_path)
    relative_path = record.get("path")
    if not isinstance(relative_path, str) or not relative_path:
        return None
    try:
        return resolve_secure_path(manifest_dir, relative_path)
    except ValueError:
        return None


def _resolve_artifact_paths(
    *,
    manifest_path: Path,
    manifest_dir: Path,
    records_by_role: Mapping[str, Sequence[Mapping[str, Any]]],
    linked_paths: Mapping[str, Path | None],
) -> dict[str, Path]:
    artifact_paths_by_role: dict[str, Path] = {"bundle_manifest": manifest_path}
    for role, role_records in records_by_role.items():
        for record in role_records:
            candidate = _artifact_record_candidate(manifest_dir, record)
            if candidate is not None:
                if candidate.is_file():
                    artifact_paths_by_role[role] = candidate
                    break
                artifact_paths_by_role.setdefault(role, candidate)
    for role, path in linked_paths.items():
        if path is not None:
            artifact_paths_by_role[role] = path
    return artifact_paths_by_role


def _manifest_role_availability(
    records_by_role: Mapping[str, Sequence[Mapping[str, Any]]],
    artifact_paths_by_role: Mapping[str, Path],
) -> tuple[set[str], set[str]]:
    available_roles: set[str] = {"bundle_manifest"}
    file_missing_roles: set[str] = set()
    for role, role_records in records_by_role.items():
        artifact_path = artifact_paths_by_role.get(role)
        recorded_file_exists = any(record.get("file_exists") for record in role_records)
        if recorded_file_exists and (artifact_path is None or artifact_path.is_file()):
            available_roles.add(role)
        else:
            file_missing_roles.add(role)
    return available_roles, file_missing_roles


def _linked_role_declared(links: Mapping[str, Any], role: str) -> bool:
    return any(
        links.get(key)
        for key, mapped in _LINKED_SIDECAR_ROLES.items()
        if mapped == role
    )


def _apply_linked_role_availability(
    available_roles: set[str],
    file_missing_roles: set[str],
    *,
    linked_paths: Mapping[str, Path | None],
    links: Mapping[str, Any],
) -> None:
    for role, path in linked_paths.items():
        if role in available_roles:
            continue
        if path is not None and path.is_file():
            available_roles.add(role)
        elif role in _LINKED_SIDECAR_ROLES.values() and _linked_role_declared(
            links, role
        ):
            file_missing_roles.add(role)
    file_missing_roles -= available_roles


def _record_task_profile_status(
    *,
    task_profile: str,
    task_profile_known: bool,
    protocol: Mapping[str, Any],
    checks: list[dict[str, str]],
    add: Callable[..., None],
) -> None:
    if task_profile_known:
        checks.append(
            _check(
                "task_profile", STATUS_PASS, f"task profile '{task_profile}' resolved"
            )
        )
        return
    checks.append(
        _check(
            "task_profile",
            STATUS_NA,
            f"task profile '{task_profile}' is not in the Required Reading Protocol",
        )
    )
    add(
        "task_profile_unknown",
        SEVERITY_INFO,
        "task_profile",
        f"task profile '{task_profile}' is not in the Required Reading Protocol; "
        f"known profiles: {', '.join(sorted(protocol['task_profiles']))}",
    )


def _record_missing_artifacts(
    missing_roles: Sequence[str],
    *,
    file_missing_roles: set[str],
    requirement: str,
    severity: str,
    area: str,
    code: str,
    add: Callable[..., None],
) -> None:
    for role in missing_roles:
        if role in file_missing_roles:
            detail = f"{requirement} artifact '{role}' is listed in the manifest but its file is missing"
        else:
            detail = f"{requirement} artifact '{role}' is not present in the bundle"
        add(code, severity, area, detail, artifact=role)


def _record_required_reading_checks(
    *,
    task_profile_known: bool,
    missing_required: Sequence[str],
    missing_recommended: Sequence[str],
    checks: list[dict[str, str]],
) -> None:
    if not task_profile_known:
        checks.append(
            _check(
                "required_artifacts",
                STATUS_NA,
                "no expectation without a known task profile",
            )
        )
        checks.append(
            _check(
                "recommended_artifacts",
                STATUS_NA,
                "no expectation without a known task profile",
            )
        )
        return
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


def _record_artifact_file_status(
    *,
    file_missing_roles: set[str],
    required_role_set: set[str],
    recommended_role_set: set[str],
    checks: list[dict[str, str]],
    add: Callable[..., None],
) -> None:
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
        artifact_files_status = (
            STATUS_FAIL if file_missing_roles & required_role_set else STATUS_WARN
        )
    else:
        artifact_files_status = STATUS_PASS
    checks.append(
        _check(
            "artifact_files",
            artifact_files_status,
            f"manifest-listed roles without files: {', '.join(sorted(file_missing_roles)) if file_missing_roles else 'none'}",
        )
    )


def _artifact_requirement(
    role: str, required_role_set: set[str], recommended_role_set: set[str]
) -> str:
    if role in required_role_set:
        return REQUIREMENT_REQUIRED
    if role in recommended_role_set:
        return REQUIREMENT_RECOMMENDED
    return REQUIREMENT_NA


def _artifact_availability(
    role: str, available_roles: set[str], file_missing_roles: set[str]
) -> str:
    if role in available_roles:
        return AVAILABILITY_AVAILABLE
    if role in file_missing_roles:
        return AVAILABILITY_FILE_MISSING
    return AVAILABILITY_MISSING


def _artifact_status(
    role: str,
    *,
    manifest_path: Path,
    records_by_role: Mapping[str, Sequence[Mapping[str, Any]]],
    linked_paths: Mapping[str, Path | None],
    artifact_paths_by_role: Mapping[str, Path],
    available_roles: set[str],
    file_missing_roles: set[str],
    required_role_set: set[str],
    recommended_role_set: set[str],
) -> PreflightArtifactStatus:
    role_records = records_by_role.get(role)
    record: Mapping[str, Any] = role_records[0] if role_records else {}
    if role == "bundle_manifest" and not record:
        record = {"path": manifest_path.name, "file_exists": True}
    linked = linked_paths.get(role)
    mapped_path = artifact_paths_by_role.get(role)
    resolved_path_value = str(mapped_path) if mapped_path is not None else None
    path_value = record.get("path")
    if path_value is None and linked is not None:
        path_value = str(linked)
    availability = _artifact_availability(role, available_roles, file_missing_roles)
    return PreflightArtifactStatus(
        role=role,
        requirement=_artifact_requirement(
            role, required_role_set, recommended_role_set
        ),
        availability=availability,
        file_exists=availability == AVAILABILITY_AVAILABLE,
        path=path_value if isinstance(path_value, str) else None,
        resolved_path=resolved_path_value,
        authority=record.get("authority")
        if isinstance(record.get("authority"), str)
        else None,
        canonicality=record.get("canonicality")
        if isinstance(record.get("canonicality"), str)
        else None,
    )


def _build_artifact_statuses(
    *,
    manifest_path: Path,
    records_by_role: Mapping[str, Sequence[Mapping[str, Any]]],
    linked_paths: Mapping[str, Path | None],
    artifact_paths_by_role: Mapping[str, Path],
    available_roles: set[str],
    file_missing_roles: set[str],
    required_role_set: set[str],
    recommended_role_set: set[str],
) -> list[PreflightArtifactStatus]:
    listed_roles = set(records_by_role) | set(linked_paths) | {"bundle_manifest"}
    return [
        _artifact_status(
            role,
            manifest_path=manifest_path,
            records_by_role=records_by_role,
            linked_paths=linked_paths,
            artifact_paths_by_role=artifact_paths_by_role,
            available_roles=available_roles,
            file_missing_roles=file_missing_roles,
            required_role_set=required_role_set,
            recommended_role_set=recommended_role_set,
        )
        for role in sorted(required_role_set | recommended_role_set | listed_roles)
    ]


def _build_evidence_layers(
    artifact_statuses: Sequence[PreflightArtifactStatus],
) -> dict[str, list[str]]:
    evidence_layers: dict[str, list[str]] = {layer: [] for layer in _AUTHORITY_LAYERS}
    evidence_layers["unspecified"] = []
    for status in artifact_statuses:
        if status.availability != AVAILABILITY_AVAILABLE:
            continue
        layer = (
            status.authority if status.authority in _AUTHORITY_LAYERS else "unspecified"
        )
        evidence_layers[layer].append(status.role)
    return evidence_layers


def _record_snapshot_profile_findings(
    snapshot_profile: str,
    evaluation: Mapping[str, Any],
    *,
    add: Callable[..., None],
) -> None:
    for role in evaluation["missing_required"]:
        add(
            "snapshot_profile_missing_required",
            SEVERITY_FAIL,
            "validation",
            f"snapshot profile '{snapshot_profile}' requires artifact '{role}' but the manifest does not provide it",
            artifact=role,
        )
    for role in evaluation["profile_excluded_present"]:
        add(
            "snapshot_profile_excluded_present",
            SEVERITY_FAIL,
            "validation",
            f"snapshot profile '{snapshot_profile}' excludes artifact '{role}' but the manifest still lists it",
            artifact=role,
        )
    for role in evaluation["missing_recommended"]:
        add(
            "snapshot_profile_missing_recommended",
            SEVERITY_WARN,
            "validation",
            f"snapshot profile '{snapshot_profile}' recommends artifact '{role}' but the manifest does not provide it",
            artifact=role,
        )


def _evaluate_snapshot_profile_policy(
    manifest: Mapping[str, Any],
    *,
    checks: list[dict[str, str]],
    add: Callable[..., None],
) -> tuple[str | None, dict[str, Any] | None]:
    capabilities = (
        manifest.get("capabilities")
        if isinstance(manifest.get("capabilities"), dict)
        else {}
    )
    snapshot_profile = capabilities.get("repobrief_profile")
    if not isinstance(snapshot_profile, str) or not snapshot_profile:
        checks.append(
            _check(
                "snapshot_profile_policy",
                STATUS_NA,
                "manifest carries no repobrief_profile label",
            )
        )
        return None, None
    if snapshot_profile not in profile_names():
        checks.append(
            _check(
                "snapshot_profile_policy",
                STATUS_WARN,
                f"unknown snapshot profile label '{snapshot_profile}'",
            )
        )
        add(
            "snapshot_profile_unknown",
            SEVERITY_WARN,
            "validation",
            f"manifest labels an unknown RepoGround snapshot profile '{snapshot_profile}'",
        )
        return snapshot_profile, None
    evaluation = evaluate_profile(
        snapshot_profile, present_roles_from_manifest(manifest)
    )
    profile_status = evaluation["status"]
    checks.append(
        _check(
            "snapshot_profile_policy",
            profile_status
            if profile_status in {STATUS_PASS, STATUS_WARN, STATUS_FAIL}
            else STATUS_WARN,
            f"snapshot profile '{snapshot_profile}' evaluated {profile_status}",
        )
    )
    _record_snapshot_profile_findings(snapshot_profile, evaluation, add=add)
    return snapshot_profile, evaluation


def _ordered_findings_and_status(
    findings: Sequence[PreflightFinding],
    *,
    task_profile_known: bool,
) -> tuple[tuple[PreflightFinding, ...], str]:
    severity_order = {SEVERITY_FAIL: 0, SEVERITY_WARN: 1, SEVERITY_INFO: 2}
    ordered_findings = tuple(
        sorted(
            findings,
            key=lambda f: (
                severity_order[f.severity],
                f.code,
                f.artifact or "",
                f.detail,
            ),
        )
    )
    if any(f.severity == SEVERITY_FAIL for f in ordered_findings):
        return ordered_findings, STATUS_FAIL
    if not task_profile_known:
        return ordered_findings, STATUS_NA
    if any(f.severity == SEVERITY_WARN for f in ordered_findings):
        return ordered_findings, STATUS_WARN
    return ordered_findings, STATUS_PASS


def _ordered_checks(
    checks: Sequence[Mapping[str, str]],
) -> tuple[Mapping[str, str], ...]:
    check_order = {
        name: i
        for i, name in enumerate(
            (
                "task_profile",
                "required_artifacts",
                "recommended_artifacts",
                "artifact_files",
                "snapshot_profile_policy",
                "validation_state",
                "freshness",
                "live_head",
                "used_citations",
                "used_ranges",
                "does_not_establish",
            )
        )
    }
    return tuple(
        sorted(checks, key=lambda c: check_order.get(c["name"], len(check_order)))
    )


def consumption_preflight(preflight_input: PreflightInput) -> PreflightResult:
    """Run the RepoGround agent consumption preflight for one bundle manifest.

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

    def add(
        code: str,
        severity: str,
        area: str,
        detail: str,
        artifact: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        findings.append(
            PreflightFinding(
                code=code,
                severity=severity,
                area=area,
                detail=detail,
                artifact=artifact,
                context=context,
            )
        )

    # ── Effective availability: manifest role + file on disk ────────────────
    records_by_role = _records_by_role(records)
    links = manifest.get("links") if isinstance(manifest.get("links"), dict) else {}
    linked_paths = _resolve_linked_sidecar_paths(
        manifest_dir=manifest_dir,
        manifest_path=manifest_path,
        links=links,
        add=add,
    )
    artifact_paths_by_role = _resolve_artifact_paths(
        manifest_path=manifest_path,
        manifest_dir=manifest_dir,
        records_by_role=records_by_role,
        linked_paths=linked_paths,
    )
    available_roles, file_missing_roles = _manifest_role_availability(
        records_by_role,
        artifact_paths_by_role,
    )
    _apply_linked_role_availability(
        available_roles,
        file_missing_roles,
        linked_paths=linked_paths,
        links=links,
    )

    # ── Task profile expectation (Required Reading Protocol, reused) ────────
    protocol = default_required_reading_protocol()
    required_reading = resolve_required_reading(
        protocol, available_roles, preflight_input.task_profile
    )
    task_profile_known = required_reading["status"] != STATUS_NA
    _record_task_profile_status(
        task_profile=preflight_input.task_profile,
        task_profile_known=task_profile_known,
        protocol=protocol,
        checks=checks,
        add=add,
    )

    required_roles = list(required_reading["required"])
    recommended_roles = list(required_reading["recommended"])
    missing_required = list(required_reading["missing_required"])
    missing_recommended = list(required_reading["missing_recommended"])
    required_role_set = set(required_roles)
    recommended_role_set = set(recommended_roles)

    def add_sidecar_read_failure(role: str, detail: str) -> None:
        if role in required_role_set:
            add(
                "validation_required_sidecar_unreadable",
                SEVERITY_FAIL,
                "validation",
                detail,
                artifact=role,
            )
        else:
            add(
                "validation_unreadable",
                SEVERITY_WARN,
                "validation",
                detail,
                artifact=role,
            )

    _record_missing_artifacts(
        missing_required,
        file_missing_roles=file_missing_roles,
        requirement="required",
        severity=SEVERITY_FAIL,
        area="required_artifacts",
        code="missing_required_artifact",
        add=add,
    )
    _record_missing_artifacts(
        missing_recommended,
        file_missing_roles=file_missing_roles,
        requirement="recommended",
        severity=SEVERITY_WARN,
        area="recommended_artifacts",
        code="missing_recommended_artifact",
        add=add,
    )
    _record_required_reading_checks(
        task_profile_known=task_profile_known,
        missing_required=missing_required,
        missing_recommended=missing_recommended,
        checks=checks,
    )
    _record_artifact_file_status(
        file_missing_roles=file_missing_roles,
        required_role_set=required_role_set,
        recommended_role_set=recommended_role_set,
        checks=checks,
        add=add,
    )

    artifact_statuses = _build_artifact_statuses(
        manifest_path=manifest_path,
        records_by_role=records_by_role,
        linked_paths=linked_paths,
        artifact_paths_by_role=artifact_paths_by_role,
        available_roles=available_roles,
        file_missing_roles=file_missing_roles,
        required_role_set=required_role_set,
        recommended_role_set=recommended_role_set,
    )
    evidence_layers = _build_evidence_layers(artifact_statuses)

    # ── Snapshot profile policy (generation-side, re-evaluated) ─────────────
    snapshot_profile, snapshot_profile_evaluation = _evaluate_snapshot_profile_policy(
        manifest,
        checks=checks,
        add=add,
    )

    # ── Degraded validation states (diagnostic layer, never hidden) ─────────
    validation = _evaluate_validation_state(
        linked_paths=linked_paths,
        links=links,
        artifact_paths_by_role=artifact_paths_by_role,
        snapshot_profile_evaluation=snapshot_profile_evaluation,
        manifest_path=manifest_path,
        manifest_run_id=manifest_run_id,
        findings=findings,
        checks=checks,
        add=add,
        add_sidecar_read_failure=add_sidecar_read_failure,
    )

    # ── Freshness / provenance visibility ───────────────────────────────────
    freshness = _evaluate_freshness(
        manifest=manifest,
        preflight_input=preflight_input,
        checks=checks,
        add=add,
    )
    live_head = None
    if preflight_input.live_repo is not None:
        snapshot_provenance = manifest.get("snapshot_provenance")
        snapshot_repositories = (
            snapshot_provenance.get("repositories")
            if isinstance(snapshot_provenance, Mapping)
            else []
        )
        if not isinstance(snapshot_repositories, list):
            snapshot_repositories = []
        live_head = _evaluate_live_head(
            live_repo=preflight_input.live_repo,
            snapshot_repositories=snapshot_repositories,
            checks=checks,
            add=add,
        )

    # ── Consumption declaration (negative semantics are mandatory) ──────────
    declaration_block, used_citations_input, used_ranges_input = (
        _prepare_consumption_declaration(
            preflight_input=preflight_input,
            checks=checks,
            add=add,
        )
    )

    # ── Used citations: resolve against the citation map ────────────────────
    used_citations_block = _evaluate_used_citations(
        used_citations_input=used_citations_input,
        available_roles=available_roles,
        artifact_paths_by_role=artifact_paths_by_role,
        findings=findings,
        checks=checks,
        add=add,
    )

    # ── Used ranges: bind to available artifacts and line bounds ────────────
    used_ranges_block = _evaluate_used_ranges(
        used_ranges_input=used_ranges_input,
        available_roles=available_roles,
        artifact_paths_by_role=artifact_paths_by_role,
        checks=checks,
        add=add,
    )

    # ── Aggregate: fail > not_applicable (unknown profile) > warn > pass ────
    ordered_findings, overall = _ordered_findings_and_status(
        findings,
        task_profile_known=task_profile_known,
    )
    ordered_checks = _ordered_checks(checks)

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
        "evidence_layers": {
            layer: sorted(roles) for layer, roles in evidence_layers.items()
        },
        "validation": validation,
        "freshness": freshness,
        "used_citations": used_citations_block,
        "used_ranges": used_ranges_block,
        "declaration": declaration_block,
        "required_reading": required_reading,
        "checks": list(ordered_checks),
        "findings": [f.to_dict() for f in ordered_findings],
        "finding_counts": {
            SEVERITY_FAIL: sum(
                1 for f in ordered_findings if f.severity == SEVERITY_FAIL
            ),
            SEVERITY_WARN: sum(
                1 for f in ordered_findings if f.severity == SEVERITY_WARN
            ),
            SEVERITY_INFO: sum(
                1 for f in ordered_findings if f.severity == SEVERITY_INFO
            ),
        },
        "mutation_boundary": json.loads(json.dumps(MUTATION_BOUNDARY)),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    if live_head is not None:
        data["live_head"] = live_head

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
    live_repo: str | Path | None = None,
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
            live_repo=live_repo,
        )
    )
    return result.to_dict()
