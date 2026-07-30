"""Shared Observed Call Overlay v1 (S2) limits and negative semantics.

S2 is *observed* evidence: one concrete execution of one concrete command was
watched and the calls it actually performed were recorded. It is a strictly
additive navigation overlay next to the static Python Call Graph v1 (S0/S1).

Two boundaries are load-bearing and are encoded as data here so that producer,
validator and navigation cannot drift apart:

``S2 never upgrades static evidence``
    An observed edge does not turn an S0 candidate into an S1 resolution and
    does not widen the static graph's completeness claim. The overlay is a
    separate artifact with its own record shape; it is never merged into the
    ``calls`` array of the static graph.

``Absence is not evidence``
    A call that was not observed may simply not have been exercised by this
    command, in this environment, at this revision. Absence from a trace
    therefore establishes neither dead code nor unreachable behaviour, and the
    overlay's ``does_not_establish`` list names both explicitly.
"""

OVERLAY_KIND = "lenskit.python_observed_call_overlay"
OVERLAY_VERSION = "1.0"

OBSERVED_EVIDENCE_LEVEL = "S2"
EVIDENCE_LEVELS = ("S2",)
RELATION_TYPES = ("observed_calls",)

#: Per-endpoint outcome of resolving a runtime code object against the static
#: Python Symbol Index. ``bound`` means exactly one definition contains the
#: observed code object; every other outcome stays unbound and keeps the raw
#: runtime coordinates instead of guessing a symbol.
BINDING_STATUSES = ("bound", "module_scope", "unbound")

BINDING_REASONS = (
    "unique_symbol_containment",
    "module_frame",
    "no_matching_symbol",
    "ambiguous_symbol_containment",
    "path_outside_repository",
)

#: Number of trace diagnostics retained verbatim in the artifact.
MAX_SKIPPED_ERRORS = 20

#: Number of distinct observed relations retained in one overlay.
MAX_RELATIONS = 20000

ABSENCE_SEMANTICS = (
    "absence of a relation from this overlay means the traced command did not "
    "exercise it in this environment at this source revision; it does not mean "
    "the relation is impossible, dead or unreachable"
)

REQUIRED_NONCLAIMS = (
    "complete_call_graph",
    "runtime_reachability",
    "dead_code",
    "unreachable_code",
    "static_resolution_upgrade",
    "dynamic_dispatch_resolution",
    "coverage_sufficiency",
    "test_sufficiency",
    "review_completeness",
    "merge_readiness",
)

#: The producer additionally denies claims that only an executing tracer could
#: be misread as making.
PRODUCER_NONCLAIMS = (
    *REQUIRED_NONCLAIMS,
    "deterministic_reproduction",
    "environment_equivalence",
)
