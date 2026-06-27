# Review Retrieval Baseline

Status: metric baseline + miss diagnostics

## Scope

This baseline measures the review goldset against the existing lexical retrieval
evaluation and connects each expected target to the existing miss-diagnostics
taxonomy. It does not run, change, or improve retrieval, ranking, indexing, or
routing behavior. It is a diagnostic measuring instrument only.

## Measurement Hygiene: Goldset Self-Reference

The committed goldset is itself part of normal full-repository indexes. Its literal
query text can therefore appear as a high-ranked result and consume top-k capacity.
When the caller supplies `repo_root`, `run_review_retrieval_baseline` resolves the
goldset inside that root and excludes its exact repository-relative path before SQL
ordering and `LIMIT` are applied.

The exclusion is exact: similarly named paths remain candidates. Unsafe, absolute,
parent-traversing, backslash-ambiguous or out-of-root paths are rejected. Lenskit does
not infer a repository root from an arbitrary absolute goldset path; without an
explicit `repo_root`, legacy evaluation behavior remains unchanged.

The report records the excluded path with reason `goldset_self_reference`, exact-match
semantics, pre-limit application, and `ranking_algorithm_changed=false`. This is a
changed measurement condition, not a retrieval or ranking improvement.
It does not establish a ranking improvement. Exclusion does not establish that the
goldset is irrelevant, and changed metrics do not establish general retrieval quality.

The baseline reuses existing infrastructure rather than reimplementing it:

- Metrics (`recall@k`, `MRR`, `zero_hit_ratio`, per-category recall/MRR) come from
  `merger/lenskit/retrieval/eval_core.py` (`do_eval`).
- Per-expected-target miss classification reuses the eight diagnoses in
  `merger/lenskit/retrieval/eval_diagnostics.py`
  (`RetrievalEvalDiagnosticsCalibrator`). No second taxonomy is introduced.
- The review-goldset adapter lives in
  `merger/lenskit/retrieval/review_eval.py`.

## Goldset

- file: `docs/retrieval/review_queries.v1.json`
- format: a top-level list following `docs/retrieval/queries.v1.json`, with the
  loader-tolerated additive `category` field
- queries: 20
- required categories: `agent_pack`, `claim_evidence`, `citation_map`,
  `post_emit_health`, `bundle_surface`, `bundle_manifest`, `retrieval`, `router`,
  `cli`, `contracts`, `security`, `source_acquisition`, `pr_schau`, `range_ref`,
  `lenses`
- expected targets: repository-path patterns and symbol/text patterns

`review_eval.load_review_queries` normalizes the goldset into stable records with a
deterministic `query_id` (`RQ-01` … `RQ-20`), preserving categories and multiple
expected targets per query. Symbolic targets are kept as `symbol_or_text` and are
never reported as file errors.

## Metric Baseline

`build_review_retrieval_baseline` consumes `do_eval` output and emits a stable,
reproducible report. Retrieval metrics are taken verbatim from the eval output;
the adapter adds review-specific aggregation and per-target reporting only.

Top-level metric fields (`metrics`):

- `total_queries`
- `recall@10` (percent, as produced by `eval_core`)
- `MRR` (mean reciprocal rank of the first matching expected target)
- `zero_hit_ratio` (existing field name; ratio of queries returning no results)
- `expected_target_total`, `expected_target_hits`, `expected_target_misses`

## Category Metrics

`categories.<category>` aggregates each blueprint category separately
(`total_queries`, `hits`, `misses`, `recall@10`, `MRR`). The full review goldset
spans all 15 blueprint categories; results are not collapsed into a single
`uncategorized` bucket.

## Expected-Target Reporting

`queries[].expected_targets[]` reports each expected target of each query
separately:

- `target`, `target_kind` (`path` | `test_path` | `symbol_or_text` | `unknown`)
- `found` (whether the target landed in top-k)
- `rank` (1-indexed rank when found in top-k, else `null`)
- `matched_result` (the ranked result that matched, else `null`)
- `diagnosis` (taxonomy term, see below)

Each query also carries `query_id`, `query`, `category`, `top_k`, and
`query_had_zero_hits`.

## Miss Diagnostics

Every expected target is classified through the existing taxonomy
(`DiagnosticsRecord.PRIMARY_DIAGNOSES`): `target_in_top_k`,
`target_exists_not_in_top_k`, `target_missing_from_index`,
`target_missing_from_canonical`, `target_missing_from_citation_map`,
`stale_expected_target`, `query_target_ambiguous`, `diagnostic_inconclusive`.

`miss_taxonomy_summary` counts targets by diagnosis deterministically, and
`miss_diagnostics[]` carries the per-target diagnostic records for targets that
did not land in top-k. Diagnostic resolution improves when the calibrator is given
the chunk index, canonical_md, and citation_map artifacts; without them, misses are
reported as `diagnostic_inconclusive` or `query_target_ambiguous` rather than as
false absence claims.

## Reproduction

```python
from pathlib import Path
from merger.lenskit.retrieval.review_eval import run_review_retrieval_baseline

baseline = run_review_retrieval_baseline(
    index_path=Path("path/to/index.sqlite"),
    goldset_path=Path("docs/retrieval/review_queries.v1.json"),
    k=10,
    repo_root=Path("."),
    # Optional artifacts sharpen miss diagnostics:
    chunk_index_path=Path("path/to/chunks.jsonl"),
    canonical_path=Path("path/to/canonical.md"),
    citation_path=Path("path/to/citation_map.jsonl"),
)
```

`run_review_retrieval_baseline` is a thin library wrapper over the existing
`eval_core.do_eval` plus the diagnostics calibrator. It adds no new CLI, contract,
runtime behavior, or bundle artifact. Concrete metric values depend on the index
the baseline is run against and are therefore reproduced on demand rather than
pinned in this document.

## Tests

`merger/lenskit/tests/test_review_retrieval_metrics.py` proves loading and
normalization, that all 20 queries flow into the baseline, category aggregation,
`recall@10` / `MRR` / `zero_hit_ratio` reporting, per-target hit records (query id,
target, hit status, rank), separate handling of multiple expected targets per
query, reconciliation of misses with the existing taxonomy, deterministic
miss-taxonomy counts, and the inference boundaries below. The structural guard
remains `merger/lenskit/tests/test_review_retrieval_goldset.py`.

## Does not mean / Does not establish

- This baseline measures current lexical retrieval behavior for the review goldset.
- The report is diagnostic and does not establish review completeness.
- A hit does not prove answer correctness.
- A miss does not prove code absence.
- `recall@10` does not prove ranking sufficiency.
- Retrieval is not "good", "solved", or "sufficient" because of these numbers.
- Removing a self-reference from the measurement candidate set does not establish
  a ranking improvement.
- An excluded path is not established as irrelevant.

## Follow-up

Ranking improvements, semantic/embedding retrieval, and reranking remain separate
later slices. This document closes the metric-baseline and miss-diagnostics
subtask tracked by `TASK-AGENT-FRONTDOOR-004` and documents the in-progress
self-reference hygiene slice `TASK-RETRIEVAL-BASELINE-HYGIENE-001`; it does not
promote retrieval quality or change ranking behavior.
