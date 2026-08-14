"""Deterministic budget planning for manual runtime-artifact GC."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping, Sequence

from .runtime_artifact_gc_support import (
    GC_PLAN_KIND,
    GC_PLAN_VERSION,
    RuntimeArtifactGCError,
    canonical_json,
    entry_index,
    iso_z,
    normalize_protection,
    parse_aware_datetime,
    protected_artifacts,
    sha256_json,
    validated_budgets,
)
from .runtime_artifact_retention import RUNTIME_ARTIFACT_TYPES


def _entry_size(entry: Mapping[str, Any]) -> int:
    return len(canonical_json(entry).encode("utf-8"))


def _entry_created_at(artifact_id: str, value: Any) -> datetime | None:
    try:
        return parse_aware_datetime(value, label=f"{artifact_id}.created_at")
    except RuntimeArtifactGCError:
        return None


def _collect_entry_info(
    index: Mapping[str, Mapping[str, Any]],
    protected: Dict[str, set[str]],
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, list[str]]]:
    info: Dict[str, Dict[str, Any]] = {}
    by_type: Dict[str, list[str]] = {artifact_type: [] for artifact_type in RUNTIME_ARTIFACT_TYPES}
    for artifact_id, entry in index.items():
        artifact_type = entry.get("artifact_type")
        created_raw = entry.get("created_at")
        created_dt = None
        if artifact_type in RUNTIME_ARTIFACT_TYPES:
            created_dt = _entry_created_at(artifact_id, created_raw)
            by_type[artifact_type].append(artifact_id)
            if created_dt is None:
                protected.setdefault(artifact_id, set()).add("created_at_unknown")
        else:
            protected.setdefault(artifact_id, set()).add("unknown_artifact_type")
        info[artifact_id] = {
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "created_at": created_raw if isinstance(created_raw, str) else None,
            "created_dt": created_dt,
            "estimated_bytes": _entry_size(entry),
            "entry_sha256": sha256_json(entry),
        }
    return info, by_type


def _ordered_ids(ids: Sequence[str], info: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return sorted(
        ids,
        key=lambda artifact_id: (
            info[artifact_id]["created_dt"] is None,
            info[artifact_id]["created_dt"] or datetime.max.replace(tzinfo=timezone.utc),
            artifact_id,
        ),
    )


def _add_candidate(
    reasons: Dict[str, set[str]],
    protected: Mapping[str, Any],
    artifact_id: str,
    reason: str,
) -> None:
    if artifact_id not in protected:
        reasons.setdefault(artifact_id, set()).add(reason)


def _mark_age_pressure(
    *,
    ordered: Sequence[str],
    info: Mapping[str, Mapping[str, Any]],
    protected: Mapping[str, Any],
    reasons: Dict[str, set[str]],
    cutoff: datetime,
) -> None:
    for artifact_id in ordered:
        created_dt = info[artifact_id]["created_dt"]
        if created_dt is not None and created_dt < cutoff:
            _add_candidate(reasons, protected, artifact_id, "age_budget")


def _mark_count_pressure(
    *,
    ordered: Sequence[str],
    protected: Mapping[str, Any],
    reasons: Dict[str, set[str]],
    count_to_release: int,
) -> None:
    marked = 0
    for artifact_id in ordered:
        if marked >= count_to_release:
            return
        if artifact_id in protected:
            continue
        _add_candidate(reasons, protected, artifact_id, "count_budget")
        marked += 1


def _mark_byte_pressure(
    *,
    ordered: Sequence[str],
    info: Mapping[str, Mapping[str, Any]],
    protected: Mapping[str, Any],
    reasons: Dict[str, set[str]],
    bytes_to_release: int,
) -> None:
    marked = 0
    for artifact_id in ordered:
        if marked >= bytes_to_release:
            return
        if artifact_id in protected:
            continue
        _add_candidate(reasons, protected, artifact_id, "bytes_budget")
        marked += int(info[artifact_id]["estimated_bytes"])


def _selected_ids(
    *,
    artifact_type: str,
    reasons: Mapping[str, Any],
    info: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    return {
        artifact_id
        for artifact_id in reasons
        if info[artifact_id]["artifact_type"] == artifact_type
    }


def _mark_type_budget_pressure(
    *,
    artifact_type: str,
    ids: Sequence[str],
    budget: Mapping[str, int],
    info: Mapping[str, Mapping[str, Any]],
    protected: Mapping[str, Any],
    reasons: Dict[str, set[str]],
    as_of_dt: datetime,
) -> Dict[str, int]:
    ordered = _ordered_ids(ids, info)
    _mark_age_pressure(
        ordered=ordered,
        info=info,
        protected=protected,
        reasons=reasons,
        cutoff=as_of_dt - timedelta(seconds=budget["max_age_seconds"]),
    )
    _mark_count_pressure(
        ordered=ordered,
        protected=protected,
        reasons=reasons,
        count_to_release=max(0, len(ids) - budget["max_count"]),
    )
    total_bytes = sum(int(info[artifact_id]["estimated_bytes"]) for artifact_id in ids)
    _mark_byte_pressure(
        ordered=ordered,
        info=info,
        protected=protected,
        reasons=reasons,
        bytes_to_release=max(0, total_bytes - budget["max_bytes"]),
    )
    selected = _selected_ids(artifact_type=artifact_type, reasons=reasons, info=info)
    remaining_count = len(ids) - len(selected)
    remaining_bytes = total_bytes - sum(
        int(info[artifact_id]["estimated_bytes"]) for artifact_id in selected
    )
    return {
        "count_over_budget": max(0, remaining_count - budget["max_count"]),
        "bytes_over_budget": max(0, remaining_bytes - budget["max_bytes"]),
    }


def _candidate_rows(
    reasons: Mapping[str, set[str]], info: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    ordered = sorted(
        reasons,
        key=lambda artifact_id: (
            str(info[artifact_id]["artifact_type"]),
            info[artifact_id]["created_dt"] or datetime.max.replace(tzinfo=timezone.utc),
            artifact_id,
        ),
    )
    return [
        {
            "artifact_id": artifact_id,
            "artifact_type": info[artifact_id]["artifact_type"],
            "created_at": info[artifact_id]["created_at"],
            "estimated_bytes": info[artifact_id]["estimated_bytes"],
            "entry_sha256": info[artifact_id]["entry_sha256"],
            "reasons": sorted(reasons[artifact_id]),
        }
        for artifact_id in ordered
    ]


def _unresolved_budgets(
    *,
    by_type: Mapping[str, Sequence[str]],
    budgets: Mapping[str, Mapping[str, int]],
    info: Mapping[str, Mapping[str, Any]],
    protected: Mapping[str, Any],
    reasons: Dict[str, set[str]],
    as_of_dt: datetime,
) -> Dict[str, Dict[str, int]]:
    return {
        artifact_type: _mark_type_budget_pressure(
            artifact_type=artifact_type,
            ids=by_type[artifact_type],
            budget=budgets[artifact_type],
            info=info,
            protected=protected,
            reasons=reasons,
            as_of_dt=as_of_dt,
        )
        for artifact_type in RUNTIME_ARTIFACT_TYPES
    }


def build_retention_plan(
    *,
    entries: Sequence[Mapping[str, Any]],
    store_sha256: str,
    protection: Mapping[str, Any],
    as_of: str,
    profile_id: str,
    budgets: Mapping[str, Any],
) -> Dict[str, Any]:
    """Build one deterministic, effect-free plan from an exact store snapshot."""
    if (
        not isinstance(store_sha256, str)
        or len(store_sha256) != 64
        or any(character not in "0123456789abcdef" for character in store_sha256)
    ):
        raise RuntimeArtifactGCError("invalid_store_sha256", "store_sha256 must be a SHA-256 hex digest")
    as_of_dt = parse_aware_datetime(as_of, label="as_of")
    validated = validated_budgets(budgets)
    explicit_protected, canonical_protection = protected_artifacts(entries, protection)
    index = entry_index(entries)
    protected: Dict[str, set[str]] = {
        artifact_id: set(values) for artifact_id, values in explicit_protected.items()
    }
    info, by_type = _collect_entry_info(index, protected)
    reasons: Dict[str, set[str]] = {}
    unresolved = _unresolved_budgets(
        by_type=by_type,
        budgets=validated,
        info=info,
        protected=protected,
        reasons=reasons,
        as_of_dt=as_of_dt,
    )
    candidates = _candidate_rows(reasons, info)
    body: Dict[str, Any] = {
        "kind": GC_PLAN_KIND,
        "schema_version": GC_PLAN_VERSION,
        "profile_id": profile_id,
        "as_of": iso_z(as_of_dt),
        "store_sha256": store_sha256,
        "protection_sha256": sha256_json(canonical_protection),
        "protection": canonical_protection,
        "budgets": validated,
        "automatic_delete": False,
        "requires_explicit_apply": True,
        "candidates": candidates,
        "protected": [
            {"artifact_id": artifact_id, "reasons": sorted(values)}
            for artifact_id, values in sorted(protected.items())
        ],
        "unresolved_budgets": unresolved,
        "expected_release": {
            "objects": len(candidates),
            "estimated_bytes": sum(int(item["estimated_bytes"]) for item in candidates),
        },
        "does_not_establish": [
            "apply_authority",
            "future_reference_state",
            "future_store_identity",
            "automatic_deletion",
        ],
    }
    body["plan_sha256"] = sha256_json(body)
    return body


def verify_retention_plan(plan: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(plan, Mapping):
        raise RuntimeArtifactGCError("invalid_plan", "plan must be an object")
    rendered = json.loads(json.dumps(plan))
    provided = rendered.pop("plan_sha256", None)
    if (
        not isinstance(provided, str)
        or len(provided) != 64
        or any(character not in "0123456789abcdef" for character in provided)
    ):
        raise RuntimeArtifactGCError("invalid_plan", "plan_sha256 is missing or malformed")
    if rendered.get("kind") != GC_PLAN_KIND or rendered.get("schema_version") != GC_PLAN_VERSION:
        raise RuntimeArtifactGCError("invalid_plan", "unsupported plan kind or schema version")
    if provided != sha256_json(rendered):
        raise RuntimeArtifactGCError("plan_hash_mismatch", "plan content does not match plan_sha256")
    rendered["plan_sha256"] = provided
    validated_budgets(rendered.get("budgets"))
    normalize_protection(rendered.get("protection"))
    return rendered
