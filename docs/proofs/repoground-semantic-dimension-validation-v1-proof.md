# RepoGround Semantic Dimension Validation v1 — Proof

Status: implemented and locally verified on branch `feat/semantic-dimension-validation-v1` from base commit `572e9d5dd818e57b5e4b8d3a43660eca525be3a6`.

## Problem

`embedding-policy.v1` defines `dimensions` as the vector size produced by the configured model. The query runtime previously loaded the field but did not compare it with the actual query or document embeddings. A misconfigured model could therefore participate in semantic reranking without satisfying its declared policy.

## Change

`merger/repoground/retrieval/query_core.py` now:

- rejects non-positive or non-integer runtime `dimensions` values;
- reads vector shapes without requiring NumPy;
- validates the query vector and document-vector batch before similarity calculation;
- records expected and observed dimensions plus `dimension_validation` in semantic diagnostics;
- preserves pre-semantic candidate scores and ordering when `fallback_behavior=ignore`;
- raises a bounded dimension-mismatch error when `fallback_behavior=fail`;
- checks that the document embedding count matches the candidate count;
- marks general semantic encoding fallbacks explicitly in query traces.

The implementation does not change lexical retrieval, graph scoring, model selection, provider support, similarity metrics or default semantic activation.

## Regression discovered

`test_eval_semantic_delta` declared 384 dimensions while its deterministic mock model emitted two-dimensional vectors. The fixture was corrected to declare 2; the production check was not weakened.

## Verification

Targeted new and adjacent cases:

```text
10 passed, 37 deselected
```

Full RepoGround Python suite:

```text
python3 -m pytest merger/repoground/tests -q

4355 passed, 2 skipped in 127.86s
```

Static and diff checks:

```text
python3 -m ruff check \
  merger/repoground/retrieval/query_core.py \
  merger/repoground/tests/test_retrieval_query.py \
  merger/repoground/tests/test_eval_semantic.py

All checks passed!

git diff --check

passed
```

Targeted cases cover:

- matching dimensions with successful semantic reranking diagnostics;
- query-dimension mismatch with pre-semantic fallback;
- query-dimension mismatch with strict failure;
- document-dimension mismatch with pre-semantic fallback;
- invalid direct policy dimensions, including booleans and non-integers;
- document embedding count mismatch with bounded fallback and trace marker.

## Boundaries

A passing dimension check proves shape compatibility only. It does not prove model identity, semantic quality, ranking improvement, retrieval completeness, claim truth or production readiness. The optional semantic dependency and model approval boundaries remain unchanged.
