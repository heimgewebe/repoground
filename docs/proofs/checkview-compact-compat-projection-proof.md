---
doc_type: proof
status: active
task: TASK-CHECKVIEW-COMPACT-COMPAT-PROJECTION-001
---

# Proof: CheckView Compact Compatibility Projection

## Purpose

`output_health`, `post_emit_health`, and `bundle_surface_validation` expose `checks` in different producer shapes. `CheckView` already provides an iterable read-only view. This slice adds one smaller by-name projection for consumers that need lookup compatibility without adopting every producer shape directly.

## Implementation

Added `compact_check_projection(report)` in `merger/lenskit/core/check_view.py`.

The function is deliberately consumer-side only:

- it does not change producer output;
- it does not change schemas or contracts;
- it does not add CLI or bundle artifacts;
- it does not migrate existing consumers.

Projection behavior:

- mapping-shaped checks keep their emitted value, deep-copied;
- list-shaped checks are projected to compact dictionaries containing `status`, `detail`, and `validation` when present;
- duplicate list names deterministically keep the last emitted entry, matching `checks_by_name`;
- malformed or absent `checks` surfaces project to `{}`.

## Negative semantics

This projection does not establish truth, correctness, completeness, runtime behavior, test sufficiency, regression absence, repo understanding, or forensic readiness. It only reduces consumer friction around shape differences.

## Verification

Regression coverage was added to `merger/lenskit/tests/test_validation_check_view.py` for:

- mapping-value preservation and copy isolation;
- list-shape compaction by name;
- `reason` fallback via `CheckView`;
- validation copy isolation;
- duplicate-name last-wins behavior;
- defensive bad-shape handling.

Focused test:

```text
python3 -m pytest -q merger/lenskit/tests/test_validation_check_view.py
29 passed
```

## Non-goals

No broader consumer adapter, no mirror of full list-shaped raw check records, no producer normalization, no schema migration, and no default promotion of this helper into existing runtime consumers.
