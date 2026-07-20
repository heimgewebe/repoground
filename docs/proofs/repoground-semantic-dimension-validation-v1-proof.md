# RepoGround Semantic Dimension Validation v1 — Proof

Status: implemented and locally verified on branch `feat/semantic-dimension-validation-v1` from original base commit `572e9d5dd818e57b5e4b8d3a43660eca525be3a6`.

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
- normalizes `(1, dimensions)` query lists, tuples and array-like rows without requiring NumPy;
- preserves lists of array- or tensor-like document rows as real batches instead of collapsing them to one document;
- distinguishes zero-dimensional array scalars from one-dimensional vector rows;
- centralizes positive runtime-dimension validation at both the public query boundary and the private embedding boundary;
- uses `numpy.asarray` only inside the NumPy scoring path, avoiding unconditional array creation and redundant copies;
- uses the measured faster `map(operator.mul, ...)` form in the optional pure-Python cosine hot path;
- validates rectangular Python batches without allocating a second dimensions list and set;
- centralizes semantic validation states, trace states and fallback markers as module constants.

The implementation does not change lexical retrieval, graph scoring, model selection, provider support, similarity metrics or default semantic activation.

## Regressions discovered

1. `test_eval_semantic_delta` declared 384 dimensions while its deterministic mock model emitted two-dimensional vectors. The fixture was corrected to declare 2; the production check was not weakened.
2. A model returning a one-dimensional document vector for one candidate passed dimension validation but failed both the pure-Python and NumPy-style scoring assumptions. The vector is now normalized to a one-row batch before validation and scoring.
3. A `(1, dimensions)` tuple query was dimension-counted correctly but remained nested. Query normalization now returns the actual single vector.
4. A list of array- or tensor-like document rows was mistaken for one flat vector because the old discriminator recognized only nested lists and tuples. Row-shape detection now preserves the batch count and validates every row dimension.
5. Array scalar objects can expose `shape=()`. They are now treated as ordinary vector components rather than batch rows, avoiding a regression while broadening array-like support.

## Verification

Review-specific semantic cases:

```text
python3 -m pytest merger/repoground/tests/test_retrieval_query.py \
  -k "semantic or cosine_scores" -q

22 passed, 33 deselected in 0.28s
```

Complete retrieval-query module:

```text
55 passed in 0.61s
```

Policy, schema, evaluation, API, context and review consumers:

```text
102 passed in 2.61s
```

Full RepoGround Python suite before the main-branch reconciliation:

```text
python3 -m pytest merger/repoground/tests -q

4358 passed, 2 skipped in 123.37s
```

The branch was then merged without conflict with current main commit `9b4b643c448e018049d03ab1ec945af99018e2b1`. That main change touched only fleet-publisher symlink I/O and its tests. The complete suite was repeated with output persisted to a file rather than inferred from transient journal output:

```text
python3 -m pytest merger/repoground/tests -q

4361 passed, 2 skipped in 119.52s
```

Durable post-main test task:

```text
task_id: d2057f00694e49f59f677061
terminalization_sha256: 2b80d603448e404d599edb5ba51804b9fef892da423080465d9815637232a32d
lifecycle_receipt_sha256: 428699fdc383adea252beb3b81fa85545b2c6fc8f2aa6a68b050c22e318c6764
persisted_output_sha256: 4451f9c0d7549e18ea51ca8d8e8a75aaa0fe72164c8175c8699c27ec6edbf039
```

Second review follow-up on the same current-main base:

```text
python3 -m pytest merger/repoground/tests -q

4366 passed, 2 skipped in 120.27s
```

Durable second-review test task:

```text
task_id: 224e5839872a44a2853037d1
terminalization_sha256: c8598ec055b8be1477c4cf00dc80c9154add4642b93e768ae65cf53c364243c9
lifecycle_receipt_sha256: 423e90b92ebd197353b5b1a26a885f557fb9f72c76e1e4012f72f36ec592e077
persisted_output_sha256: 1cf9109d28ac9efb26c3a49d3156a99278f2adb98289b7098024fc62c9ef4d76
```

A local 384-component microbenchmark compared 20,000 dot products over five repeats. The best observed times were 0.294337 seconds for the generator expression and 0.114604 seconds for `sum(map(operator.mul, ...))`. This establishes a local hot-path improvement, not a universal production latency claim.

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
- query-only validation with a `(1, dimensions)` tuple and no document encoding;
- query-only dimension mismatch without document encoding;
- a query returned as a one-row list containing an array-like vector;
- a document batch returned as a list of array-like vectors;
- a one-dimensional array-like single-document vector in the pure-Python scorer;
- zero-dimensional array scalar components inside an ordinary vector.

## Review decisions

Accepted because they had direct correctness or measurable allocation value:

- single-candidate batch normalization;
- tuple/list query normalization;
- `numpy.asarray` instead of unconditional `numpy.array` copies;
- allocation-free rectangular-batch validation;
- explicit diagnostic constants;
- a separate result-scoring helper;
- a clearer document-count-mismatch test name and comment;
- explicit documentation that missing runtime `dimensions` is rejected;
- array-like row detection for query and document batches;
- zero-dimensional scalar discrimination;
- centralized positive-dimension validation;
- the locally measured faster `operator.mul` pure-Python hot path.

Not adopted in this pull request:

- a new public exception hierarchy, because the exceptions remain private implementation details and existing bounded runtime errors are contract-compatible;
- immutable retrieval result objects, because mutation is an established internal query-core pattern and changing it would expand the pull request beyond semantic validation;
- requiring or warning for NumPy above an arbitrary candidate threshold, because semantic dependencies remain optional and no benchmark establishes 500 as a defensible boundary;
- an enum for diagnostics, because internal string constants remove duplication without changing serialized contracts or adding conversion overhead;
- removal of defensive normalization in the scoring helpers, because those private helpers are directly tested and intentionally remain safe when called independently of `_validated_semantic_embeddings`;
- removal of the NumPy shape guards as "dead code", for the same standalone-helper reason;
- a real `sentence-transformers` model test in the default suite, because the dependency is optional, absent in the verification environment, and model acquisition would make the test network- and artifact-dependent;
- arbitrary 1536/3072/4096-dimension tests, because vector-size bookkeeping is dimension-agnostic and such cases do not exercise a distinct branch;
- a nested diagnostics-schema migration or new logging contract, because both would change serialized observability surfaces beyond this correctness slice.

## Boundaries

A passing dimension check proves shape compatibility only. It does not prove model identity, semantic quality, ranking improvement, retrieval completeness, claim truth or production readiness. The optional semantic dependency and model approval boundaries remain unchanged.
