---
doc_type: proof
status: active
task: TASK-CONTEXT-QUALITY-CHECKVIEW-HEALTH-001
---

# Proof: Context Quality CheckView Health Consumer

## Purpose

`context_quality` is a read-only diagnostic projection. After the export-safety and agent-reading-pack slices, it is the next output-health consumer selected by the CheckView consumer inventory.

This slice migrates the output-health `checks` read path inside `context_quality` to `compact_check_projection(report)` while preserving the mapping-shaped `output_health["checks"]` contract.

## Implementation

`merger/lenskit/core/context_quality.py` now imports `compact_check_projection` and uses it in `_project_output_health` when, and only when, the original `checks` value is a mapping.

Preserved behavior:

- output-health verdict is projected verbatim as an observation;
- mapping-shaped health checks still provide canonical/chunk hash flags, SQLite/FTS signals, range-ref status, and redaction flags;
- non-mapping `checks` shapes remain ignored and project as `None` fields;
- context-quality JSON schema, output shape, write behavior, and projection-status semantics are unchanged.

## Verification

`merger/lenskit/tests/test_context_quality.py` now pins full output-health field parity for the existing observation test and adds a malformed-shape regression test. The malformed-shape test prevents list-shaped check objects from being interpreted as scalar output-health signals.

Focused local test:

```text
python3 -m pytest -q merger/lenskit/tests/test_context_quality.py merger/lenskit/tests/test_validation_check_view.py
63 passed
```

## Negative semantics

This does not establish truth, repository understanding, answer safety, retrieval completeness, claim correctness, runtime correctness, test sufficiency, regression absence, or forensic readiness. It is only one read-only consumer migration.

## Non-goals

No producer normalization, no schema migration, no JSON-output migration, no bundle emission change, no parity-state migration, no smoke-script migration, and no broad adapter sweep.
