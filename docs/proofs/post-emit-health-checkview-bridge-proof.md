---
doc_type: proof
status: active
task: TASK-POST-EMIT-HEALTH-CHECKVIEW-BRIDGE-001
---

# Proof: Post-Emit Health CheckView Bridge

## Purpose

The remaining-consumer audit selected `post_emit_health` as the only plausible next narrow CheckView consumer. This path reads two validated `output_health` diagnostic signals to decide whether the `searchable` evidence level can be reported when a valid `sqlite_index` is present.

This slice migrates that read path to `compact_check_projection(report)` while preserving the existing mapping-shaped `output_health["checks"]` contract.

## Implementation

`merger/lenskit/core/post_emit_health.py` now imports `compact_check_projection` and uses it for `oh_doc` when, and only when, the original `checks` value is a mapping.

Preserved behavior:

- `output_health.verdict` remains observation-only;
- the post-emit status is not gated by output_health;
- `searchable` requires a valid `sqlite_index` plus positive SQLite/FTS output-health signals;
- `False`, `None`, missing key, and non-mapping `checks` do not overstate `searchable`;
- noise-hygiene fallback behavior remains unchanged because mapping values are preserved by the projection.

## Verification

`merger/lenskit/tests/test_post_emit_health.py` adds an explicit valid `sqlite_index` fixture and covers:

- both SQLite/FTS booleans true -> `searchable` is reached;
- `False` -> `searchable` is not reached;
- `None` -> `searchable` is not reached;
- missing key -> `searchable` is not reached;
- non-mapping list-shaped `checks` -> `searchable` is not reached.

Focused local test:

```text
python3 -m pytest -q merger/lenskit/tests/test_post_emit_health.py merger/lenskit/tests/test_validation_check_view.py
77 passed
```

## Negative semantics

This does not establish truth, repository understanding, answer safety, retrieval completeness, claim correctness, runtime correctness, test sufficiency, regression absence, or forensic readiness. It is only one producer-side diagnostic bridge migration.

## Non-goals

No producer normalization, no schema migration, no JSON-output migration, no bundle emission change, no parity-state migration, no merge.py invariant migration, no forensic-preflight migration, no smoke-script migration, and no broad adapter sweep.
