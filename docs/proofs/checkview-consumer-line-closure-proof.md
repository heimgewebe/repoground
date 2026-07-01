---
doc_type: proof
status: active
task: TASK-CHECKVIEW-CONSUMER-LINE-CLOSURE-001
---

# Proof: CheckView Consumer Line Closure

## Purpose

The CheckView consumer line started as a compatibility adapter for heterogeneous `checks` surfaces. After the targeted migrations through PR #854, this proof closes the current migration line and records the remaining boundaries.

The goal is to stop treating every raw `checks` access as technical debt. Some raw access is now intentional because it belongs to stricter producer, comparison, forensic, or operational contracts.

## Current migrated consumers

| Path | Surface | Contract preserved |
|---|---|---|
| `merger/lenskit/cli/cmd_bundle_surface.py` | `bundle_surface_validation` human CLI output | human formatting only; JSON/report semantics unchanged |
| `merger/lenskit/core/export_safety_report.py` | `output_health` redaction observation | post_emit priority and top-level fallback preserved |
| `merger/lenskit/core/agent_reading_pack.py` | `output_health` health summary | mapping-shaped output_health contract preserved |
| `merger/lenskit/core/context_quality.py` | `output_health` diagnostic projection | mapping-shaped output_health contract preserved |
| `merger/lenskit/core/post_emit_health.py` | `output_health` SQLite/FTS bridge | searchable evidence remains strict; mapping-shaped output_health contract preserved |

## Boundary decisions

| Remaining path | Decision | Reason |
|---|---|---|
| `merger/lenskit/core/parity_state.py` | keep raw | strict `checks.get(key) is True` comparison semantics; migration would need a separate parity proof |
| `merger/lenskit/core/merge.py` | keep raw | emission-critical invariant filter over list-shaped bundle-surface checks; duplicate/fail behavior must stay explicit |
| `merger/lenskit/core/forensic_preflight.py` | keep separate | forensic gate surface, not an OH/BSV compatibility consumer |
| `scripts/rlens-post-merge-surface-smoke.sh` | keep raw | operator smoke gate with explicit shell failure messages; Python projection would be a separate script contract change |
| `merger/lenskit/adapters/diagnostics.py` | keep separate | adapter diagnostics use profile-specific check vocabulary |
| `merger/lenskit/cli/cmd_governance.py` | keep separate | governance report family, not bundle health/surface checks |
| card validators | keep separate | `lens_card_validate`, `pr_delta_card_validate`, and `relation_card_validate` expose their own validation-result contracts |

## Closure rule

No further automatic CheckView migration should be started from this line.

A future migration of any boundary path must open a new task/proof with its own equivalence tests. In particular:

- `parity_state` needs exact boolean-comparison parity tests;
- `merge.py` needs invariant fail-filter parity tests over list ordering, duplicates, and malformed entries;
- `forensic_preflight` needs a forensic-surface adapter decision;
- `rlens-post-merge-surface-smoke.sh` needs script-level operational parity tests.

## Why closure is better than continuing

The already-migrated paths are read-only diagnostic or human-facing consumers where a compact projection reduces shape coupling without changing producer contracts. The remaining paths are not equivalent: they either gate emission, compare bundles, certify forensic readiness, or fail operator runs with explicit messages. Continuing the same migration pattern would collapse distinct contracts under a shared name. That would be tidy in code and wrong in behavior.

## Negative semantics

This closure proof does not establish correctness of all remaining raw readers. It does not prove runtime correctness, test sufficiency, regression absence, repository understanding, claim truth, answer safety, forensic readiness, or completeness. It only establishes that the current CheckView consumer migration line should stop here.

## Decision

Close the CheckView consumer migration line after PR #854. Keep remaining raw readers intentional unless a future task proves a narrower migration is safe.
