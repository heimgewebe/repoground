"""Machine-readable retention policy for query runtime artifacts.

This module is deliberately policy-only. It does not delete artifacts, schedule
GC, mutate stores, or assign TTLs. The current explicit policy is
``unbounded_currently`` for all query runtime artifacts.
"""
from __future__ import annotations

import copy
from typing import Any, Dict

RETENTION_POLICY_KIND = "lenskit.runtime_artifact_retention_policy"
RETENTION_POLICY_VERSION = "v1"
RETENTION_POLICY_ID = "runtime-artifact-retention.v1"

RUNTIME_ARTIFACT_TYPES: tuple[str, ...] = (
    "query_trace",
    "context_bundle",
    "agent_query_session",
)

RETENTION_STATE_UNBOUNDED = "unbounded_currently"
LIFECYCLE_STATUS_ACTIVE = "active"

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


def runtime_artifact_retention_policy() -> Dict[str, Any]:
    """Return the current machine-readable retention policy.

    The policy explicitly defers TTL/GC/deletion behaviour. It is a diagnostic
    and contract surface, not a cleanup engine.
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
            "rationale": "No automatic or manual GC entrypoint is implemented by this policy slice.",
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
