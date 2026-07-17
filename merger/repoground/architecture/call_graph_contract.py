"""Shared Python Call Graph v1 limits and negative semantics.

``transitive_import_resolution`` means the static producer does not follow
multi-hop imports, package re-exports, star-export expansion, module
``__getattr__`` hooks, or other runtime import indirection. A unique local
resolution therefore never implies that those transitive paths were searched.
"""

MAX_SKIPPED_ERRORS = 20

REQUIRED_NONCLAIMS = (
    "complete_call_graph",
    "runtime_reachability",
    "dynamic_dispatch_resolution",
    "dependency_completeness",
    "import_success",
    "test_sufficiency",
    "review_completeness",
    "merge_readiness",
)

PRODUCER_NONCLAIMS = (
    *REQUIRED_NONCLAIMS[:4],
    "transitive_import_resolution",
    *REQUIRED_NONCLAIMS[4:],
)
