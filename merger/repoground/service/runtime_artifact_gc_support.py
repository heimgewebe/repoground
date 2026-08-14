"""Validation and protection helpers for manual runtime-artifact GC."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Sequence

from .runtime_artifact_retention import RUNTIME_ARTIFACT_TYPES

GC_PLAN_KIND = "lenskit.runtime_artifact_gc_plan"
GC_PLAN_VERSION = 1
GC_PROTECTION_KIND = "lenskit.runtime_artifact_gc_protection"
GC_PROTECTION_VERSION = 1

_REFERENCE_STATES = frozenset({"complete", "unknown"})
_EXTERNAL_REFERENCE_STATES = frozenset({"nonterminal", "terminal", "unknown"})


class RuntimeArtifactGCError(ValueError):
    """Fail-closed manual-GC planning or verification error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_aware_datetime(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise RuntimeArtifactGCError("invalid_timestamp", f"{label} must be an ISO-8601 string")
    candidate = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise RuntimeArtifactGCError("invalid_timestamp", f"{label} is not valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RuntimeArtifactGCError("invalid_timestamp", f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _string_list(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise RuntimeArtifactGCError("invalid_protection", f"{label} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise RuntimeArtifactGCError("invalid_protection", f"{label} contains duplicates")
    return sorted(value)


def _normalize_external_reference(raw: Any, *, index: int) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise RuntimeArtifactGCError(
            "invalid_protection", f"external_references[{index}] must be an object"
        )
    fields = {name: raw.get(name) for name in ("artifact_id", "kind", "state", "reference")}
    if not all(isinstance(item, str) and item for item in fields.values()):
        raise RuntimeArtifactGCError(
            "invalid_protection",
            f"external_references[{index}] fields must be non-empty strings",
        )
    state = fields["state"]
    if state not in _EXTERNAL_REFERENCE_STATES:
        raise RuntimeArtifactGCError(
            "invalid_protection", f"external_references[{index}].state is unsupported"
        )
    if state == "unknown":
        raise RuntimeArtifactGCError(
            "reference_state_unknown",
            f"external reference {fields['reference']!r} has unknown terminality",
        )
    return {name: str(value) for name, value in fields.items()}


def _normalize_external_references(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise RuntimeArtifactGCError("invalid_protection", "external_references must be a list")
    external = [_normalize_external_reference(raw, index=index) for index, raw in enumerate(value)]
    keys = [(item["artifact_id"], item["kind"], item["reference"]) for item in external]
    if len(keys) != len(set(keys)):
        raise RuntimeArtifactGCError("invalid_protection", "duplicate external reference")
    return sorted(external, key=lambda item: (item["artifact_id"], item["kind"], item["reference"]))


def normalize_protection(protection: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and canonicalise one complete protection-evidence document."""
    if not isinstance(protection, Mapping):
        raise RuntimeArtifactGCError("invalid_protection", "protection must be an object")
    if protection.get("schema_version") != GC_PROTECTION_VERSION:
        raise RuntimeArtifactGCError("invalid_protection", "unsupported protection schema_version")
    reference_state = protection.get("reference_state")
    if reference_state not in _REFERENCE_STATES:
        raise RuntimeArtifactGCError("invalid_protection", "reference_state must be complete or unknown")
    if reference_state != "complete":
        raise RuntimeArtifactGCError(
            "reference_state_unknown",
            "manual GC requires complete reference evidence; unknown state blocks planning/apply",
        )
    return {
        "schema_version": GC_PROTECTION_VERSION,
        "kind": GC_PROTECTION_KIND,
        "reference_state": "complete",
        "active_session_ids": _string_list(
            protection.get("active_session_ids", []), label="active_session_ids"
        ),
        "pinned_artifact_ids": _string_list(
            protection.get("pinned_artifact_ids", []), label="pinned_artifact_ids"
        ),
        "external_references": _normalize_external_references(
            protection.get("external_references", [])
        ),
    }


def entry_index(entries: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    index: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        artifact_id = entry.get("id") if isinstance(entry, Mapping) else None
        if not isinstance(artifact_id, str) or not artifact_id:
            raise RuntimeArtifactGCError("invalid_store_entry", "every artifact entry requires a non-empty id")
        if artifact_id in index:
            raise RuntimeArtifactGCError("duplicate_artifact_id", f"duplicate artifact id {artifact_id!r}")
        index[artifact_id] = entry
    return index


def _protect(reasons: Dict[str, set[str]], index: Mapping[str, Any], artifact_id: str, reason: str) -> None:
    if artifact_id in index:
        reasons.setdefault(artifact_id, set()).add(reason)


def _session_reference_ids(
    session_id: str,
    session: Mapping[str, Any],
    index: Mapping[str, Any],
) -> list[tuple[str, str]]:
    data = session.get("data")
    refs = data.get("artifact_refs") if isinstance(data, Mapping) else None
    if refs is None:
        refs = {}
    if not isinstance(refs, Mapping):
        raise RuntimeArtifactGCError(
            "active_session_reference_invalid",
            f"active session {session_id!r} artifact_refs is not an object",
        )
    resolved: list[tuple[str, str]] = []
    for field in ("query_trace_id", "context_bundle_id"):
        referenced = refs.get(field)
        if referenced is None:
            continue
        if not isinstance(referenced, str) or not referenced:
            raise RuntimeArtifactGCError(
                "active_session_reference_invalid",
                f"active session {session_id!r} has invalid {field}",
            )
        if referenced not in index:
            raise RuntimeArtifactGCError(
                "active_session_reference_missing",
                f"active session {session_id!r} references missing artifact {referenced!r}",
            )
        resolved.append((field, referenced))
    return resolved


def _protect_active_session(
    session_id: str,
    *,
    index: Mapping[str, Mapping[str, Any]],
    reasons: Dict[str, set[str]],
) -> None:
    session = index.get(session_id)
    if session is None:
        raise RuntimeArtifactGCError(
            "active_session_missing", f"active session artifact {session_id!r} is absent"
        )
    if session.get("artifact_type") != "agent_query_session":
        raise RuntimeArtifactGCError(
            "active_session_type_mismatch",
            f"active session {session_id!r} is not an agent_query_session",
        )
    _protect(reasons, index, session_id, "active_session")
    for field, referenced in _session_reference_ids(session_id, session, index):
        _protect(reasons, index, referenced, f"active_session_ref:{session_id}:{field}")


def protected_artifacts(
    entries: Sequence[Mapping[str, Any]], protection: Mapping[str, Any]
) -> tuple[Dict[str, list[str]], Dict[str, Any]]:
    """Return protected artifact IDs/reasons and canonical protection evidence."""
    canonical = normalize_protection(protection)
    index = entry_index(entries)
    reasons: Dict[str, set[str]] = {}
    for artifact_id in canonical["pinned_artifact_ids"]:
        _protect(reasons, index, artifact_id, "pin")
    for ref in canonical["external_references"]:
        if ref["state"] == "nonterminal":
            _protect(reasons, index, ref["artifact_id"], f"external:{ref['kind']}:{ref['reference']}")
    for session_id in canonical["active_session_ids"]:
        _protect_active_session(session_id, index=index, reasons=reasons)
    return (
        {artifact_id: sorted(values) for artifact_id, values in sorted(reasons.items())},
        canonical,
    )


def validated_budgets(budgets: Mapping[str, Any]) -> Dict[str, Dict[str, int]]:
    if not isinstance(budgets, Mapping) or set(budgets) != set(RUNTIME_ARTIFACT_TYPES):
        raise RuntimeArtifactGCError("invalid_budgets", "budgets must cover every runtime artifact type")
    result: Dict[str, Dict[str, int]] = {}
    expected = {"max_age_seconds", "max_count", "max_bytes"}
    for artifact_type in RUNTIME_ARTIFACT_TYPES:
        raw = budgets.get(artifact_type)
        if not isinstance(raw, Mapping) or set(raw) != expected:
            raise RuntimeArtifactGCError(
                "invalid_budgets", f"budget for {artifact_type} must contain {sorted(expected)}"
            )
        rendered: Dict[str, int] = {}
        for field in sorted(expected):
            value = raw.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise RuntimeArtifactGCError(
                    "invalid_budgets", f"{artifact_type}.{field} must be a positive integer"
                )
            rendered[field] = value
        result[artifact_type] = rendered
    return result
