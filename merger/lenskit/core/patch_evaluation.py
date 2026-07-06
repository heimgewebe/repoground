"""Read-only consumer/validator for external Patch Evaluation artifacts (v1).

This module is the RepoBrief-side, read-only consumption surface for
``repobrief.patch_evaluation`` v1 artifacts that are emitted by the *external*
Patch Evaluation Sidecar (see
``docs/architecture/repobrief-agent-workbench-boundary.md`` and
``docs/contracts/patch-evaluation-v1.md``).

It deliberately does very little: it reads JSON, validates it against the v1
schema, and projects the declared status and non-claims into a bounded summary
that is explicitly labelled as ``external_evaluation_evidence``. It is a court
clerk, not a judge — it checks form and records evidence; it does not bang the
gavel.

It does NOT and MUST NOT:

- mutate Git state,
- create branches, worktrees, or pull requests,
- write, apply, or repair patches,
- run shells, tests, linters, or sandboxes,
- read secrets,
- claim merge readiness or merge authorization,
- emit a review verdict.

A validation ``pass`` means only that the artifact matches the v1 schema. It
never means the evaluated patch is correct, sufficiently tested, secure,
regression-free, or safe to merge.
"""
from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from merger.lenskit.core.dependency_diagnostics import jsonschema_dependency

ARTIFACT_KIND = "repobrief.patch_evaluation"
ARTIFACT_VERSION = "v1"
ARTIFACT_AUTHORITY = "external_evaluation_evidence"

KIND = "repobrief.patch_evaluation_consumption"
VERSION = "v1"
ENGINE = "patch_evaluation_consumer"

# The nine mandatory non-claims the artifact itself must declare.
REQUIRED_DOES_NOT_ESTABLISH = (
    "correctness",
    "test_sufficiency",
    "security_correctness",
    "runtime_behavior_outside_evaluated_commands",
    "merge_authorization",
    "merge_readiness",
    "regression_absence",
    "repo_understood",
    "claims_true",
)

# What a consumption PASS does NOT prove (consumer-level negative semantics,
# distinct from the artifact-level does_not_establish vocabulary). Consuming a
# well-formed artifact adds no authority of its own.
CONSUMER_DOES_NOT_ESTABLISH = (
    "truth",
    "correctness",
    "test_sufficiency",
    "security_correctness",
    "runtime_behavior_outside_evaluated_commands",
    "regression_absence",
    "repo_understood",
    "claims_true",
    "merge_readiness",
    "merge_authorization",
    "review_completeness",
    "producer_honesty",
    "snapshot_freshness",
)

_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "contracts" / "patch-evaluation.v1.schema.json"
)
_STATUS_WEIGHT = {"pass": 0, "warn": 1, "fail": 2}

_COMMAND_STATUSES = ("passed", "failed", "error", "skipped", "timeout")


def load_patch_evaluation(path_or_obj: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    """Read a patch-evaluation artifact from a path or accept an in-memory mapping.

    This is a pure read. It opens and parses JSON only; it never fetches,
    refreshes, executes, or mutates anything. A ``Mapping`` is accepted so callers
    can validate an already-loaded object without a second file read.

    Raises ``ValueError`` if the source cannot be read or is not a JSON object.
    """
    if isinstance(path_or_obj, Mapping):
        return dict(path_or_obj)
    path = Path(path_or_obj)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"patch-evaluation artifact could not be read: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"patch-evaluation artifact is not valid JSON: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ValueError("patch-evaluation artifact must be a JSON object")
    return dict(data)


def _load_jsonschema() -> tuple[Any | None, str | None]:
    try:
        return importlib.import_module("jsonschema"), None
    except Exception as exc:  # pragma: no cover - exact import error varies by host.
        return None, f"{type(exc).__name__}: {exc}"


def _load_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _schema_error_path(error: Any) -> str:
    parts = [str(part) for part in error.path]
    return "$" if not parts else "$." + ".".join(parts)


def _schema_errors(errors: list[Any]) -> list[dict[str, str]]:
    ordered = sorted(
        errors,
        key=lambda error: (
            tuple(str(part) for part in error.path),
            tuple(str(part) for part in error.schema_path),
            error.message,
        ),
    )
    return [
        {
            "path": _schema_error_path(error),
            "validator": str(error.validator),
            "message": error.message,
        }
        for error in ordered
    ]


def _check(name: str, status: str, detail: str, *, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"name": name, "status": status, "detail": detail}
    if extra:
        result.update(extra)
    return result


def _rollup(checks: list[Mapping[str, Any]]) -> str:
    worst = "pass"
    for check in checks:
        status = check.get("status")
        if isinstance(status, str) and _STATUS_WEIGHT.get(status, 0) > _STATUS_WEIGHT[worst]:
            worst = status
    return worst


def validate_patch_evaluation(
    data: Mapping[str, Any],
    *,
    schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate an artifact against the patch-evaluation v1 schema, fail-closed.

    Returns a lens-family validation report (``kind`` / ``status`` /
    ``checks[]`` / ``dependencies`` / ``does_not_establish``). ``status`` is
    ``pass`` only when the artifact matches the v1 schema. If ``jsonschema`` is
    unavailable the single ``schema_validation`` check fails (degraded), because
    RepoBrief must not silently accept unvalidated external evidence.
    """
    checks: list[dict[str, Any]] = []
    jsonschema, import_error = _load_jsonschema()
    jsonschema_available = jsonschema is not None

    if jsonschema is None:
        checks.append(
            _check(
                "schema_validation",
                "fail",
                "jsonschema is unavailable; patch-evaluation validation cannot run",
                extra={"error": import_error or "jsonschema unavailable"},
            )
        )
        return _assemble(checks, jsonschema_available=jsonschema_available)

    active_schema = schema if schema is not None else _load_schema()
    try:
        jsonschema.Draft7Validator.check_schema(active_schema)
        validator = jsonschema.Draft7Validator(active_schema)
        errors = list(validator.iter_errors(data))
    except Exception as exc:
        checks.append(
            _check(
                "schema_validation",
                "fail",
                f"patch-evaluation schema could not be used: {type(exc).__name__}: {exc}",
            )
        )
        return _assemble(checks, jsonschema_available=jsonschema_available)

    if errors:
        checks.append(
            _check(
                "schema_validation",
                "fail",
                f"patch-evaluation schema validation failed with {len(errors)} error(s)",
                extra={"errors": _schema_errors(errors)},
            )
        )
    else:
        checks.append(
            _check(
                "schema_validation",
                "pass",
                "patch-evaluation artifact matches the v1 schema",
            )
        )
    return _assemble(checks, jsonschema_available=jsonschema_available)


def _assemble(checks: list[dict[str, Any]], *, jsonschema_available: bool) -> dict[str, Any]:
    return {
        "kind": KIND,
        "version": VERSION,
        "status": _rollup(checks),
        "authority": ARTIFACT_AUTHORITY,
        "checks": checks,
        "dependencies": jsonschema_dependency(
            available=jsonschema_available,
            required_for=["patch_evaluation_schema"],
        ),
        "does_not_establish": list(CONSUMER_DOES_NOT_ESTABLISH),
    }


def _as_list(value: Any) -> list[Any]:
    """Return a shallow copy if ``value`` is a list, else ``[]``.

    The summary path runs on artifacts that have not necessarily passed schema
    validation (e.g. the ``--summary`` CLI flag summarizes regardless of the
    validation verdict). A malformed scalar in a field that the schema declares
    as an array must therefore degrade to an empty list here rather than raise a
    ``TypeError`` from ``list(scalar)`` — this stays read-only and never turns a
    bad artifact into a traceback. A string is intentionally treated as invalid
    (empty), not splatted into characters.
    """
    return list(value) if isinstance(value, list) else []


def _as_string_set(value: Any) -> set[str]:
    """Return string members from a possibly malformed list field.

    Diagnostics may run before schema validation has accepted the artifact.
    Keep them total for malformed evidence surfaces: ignore non-string members
    instead of raising from ``set([{}])``.
    """
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str)}


def _command_status_counts(commands: Any) -> dict[str, int]:
    counts = {status: 0 for status in _COMMAND_STATUSES}
    counts["unknown"] = 0
    if isinstance(commands, list):
        for command in commands:
            status = command.get("status") if isinstance(command, Mapping) else None
            if isinstance(status, str) and status in counts:
                counts[status] += 1
            else:
                counts["unknown"] += 1
    return counts


def summarize_patch_evaluation(data: Mapping[str, Any]) -> dict[str, Any]:
    """Project the artifact into a bounded, read-only summary.

    The summary always pins ``authority`` to ``external_evaluation_evidence`` and
    echoes the artifact's declared ``does_not_establish`` verbatim, so a caller
    cannot mistake the summary for an approval. Cited ranges/citations are
    surfaced only as reference lists, never resolved or acted upon.
    """
    commands = data.get("commands_run")
    repobrief_context = data.get("repobrief_context")
    if not isinstance(repobrief_context, Mapping):
        repobrief_context = {}
    producer = data.get("producer") if isinstance(data.get("producer"), Mapping) else {}

    return {
        "kind": KIND,
        "version": VERSION,
        # Authority is asserted here, never upgraded, regardless of declared status.
        "authority": ARTIFACT_AUTHORITY,
        "artifact_kind": data.get("kind"),
        "artifact_version": data.get("version"),
        "producer": {
            "name": producer.get("name"),
            "version": producer.get("version"),
        },
        "created_at": data.get("created_at"),
        "declared_status": data.get("status"),
        "command_count": len(commands) if isinstance(commands, list) else 0,
        "command_status_counts": _command_status_counts(commands),
        "workspace_isolated": (
            data.get("workspace", {}).get("isolated")
            if isinstance(data.get("workspace"), Mapping)
            else None
        ),
        "patch_applied": (
            data.get("patch", {}).get("applied")
            if isinstance(data.get("patch"), Mapping)
            else None
        ),
        "referenced_citations": _as_list(repobrief_context.get("citations")),
        "referenced_ranges": _as_list(repobrief_context.get("cited_ranges")),
        "referenced_workbench_outputs": _as_list(repobrief_context.get("workbench_outputs")),
        # The artifact's own declared non-claims, surfaced verbatim.
        "does_not_establish": _as_list(data.get("does_not_establish")),
        # Consuming this artifact adds no authority of its own.
        "consumer_does_not_establish": list(CONSUMER_DOES_NOT_ESTABLISH),
    }


def patch_evaluation_diagnostics(data: Mapping[str, Any]) -> dict[str, Any]:
    """Report structured, non-fatal observations about an artifact.

    This surfaces missing/soft fields as diagnostics without executing anything.
    It complements :func:`validate_patch_evaluation` (which is fail-closed on
    schema conformance) by describing softer degradations a consumer should be
    aware of, e.g. a missing mandatory non-claim, a non-isolated workspace, or
    no recorded commands.
    """
    missing_required_top: list[str] = []
    for field in ("kind", "version", "status", "does_not_establish", "commands_run"):
        if field not in data:
            missing_required_top.append(field)

    declared = data.get("does_not_establish")
    declared_set = _as_string_set(declared)
    missing_non_claims = [
        claim for claim in REQUIRED_DOES_NOT_ESTABLISH if claim not in declared_set
    ]

    workspace = data.get("workspace") if isinstance(data.get("workspace"), Mapping) else {}
    workspace_isolated = workspace.get("isolated") if isinstance(workspace, Mapping) else None

    commands = data.get("commands_run")
    command_count = len(commands) if isinstance(commands, list) else 0

    degradations: list[dict[str, str]] = []
    if data.get("kind") != ARTIFACT_KIND:
        degradations.append(
            {"class": "unexpected_kind", "detail": f"kind is {data.get('kind')!r}, expected {ARTIFACT_KIND!r}"}
        )
    if data.get("authority") != ARTIFACT_AUTHORITY:
        degradations.append(
            {"class": "unexpected_authority", "detail": f"authority is {data.get('authority')!r}, expected {ARTIFACT_AUTHORITY!r}"}
        )
    if missing_non_claims:
        degradations.append(
            {"class": "missing_non_claims", "detail": "artifact omits mandatory non-claims: " + ", ".join(missing_non_claims)}
        )
    if workspace_isolated is not True:
        degradations.append(
            {"class": "workspace_not_isolated", "detail": f"workspace.isolated is {workspace_isolated!r}; evaluation isolation is not asserted"}
        )
    if command_count == 0:
        degradations.append(
            {"class": "no_commands_recorded", "detail": "commands_run is empty; no execution evidence is present"}
        )

    return {
        "kind": KIND,
        "version": VERSION,
        "authority": ARTIFACT_AUTHORITY,
        "missing_required_top": missing_required_top,
        "missing_non_claims": missing_non_claims,
        "workspace_isolated": workspace_isolated,
        "command_count": command_count,
        "degradations": degradations,
        "does_not_establish": list(CONSUMER_DOES_NOT_ESTABLISH),
    }
