---
doc_type: proof
status: active
task: TASK-AGENT-READING-PACK-CHECKVIEW-HEALTH-001
---

# Proof: Agent Reading Pack CheckView Health Consumer

## Purpose

The CheckView consumer inventory identified `agent_reading_pack.summarize_health` as the next read-only consumer after the export-safety slice. This function summarizes selected `output_health` fields for the Agent Reading Pack.

This slice moves that read path to `compact_check_projection(report)` while preserving the `output_health["checks"]` mapping contract.

## Implementation

`merger/lenskit/core/agent_reading_pack.py` now imports `compact_check_projection` and uses it in `summarize_health` when, and only when, the original `checks` surface is mapping-shaped.

Preserved behavior:

- `output_health` mapping checks still provide `chunk_count`, `sqlite_row_count`, `fts_content_non_empty`, and `range_ref_resolution_status`;
- verdict, error count, and warning count are unchanged;
- non-mapping `checks` shapes remain ignored instead of being interpreted as scalar health fields;
- Agent Reading Pack rendering and artifact emission are unchanged.

## Verification

`merger/lenskit/tests/test_agent_reading_pack.py` now pins full field parity for `summarize_health` and adds a malformed-shape regression test. The malformed-shape test prevents list-shaped check objects from being treated as scalar health values.

Focused local test:

```text
python3 -m pytest -q merger/lenskit/tests/test_agent_reading_pack.py merger/lenskit/tests/test_validation_check_view.py
85 passed
```

## Negative semantics

This does not establish truth, completeness, runtime behavior, test sufficiency, regression absence, repo understanding, claim correctness, answer safety, or forensic readiness. It is only one read-only consumer migration.

## Non-goals

No producer normalization, no schema migration, no JSON output migration, no bundle emission change, no `context_quality` migration, no parity-state migration, no smoke-script migration, and no broad adapter sweep.
