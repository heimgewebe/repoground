"""Public manual runtime-artifact GC planning contract.

Validation/protection and deterministic budget planning are split into small
modules so the public surface stays stable without accumulating a monolithic
planner. This facade is effect-free; filesystem effects remain in
:mod:`runtime_artifact_gc_store`.
"""
from .runtime_artifact_gc_plan import build_retention_plan, verify_retention_plan
from .runtime_artifact_gc_support import (
    GC_PLAN_KIND,
    GC_PLAN_VERSION,
    GC_PROTECTION_KIND,
    GC_PROTECTION_VERSION,
    RuntimeArtifactGCError,
    canonical_json,
    normalize_protection,
    protected_artifacts,
    sha256_bytes,
    sha256_json,
)

__all__ = [
    "GC_PLAN_KIND",
    "GC_PLAN_VERSION",
    "GC_PROTECTION_KIND",
    "GC_PROTECTION_VERSION",
    "RuntimeArtifactGCError",
    "build_retention_plan",
    "canonical_json",
    "normalize_protection",
    "protected_artifacts",
    "sha256_bytes",
    "sha256_json",
    "verify_retention_plan",
]
