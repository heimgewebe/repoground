# Retrieval v2 Default Promotion Decision Proof

Status: done
Task: `TASK-RETRIEVAL-V2-DEFAULT-PROMOTION-DECISION-001`
Run: `20260708T152502Z`

## Result

The current reproducible decision is: **keep Retrieval v2-style review-intent retrieval opt-in and do not promote it to the default path**.

The diagnostic promotion gate passed on the measured goldset, but the gate is intentionally non-promotional. Passing the diagnostic gate establishes that this measured candidate did not regress against the measured legacy baseline under the supplied reports. It does not authorize a default behavior change.

## Decision record

- Gate status: `passed`
- `promote_default`: `false`
- `decision.default_promotion_allowed`: `false`
- Decision reason: diagnostic gate only; promotion requires explicit later decision even when gates pass

## Measurement inputs

- Repository: `heimgewebe/lenskit`
- Repository commit: `43d97b2b7cd26d7cc1d5ce2cc53df8a4f2eb8912`
- Repository dirty: `false`
- Measured at: `2026-07-08T15:25:02Z`
- Dump stem: `/home/alex/repos/merges/repobrief-auto/heimgewebe__lenskit/main/20260708T152502Z/heimgewebe__lenskit__main-max-260708-1525`
- Canonical dump SHA-256: `5b788402acf624f100d9119095544ca1d07f461e38b3c798d7ba1b5756020011`
- Dump index SHA-256: `1bd7b3d4b56fe2b742026c5cb21396df0f3ff9434507d51745f4a36614c0f149`
- SQLite index SHA-256: `556c44ae4c2c7ca9fcbf533e95cc1cfb395ffc8ecfc350733cb301d6d98844c2`
- Graph index SHA-256: `d87983354fea89e1691149f13e293f2e0ec7ded01780c7fe67a97dccc358ce2c`
- Retrieval eval SHA-256: `307b9adc2c75cdae3eb543253e3b022c2ac421555376c7c9190170a5b01bb5d1`
- Bundle health SHA-256: `3691d0e757172825ea212c0a7684abe99438228d6c76bf603cabf589bd27498b`
- Surface validation SHA-256: `d6bf2a6dd8ea29fae57f3d9ca62327cba29e1da951aacd1107c21848e0125961`

The run uses the existing review-query goldset and current real RepoBrief dump artifacts for `heimgewebe/lenskit` at the recorded commit. Artifact hashes above bind the decision to the measured inputs.

## Produced evidence

| Role | Path | SHA-256 |
| --- | --- | --- |
| Legacy retrieval report | `docs/diagnostics/retrieval-v2-default-promotion-legacy-20260708T152502Z.json` | `18066240f57ede8c554dc4aaf44404e57e5afaa70fa58578b065c857e3996e4d` |
| Review-intent candidate report | `docs/diagnostics/retrieval-v2-default-promotion-review-intent-20260708T152502Z.json` | `9a8e08673e232d1625453971fbad519e64c2c1aae9b5c2f1646c940da865a749` |
| Graph health report | `docs/diagnostics/retrieval-v2-default-promotion-graph-health-20260708T152502Z.json` | `56aae7951507de9e3c86ae0e89d99c957b533a5ea78370062b31df337f6585ab` |
| Range/citation health report | `docs/diagnostics/retrieval-v2-default-promotion-range-health-20260708T152502Z.json` | `d7aaff87d62f9406aa40dce18f2d524b11a594f475ec7b8e9cd3d90968159076` |
| Promotion decision report | `docs/diagnostics/retrieval-v2-default-promotion-decision-20260708T152502Z.json` | `3af0571fc2822cf09e6d879aa3ea9d0956c07c478287105dde7927084b9955ea` |

## Aggregate metrics

| Metric | Legacy | Review-intent candidate | Decision relevance |
| --- | ---: | ---: | --- |
| `recall@10` | 10 | 95 | non-regression passed |
| `MRR` | 0.1 | 0.375119 | non-regression passed |
| Expected target hits | 2 / 60 | 27 / 60 | expected-target recall passed |
| Expected target misses | 58 | 33 | miss count decreased |
| Zero-hit ratio | 0.2 | 0 | no candidate zero-hit cases |

## Gate matrix

| Gate | Passed | Values |
| --- | --- | --- |
| `global_recall_non_regression` | true | legacy `10.0`, candidate `95.0` |
| `global_mrr_non_regression` | true | legacy `0.1`, candidate `0.3751190476190477` |
| `expected_target_recall_non_regression` | true | legacy `0.033333`, candidate `0.45` |
| `per_category_non_regression` | true | 15 categories, no regressions |
| `miss_count_non_regression` | true | legacy `58`, candidate `33` |
| `fallback_count_zero` | true | candidate fallback count `0` |
| `fresh_graph_if_supplied` | true | graph supplied `true` |
| `range_citation_health_ok_if_supplied` | true | range report supplied `true` |

## Category matrix

| Category | Legacy recall@10 | Candidate recall@10 | Legacy MRR | Candidate MRR | Passed |
| --- | ---: | ---: | ---: | ---: | --- |
| `agent_pack` | 50 | 100 | 0.5 | 0.625 | true |
| `bundle_manifest` | 100 | 100 | 1 | 1 | true |
| `bundle_surface` | 0 | 100 | 0 | 0.333333 | true |
| `citation_map` | 0 | 100 | 0 | 1 | true |
| `claim_evidence` | 0 | 100 | 0 | 0.333333 | true |
| `cli` | 0 | 100 | 0 | 0.375 | true |
| `contracts` | 0 | 50 | 0 | 0.25 | true |
| `lenses` | 0 | 100 | 0 | 0.142857 | true |
| `post_emit_health` | 0 | 100 | 0 | 0.1 | true |
| `pr_schau` | 0 | 100 | 0 | 0.5 | true |
| `range_ref` | 0 | 100 | 0 | 0.333333 | true |
| `retrieval` | 0 | 100 | 0 | 0.208333 | true |
| `router` | 0 | 100 | 0 | 0.25 | true |
| `security` | 0 | 100 | 0 | 0.225 | true |
| `source_acquisition` | 0 | 100 | 0 | 0.142857 | true |

## Graph and range health

Graph health is supplied and fresh for this run:

- Graph report status: `fresh`
- Graph load status: `ok`
- Entrypoints: `48`
- Reachable nodes: `385`
- Unreachable nodes: `303`

Range/citation health is supplied and passed:

- Range/citation report status: `pass`

These reports only bind the diagnostic inputs used by this decision. They do not prove graph completeness, runtime causality, citation semantics, or answer correctness.

## Explicit decision

Default promotion remains **false** for this slice.

Reasoning:

1. The measured review-intent candidate improves the recorded aggregate and expected-target metrics against the recorded legacy baseline.
2. No category regression is recorded in the supplied gate matrix.
3. The candidate fallback count is zero.
4. Current graph and range/citation health reports are supplied and pass their diagnostic checks.
5. The existing gate is explicitly diagnostic-only, so a passing result is not itself a runtime default-promotion authorization.

Therefore this task records the current promotion decision as **keep false** rather than `promote`.

## Validation

The decision report contains two layers:

1. the diagnostic gate result produced by the existing promotion gate surface;
2. measurement metadata and artifact hashes that bind this decision to the real dump and produced reports.

Gate surface:

```text
scripts/proofs/retrieval_promotion_gate.py
merger/lenskit/retrieval/retrieval_promotion_gate.py
```

Validation expectations for this slice:

- all committed JSON reports pass `python3 -m json.tool`;
- the diagnostic gate core reproduced from the legacy, review-intent, graph and range reports matches the committed decision after excluding the wrapper-only `measurement_metadata` and `produced_reports` fields;
- `merger/lenskit/tests/test_retrieval_promotion_gate.py` remains the behavioral regression surface for the diagnostic gate;
- the planning registration ratchet reports zero new findings.

## Non-claims

This proof does not establish:

- retrieval correctness
- review completeness
- answer correctness
- runtime behavior
- default-promotion readiness beyond this measured goldset
- agent quality improvement by itself
- graph completeness or runtime causality
- citation semantic correctness
