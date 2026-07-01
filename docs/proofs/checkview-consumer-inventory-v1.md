---
doc_type: proof
status: active
task: TASK-CHECKVIEW-CONSUMER-INVENTORY-001
---

# Proof: CheckView Consumer Inventory v1

## Purpose

After `compact_check_projection(report)` and the first bundle-surface CLI consumer, the next decision must not be another blind migration. This inventory records which runtime paths still consume producer-specific `checks` shapes, which ones are good follow-up candidates, and which similarly named `checks` surfaces are deliberately out of scope.

The goal is consumer selection, not producer normalization.

## Scope

In scope:

- `output_health["checks"]`
- `post_emit_health["checks"]`
- `bundle_surface_validation["checks"]`
- consumers that can plausibly use `compact_check_projection(report)` or `CheckView`

Out of scope for this inventory:

- card-validator result checks (`lens_card_validate`, `pr_delta_card_validate`, `relation_card_validate`)
- `forensic_preflight` validator checks
- Atlas/profile/governance checks with their own schema or vocabulary
- tests that assert producer shape as contract
- changing JSON output, schemas, contracts, producer reports or exit-code semantics

## Method

Read-only text search on current `origin/main` after PR #847. Search was intentionally broad, then manually classified to avoid treating every variable named `checks` as the same surface. That distinction matters: same word, different contract. A wrench and a tuning fork are both metal; this does not make them interchangeable.

## Runtime consumer inventory

| Path | Surface | Current access | Classification | Recommendation |
|---|---|---|---|---|
| `merger/lenskit/cli/cmd_bundle_surface.py` | `bundle_surface_validation` | `compact_check_projection(report)` | already migrated, human output only | keep; this is the baseline example |
| `merger/lenskit/core/merge.py` | `bundle_surface_validation` | raw list filter for invariant failures | emission-critical gate | defer; do not migrate before an equivalence test for fail filtering |
| `merger/lenskit/core/post_emit_health.py` | `output_health` | guarded dict lookup for SQLite/FTS propagation | producer-side diagnostic bridge | candidate, but only with fixture proving identical propagated SQLite status |
| `merger/lenskit/core/agent_reading_pack.py` | `output_health` | guarded dict lookup for chunk/sqlite/FTS/range summary | read-only navigation summary | good next low-risk candidate |
| `merger/lenskit/core/context_quality.py` | `output_health` | guarded dict lookup for context quality signals | read-only diagnostic projection | good candidate after agent-reading-pack, broader signal surface |
| `merger/lenskit/core/export_safety_report.py` | `output_health` | guarded dict lookup for `redact_secrets_enabled` | narrow read-only policy signal | good smallest candidate; verify `False`, `True`, missing and bad-shape cases |
| `merger/lenskit/core/parity_state.py` | `output_health` | strict `checks.get(key) is True` helper | parity/comparison logic | defer; preserve exact boolean semantics explicitly before migration |
| `scripts/rlens-post-merge-surface-smoke.sh` | `output_health` | strict dict checks with operational failure messages | operator smoke gate | defer; operational script should stay explicit unless script-level parity is tested |

## Adjacent but not currently target surfaces

| Path family | Why not in the first migration wave |
|---|---|
| `merger/lenskit/core/forensic_preflight.py` | Its ordered checks are a forensic gate surface with stricter semantics. Treat separately. |
| `merger/lenskit/core/lens_card_validate.py`, `pr_delta_card_validate.py`, `relation_card_validate.py` | Card validators expose their own validation result contract; do not fold into OH/PEH/BSV CheckView without a separate adapter decision. |
| `merger/lenskit/cli/cmd_governance.py` | Governance command formats a different report family. Similar shape, different meaning. |
| `merger/lenskit/adapters/diagnostics.py` | Adapter diagnostics use profile-specific checks, not bundle health/surface checks. |
| tests under `merger/lenskit/tests/` | Contract tests intentionally assert raw producer shapes; most should remain raw. |

## Recommended next slice

Best next implementation: migrate `export_safety_report._redaction_enabled_from_output_health` to `compact_check_projection(report)`.

Why this is first:

- it reads exactly one scalar output-health signal;
- it is read-only;
- it has focused tests already nearby;
- failures are easy to reason about (`True`, `False`, absent, malformed shape);
- it avoids touching emission, bundle JSON, parity logic or operational smoke scripts.

Second candidate: `agent_reading_pack.summarize_health`, because it is also read-only but consumes more fields.

Do not start with `merge.py`, `parity_state.py`, or `rlens-post-merge-surface-smoke.sh`; they are more operationally load-bearing.

## Negative semantics

This inventory does not prove that any migration is correct. It does not establish truth, completeness, runtime behavior, test sufficiency, regression absence, repo understanding, or forensic readiness. It only narrows the next safe migration choice.

## Decision

Proceed with one narrow follow-up migration only: `export_safety_report` first. Reassess after tests and CI. No broad adapter sweep.
