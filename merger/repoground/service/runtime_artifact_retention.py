"""Machine-readable retention policy for query runtime artifacts.

Per-artifact lookup metadata remains deliberately TTL-free and unbounded: no
artifact expires merely because time passes and lookup never deletes. T018
adds a separate *manual* plan/apply GC policy with conservative storage
budgets. The manual policy has no scheduler and no automatic effect.
"""
from __future__ import annotations

import copy
from typing import Any, Dict

RETENTION_POLICY_KIND = "lenskit.runtime_artifact_retention_policy"
RETENTION_POLICY_VERSION = "v1"
RETENTION_POLICY_ID = "runtime-artifact-retention.v1"
MANUAL_GC_POLICY_ID = "runtime-artifact-manual-gc.v1"
MANUAL_GC_DEFAULT_PROFILE = "conservative"

RUNTIME_ARTIFACT_TYPES: tuple[str, ...] = (
    "query_trace",
    "context_bundle",
    "agent_query_session",
)

RETENTION_STATE_UNBOUNDED = "unbounded_currently"
LIFECYCLE_STATUS_ACTIVE = "active"

# These are soft planning budgets, not TTLs. Crossing one or more limits only
# makes an unprotected artifact a candidate in an explicit dry-run plan.
# No automatic process consumes these values.
_MANUAL_GC_PROFILES: Dict[str, Dict[str, Dict[str, int]]] = {
    "conservative": {
        "query_trace": {
            "max_age_seconds": 90 * 24 * 60 * 60,
            "max_count": 25_000,
            "max_bytes": 512 * 1024 * 1024,
        },
        "context_bundle": {
            "max_age_seconds": 90 * 24 * 60 * 60,
            "max_count": 10_000,
            "max_bytes": 2 * 1024 * 1024 * 1024,
        },
        "agent_query_session": {
            "max_age_seconds": 180 * 24 * 60 * 60,
            "max_count": 25_000,
            "max_bytes": 512 * 1024 * 1024,
        },
    }
}

DOES_NOT_ESTABLISH: tuple[str, ...] = (
    "ttl_is_active",
    "gc_is_active",
    "automatic_deletion",
    "storage_bound",
    "artifact_freshness",
    "migration_completed",
    "operator_cleanup_safe",
)

_POLICY_BY_ARTIFACT_TYPE: Dict[str, Dict[str, Any]] = {
    "query_trace": {
        "authority": "runtime_observation",
        "canonicality": "observation",
        "artifact_shape": "raw",
        "retention_policy": RETENTION_STATE_UNBOUNDED,
        "lifecycle_status": LIFECYCLE_STATUS_ACTIVE,
        "expires_at": None,
        "ttl_enabled": False,
        "ttl_seconds": None,
        "gc_enabled": False,
        "gc_mode": "not_implemented",
        "deletion_mode": "not_supported_by_policy",
        "claim_boundaries": {
            "does_not_prove": [
                "Artifact ID stability is limited to this store location.",
                "Runtime artifact does not prove live repository state.",
            ]
        },
    },
    "context_bundle": {
        "authority": "runtime_observation",
        "canonicality": "observation",
        "artifact_shape": "projected",
        "retention_policy": RETENTION_STATE_UNBOUNDED,
        "lifecycle_status": LIFECYCLE_STATUS_ACTIVE,
        "expires_at": None,
        "ttl_enabled": False,
        "ttl_seconds": None,
        "gc_enabled": False,
        "gc_mode": "not_implemented",
        "deletion_mode": "not_supported_by_policy",
        "claim_boundaries": {
            "does_not_prove": [
                "Artifact ID stability is limited to this store location.",
                "Runtime artifact does not prove live repository state.",
                "Context bundle is stored in projected API form, not raw execute_query form.",
            ]
        },
    },
    "agent_query_session": {
        "authority": "runtime_observation",
        "canonicality": "observation",
        "artifact_shape": "wrapper",
        "retention_policy": RETENTION_STATE_UNBOUNDED,
        "lifecycle_status": LIFECYCLE_STATUS_ACTIVE,
        "expires_at": None,
        "ttl_enabled": False,
        "ttl_seconds": None,
        "gc_enabled": False,
        "gc_mode": "not_implemented",
        "deletion_mode": "not_supported_by_policy",
        "claim_boundaries": {
            "does_not_prove": [
                "Artifact ID stability is limited to this store location.",
                "Runtime artifact does not prove live repository state.",
            ]
        },
    },
}


def runtime_artifact_metadata_table() -> Dict[str, Dict[str, Any]]:
    """Return per-artifact runtime metadata copied from the retention policy."""
    return copy.deepcopy(_POLICY_BY_ARTIFACT_TYPE)


def runtime_artifact_metadata_for(artifact_type: str) -> Dict[str, Any]:
    """Return metadata for one artifact type or raise ValueError if unknown."""
    try:
        return copy.deepcopy(_POLICY_BY_ARTIFACT_TYPE[artifact_type])
    except KeyError as exc:
        raise ValueError(f"unknown runtime artifact type: {artifact_type!r}") from exc


def runtime_artifact_gc_profile(
    profile_id: str = MANUAL_GC_DEFAULT_PROFILE,
) -> Dict[str, Dict[str, int]]:
    """Return one named manual-GC budget profile as an independent copy."""
    try:
        return copy.deepcopy(_MANUAL_GC_PROFILES[profile_id])
    except KeyError as exc:
        raise ValueError(f"unknown runtime artifact GC profile: {profile_id!r}") from exc


def runtime_artifact_retention_policy() -> Dict[str, Any]:
    """Return the machine-readable retention and manual-GC policy.

    The established lookup policy remains unchanged: TTL/automatic GC/deletion
    are deferred. T018 adds a separate manual operator path that requires a
    deterministic dry-run and an exact plan-hash-bound apply with fresh
    protection evidence.
    """
    return {
        "kind": RETENTION_POLICY_KIND,
        "version": RETENTION_POLICY_VERSION,
        "policy_id": RETENTION_POLICY_ID,
        "status": "explicitly_deferred",
        "applies_to": list(RUNTIME_ARTIFACT_TYPES),
        "default_retention_policy": RETENTION_STATE_UNBOUNDED,
        "ttl": {
            "enabled": False,
            "default_ttl_seconds": None,
            "rationale": "No TTL is active for query runtime artifacts in this version.",
        },
        "gc": {
            "enabled": False,
            "mode": "not_implemented",
            "automatic_delete": False,
            "requires_explicit_future_policy": True,
            "rationale": "No automatic GC entrypoint is enabled by this policy slice.",
        },
        "manual_gc": {
            "policy_id": MANUAL_GC_POLICY_ID,
            "enabled": True,
            "mode": "explicit_plan_hash_bound_apply",
            "automatic_delete": False,
            "default_profile": MANUAL_GC_DEFAULT_PROFILE,
            "profiles": copy.deepcopy(_MANUAL_GC_PROFILES),
            "reference_state_required": "complete",
            "unknown_reference_state_blocks": True,
            "apply_requires_fresh_protection": True,
            "receipts_required": True,
            "rationale": (
                "Budgets create reviewable candidates only; active sessions, pins and "
                "nonterminal external evidence remain protected."
            ),
        },
        "no_surprise_delete": {
            "existing_artifacts_deleted_by_this_policy": False,
            "store_write_path_deletes_existing_entries": False,
            "lookup_deletes_expired_entries": False,
        },
        "backward_compatibility": {
            "legacy_entries_backfilled_on_read": True,
            "legacy_entries_rewritten_on_read": False,
            "migration_required": False,
        },
        "artifact_types": runtime_artifact_metadata_table(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
