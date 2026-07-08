# Graph Degradation Semantics v1 proof

Task: `TASK-GRAPH-DEGRADATION-SEMANTICS-HARDENING-001` / Bureau `RPU-V1-T010`.

Status: shared diagnostic vocabulary and consumer wiring for stale, missing, invalid, validation-unavailable, degraded or unavailable graph evidence.

## Implemented surface

The shared vocabulary lives in:

```text
merger/lenskit/core/graph_degradation.py
```

It provides:

```text
graph_load_degradation(status, graph_used=...)
graph_availability_degradation(status, load_status=...)
graph_degradation_report(...)
graph_gap_from_availability(source, graph)
```

## Current consumers

The vocabulary is used by:

```text
merger/lenskit/core/repobrief_availability.py
merger/lenskit/retrieval/query_core.py
merger/lenskit/core/repobrief_context_compiler.py
merger/lenskit/core/repobrief_delta_context.py
```

## Decision

Only an `ok` loaded graph index / `available` graph availability is retrieval-eligible.

Every other graph state remains diagnostic and sets or implies:

```text
retrieval_eligible: false
graph_must_not_influence_retrieval: true
```

Covered degradation states include:

```text
missing
missing_source
missing_provenance
stale
profile_excluded
invalid
validation_unavailable
degraded
```

## Non-claim boundary

Graph degradation reports and gaps carry explicit non-claims. They do not establish:

```text
graph_completeness
dependency_completeness
runtime_reachability
runtime_causality
runtime_behavior
change_impact
impact_completeness
test_sufficiency
review_impact
retrieval_improvement
default_promotion_readiness
merge_readiness
```

## Consumer semantics

- `repobrief.graph_availability` now includes a `degradation` object for available, missing, stale, invalid and profile-excluded graph surfaces.
- Query explain diagnostics now include a `degradation` object with `graph_used_consistent_with_status`.
- Context compiler and delta-context compiler graph gaps use the same `graph_gap_from_availability(...)` projection.
- Query claim boundaries explicitly say graph diagnostics do not prove runtime reachability, causality, change impact, graph completeness or default-promotion readiness.

## Read-only / no-promotion boundary

This slice does not:

- build new graph evidence;
- change graph ranking weights;
- promote graph-conditioned ranking to default;
- turn graph diagnostics into a gate;
- prove runtime reachability, causality or impact.

## Validation scope

Tests cover:

- all non-`ok` load states are not retrieval-eligible;
- `ok` load state is the only graph-used state considered consistent;
- stale graph use is flagged inconsistent;
- availability degradation vocabulary for stale, missing, available and profile-excluded states;
- gap projection preserving negative semantics;
- graph availability model output for available, stale, missing, validation-unavailable and profile-excluded bundles;
- query explain output for stale graph diagnostics;
- query claim-boundary language.

Current local validation on the implementation branch:

```text
python3 -m json.tool docs/tasks/index.json
# ok

python3 -m scripts.docmeta.check_planning_registration \
  --ratchet \
  --baseline docs/tasks/planning-registration-baseline.json \
  --format json
# current findings: 0; new findings: 0; invalid exceptions: 0; control errors: 0

git diff --check
# ok

pytest -q \
  merger/lenskit/tests/test_graph_degradation_semantics.py \
  merger/lenskit/tests/test_repobrief_profiles.py \
  merger/lenskit/tests/test_retrieval_query.py \
  merger/lenskit/tests/test_repobrief_delta_context.py \
  merger/lenskit/tests/test_repobrief_context_compiler.py
# 69 passed

ruff check \
  merger/lenskit/core/graph_degradation.py \
  merger/lenskit/core/repobrief_availability.py \
  merger/lenskit/core/repobrief_context_compiler.py \
  merger/lenskit/core/repobrief_delta_context.py \
  merger/lenskit/retrieval/query_core.py \
  merger/lenskit/tests/test_graph_degradation_semantics.py \
  merger/lenskit/tests/test_repobrief_profiles.py \
  merger/lenskit/tests/test_retrieval_query.py
# All checks passed
```

## Non-claims

This proof does not establish:

```text
graph completeness
dependency completeness
runtime reachability
runtime causality
change impact completeness
test sufficiency
runtime behavior
review impact
retrieval improvement
default-promotion readiness
merge readiness
```
