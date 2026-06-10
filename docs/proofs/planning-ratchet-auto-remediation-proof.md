---
doc_type: proof
status: active
task: TASK-OPS-CTL-006
---

# Proof: Planning Ratchet Auto-Remediation / Baseline Pruning (TASK-OPS-CTL-006)

This proof documents the controlled baseline pruning behavior for the planning registration ratchet, designed to auto-remediate resolved baseline entries without opening the door to new drift.

## Problem

The original ratchet (TASK-OPS-CTL-005) tolerated known findings via a baseline but lacked a safe mechanism to prune entries once they were resolved (e.g. when an unregistered blueprint is finally registered). Without pruning, the baseline accumulates stale entries, degrading its usefulness as an accurate record of current legacy drift.

## Solution: Controlled Baseline Pruning

- `--prune-baseline --baseline PATH` compares the current scan with the loaded baseline and reports only `resolved_findings` as removable. By default, this is a dry-run.
- `--write` removes exactly those resolved ids, preserves active known entries, never adds `new_findings`, validates the serialized candidate against the contract schema, and replaces the baseline atomically (`os.replace`).
- Pruning fails closed with exit 2 and no baseline change for:
  - Unreadable or invalid baselines.
  - Control errors (e.g. missing/unparseable control files).
  - Invalid exceptions (e.g. expired exceptions).
  - Ambiguous resolved-id mapping.
  - Write failures (e.g. `OSError`).
  - A mutating write that would remove the last remaining baseline entry (`empty_baseline_write`). An already-empty baseline is a valid write no-op: it exits 0, removes nothing, and is not rewritten.
- New drift remains visible in the report but does not prevent removal of an independently resolved baseline entry; pruning is not an acceptance path for that drift.

## Diagnostics and Dry-Run Reporting

- The tool emits a `prune` block for every `prune_baseline` report containing `dry_run`, `write`, `removed_count`, removed ids, `blocked`, and explicit `block_reasons`.
- If a future write would be blocked (e.g., removing the last entry), the `prune` block also contains `write_would_block: true` and lists the reasons in `write_block_reasons`.
- Human-readable output exposes the same action, blocker state, and `Write would block` diagnostics, ensuring dry-runs provide early feedback about potential write failures.

## Consumer / Contract Compatibility Check

The v1 report contract uses an additive extension strategy:
- The `mode` enum adds `prune_baseline`.
- The schema includes a strict `allOf`/`if-then` block: `prune` is required and `enabled` must be `true` if `mode == "prune_baseline"`; otherwise, if `prune` is present, `enabled` must be `false`.
- This ensures legacy scan/ratchet/update_baseline reports without prune remain schema-valid in the tested in-repo compatibility scope.

To verify consumer compatibility, a focused in-repo search was performed:

```bash
grep -RIn \
  -e "planning_registration_report.v1" \
  -e "planning-registration-report.v1.schema.json" \
  -e "prune_baseline" \
  merger scripts docs .github

grep -RIn \
  -e "planning-registration-report.json" \
  merger scripts docs .github
```

The search found only the producer (`scripts/docmeta/check_planning_registration.py`), schema-validation tests, and planning documentation/task metadata. A separate search for the emitted report filename found the read-only workflow summary. No hard-coded incompatible consumer was identified in the reviewed in-repo search scope.

## Follow-up

- Optional PR-comment reporting remains deferred; it would require a separate, explicitly permissioned workflow design.
