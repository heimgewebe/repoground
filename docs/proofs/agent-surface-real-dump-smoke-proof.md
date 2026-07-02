---
doc_type: proof
status: active
task: TASK-AGENT-SURFACE-REAL-DUMP-SMOKE-001
---

# Proof: Agent Surface Real Dump Smoke

## Purpose

This proof records a focused integration smoke for the agent-facing Lenskit bundle surfaces: Agent Entry Manifest, Agent Reading Pack, Export Safety Report, post-emit health and bundle surface validation.

The slice hardens the existing `test_asrs.py` smoke instead of adding a second near-duplicate test. Current `origin/main` already contains the Export Safety schema fields that the old scratch worktree had added.

## What is covered

The smoke verifies a standard minimal `write_reports_v2(..., output_mode="dual")` bundle path and checks:

- manifest roles for `canonical_md`, `agent_reading_pack`, `agent_entry_manifest`, and `output_health`;
- linked availability of `post_emit_health` and `bundle_surface_validation`;
- schema-valid Agent Entry Manifest output;
- Agent Entry surface roles for canonical, reading-pack, post-emit and surface-validation surfaces;
- Agent Entry `does_not_establish` keeps `repo_understood`;
- Agent Reading Pack sections for `AGENT_ENTRY_MANIFEST`, `EXPORT_SAFETY_REPORT`, and `WHAT_THIS_DOES_NOT_PROVE`;
- reading-pack guidance mentions `security_export_review`, `redaction_required`, and secret-absence non-claim semantics;
- `export-safety report --bundle-manifest ... --profile local-private --out ...` produces a schema-valid report;
- the report preserves kind, pass status, profile and `secret_absence` non-claim semantics;
- required-reading `security_export_review` fails without `export_safety_report` and passes when it is available.

## Verification

Focused local test:

```text
python3 -m pytest -q merger/lenskit/tests/test_asrs.py
```

## Negative semantics

This smoke does not establish repo understanding, answer correctness, review completeness, runtime correctness outside the covered producer path, secret absence, PII absence, public-share safety, forensic readiness, test sufficiency, regression absence or agent adoption.

## Non-goals

No producer change, no schema change, no bundle-manifest contract change and no new CLI behavior are introduced by this slice.
