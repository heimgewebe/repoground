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
- marks general semantic encoding fallbacks explicitly in query traces;
- separates semantic conversion, validation, scoring and failure handling from `execute_query` so the repository maintainability ratchet remains satisfied;
- normalizes a one-dimensional document vector for exactly one candidate into a one-row batch before scoring;
- normalizes `(1, dimensions)` query lists and tuples without requiring NumPy;
- uses `numpy.asarray` only inside the NumPy scoring path, avoiding unconditional array creation and redundant copies;
- validates rectangular Python batches without allocating a second dimensions list and set;
- centralizes semantic validation states, trace states and fallback markers as module constants.

The implementation does not change lexical retrieval, graph scoring, model selection, provider support, similarity metrics or default semantic activation.

## Regressions discovered

1. `test_eval_semantic_delta` declared 384 dimensions while its deterministic mock model emitted two-dimensional vectors. The fixture was corrected to declare 2; the production check was not weakened.
2. A model returning a one-dimensional document vector for one candidate passed dimension validation but failed both the pure-Python and NumPy-style scoring assumptions. The vector is now normalized to a one-row batch before validation and scoring.
3. A `(1, dimensions)` tuple query was dimension-counted correctly but remained nested. Query normalization now returns the actual single vector.

## Verification

Review-specific semantic cases:

```text
python3 -m pytest merger/repoground/tests/test_retrieval_query.py \
  -k "semantic or cosine_scores_accepts or query_only_normalizes" -q

17 passed, 33 deselected in 0.30s
```

Complete retrieval-query module:

```text
50 passed in 0.62s
```

Policy, schema, evaluation, API, context and review consumers:

```text
102 passed in 2.61s
```

Full RepoGround Python suite:

```text
python3 -m pytest merger/repoground/tests -q

4358 passed, 2 skipped in 123.37s
```

Static, maintainability and diff checks:

```text
python3 -m ruff check \
  merger/repoground/retrieval/query_core.py \
  merger/repoground/tests/test_retrieval_query.py

All checks passed!

python3 scripts/ci/check_graph_maintainability.py --root . --format json

status: pass
new_count: 0
resolved_count: 2
findings: []

git diff --check

passed
```

Targeted cases cover:

- matching dimensions with successful semantic reranking diagnostics;
- query-dimension mismatch with pre-semantic fallback;
- query-dimension mismatch with strict failure;
- document-dimension mismatch with pre-semantic fallback;
- invalid direct policy dimensions, including booleans and non-integers;
- document embedding count mismatch with bounded fallback and trace marker;
- a single candidate whose model returns a one-dimensional document vector;
- pure-Python cosine scoring for a one-dimensional single-document input;
- query-only validation with a `(1, dimensions)` tuple and no document encoding.

## Review decisions

Accepted because they had direct correctness or measurable allocation value:

- single-candidate batch normalization;
- tuple/list query normalization;
- `numpy.asarray` instead of unconditional `numpy.array` copies;
- allocation-free rectangular-batch validation;
- explicit diagnostic constants;
- a separate result-scoring helper;
- a clearer document-count-mismatch test name and comment;
- explicit documentation that missing runtime `dimensions` is rejected.

Not adopted in this pull request:

- a new public exception hierarchy, because the exceptions remain private implementation details and existing bounded runtime errors are contract-compatible;
- immutable retrieval result objects, because mutation is an established internal query-core pattern and changing it would expand the pull request beyond semantic validation;
- requiring or warning for NumPy above an arbitrary candidate threshold, because semantic dependencies remain optional and no benchmark establishes 500 as a defensible boundary;
- an enum for diagnostics, because internal string constants remove duplication without changing serialized contracts or adding conversion overhead.

## Boundaries

A passing dimension check proves shape compatibility only. It does not prove model identity, semantic quality, ranking improvement, retrieval completeness, claim truth or production readiness. The optional semantic dependency and model approval boundaries remain unchanged.
