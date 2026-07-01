---
doc_type: proof
status: active
task: TASK-CHECKVIEW-REMAINING-CONSUMER-AUDIT-001
---

# Proof: CheckView Remaining Consumer Audit v1

## Purpose

After PRs #847, #849, #850, and #852, CheckView is no longer only a helper: it is used by selected read-only consumers. This audit re-runs the consumer inventory on current `origin/main` after PR #851 and classifies the remaining raw `checks` readers.

The goal is to prevent autopilot migration. Same field name does not mean same contract.

## Current migrated consumers

| Path | Surface | Status |
|---|---|---|
| `merger/lenskit/cli/cmd_bundle_surface.py` | `bundle_surface_validation` human output | migrated via `compact_check_projection(report)` |
| `merger/lenskit/core/export_safety_report.py` | `output_health` redaction signal | migrated with fallback preserved |
| `merger/lenskit/core/agent_reading_pack.py` | `output_health` health summary | migrated with mapping-shape guard |
| `merger/lenskit/core/context_quality.py` | `output_health` diagnostic projection | migrated with mapping-shape guard |

## Remaining runtime readers

| Path | Surface | Current role | Classification | Recommendation |
|---|---|---|---|---|
| `merger/lenskit/core/post_emit_health.py` | `output_health` | reads SQLite row-count and FTS signals to propagate diagnostic status | producer-side diagnostic bridge | plausible next code slice, but only with equivalence tests for `None`, `False`, `True`, missing and non-mapping shapes |
| `merger/lenskit/core/parity_state.py` | `output_health` | strict boolean helper for parity comparison | comparison semantics | defer; preserve exact `is True` and mapping-shape semantics before any migration |
| `scripts/rlens-post-merge-surface-smoke.sh` | `output_health` | operational smoke gate for noise-hygiene diagnostics | operator guard | keep raw for now; do not route shell smoke logic through Python projection without script-level parity tests |
| `merger/lenskit/core/merge.py` | `bundle_surface_validation` | emission-critical invariant fail filter | bundle emission gate | defer; a projection migration would need fail-filter equivalence on duplicate and malformed list entries |
| `merger/lenskit/core/forensic_preflight.py` | `post_emit_health` / forensic checks | forensic gate surface | separate contract | do not migrate in the OH/BSV consumer line; treat as forensic adapter decision |

## Remaining adjacent namespaces

These are intentionally not migration targets for the OH/PEH/BSV CheckView line:

- `merger/lenskit/adapters/diagnostics.py`
- `merger/lenskit/cli/cmd_governance.py`
- `merger/lenskit/core/lens_card_validate.py`
- `merger/lenskit/core/pr_delta_card_validate.py`
- `merger/lenskit/core/relation_card_validate.py`
- tests that pin raw producer contracts such as `test_output_health.py`, `test_post_emit_health.py`, `test_bundle_surface_validate.py`, and `test_validation_check_shapes.py`

## Recommended next slice

Best next implementation, if continuing the CheckView consumer line:

`post_emit_health` output-health bridge.

Why:

- it reads only two output-health signals: `sqlite_row_count_matches_chunk_count` and `fts_content_non_empty`;
- it is narrower than `parity_state` and less operational than the smoke script;
- it already guards for mapping-shaped `output_health["checks"]`;
- an equivalence fixture can cover the full local state space.

Do not start with `parity_state`. Its `checks.get(key) is True` helper is deliberately strict and comparison-oriented. That strictness may be more important than reducing raw access.

## Acceptance criteria for the next code slice

A future `post_emit_health` migration must prove:

1. mapping with both booleans true still propagates positive SQLite status;
2. `False`, `None`, missing key, and non-mapping `checks` preserve existing degraded/unknown behavior;
3. output report shape and statuses remain unchanged;
4. no producer or schema contract is normalized.

## Negative semantics

This audit does not prove any future migration correct. It does not establish runtime correctness, test sufficiency, regression absence, repository understanding, claim truth, answer safety, forensic readiness, or completeness. It only narrows the remaining consumer decision surface.

## Decision

Proceed next, if at all, with a narrow `post_emit_health` bridge migration. Keep `parity_state`, `merge.py`, forensic preflight, and smoke scripts out of the next automatic migration wave.
