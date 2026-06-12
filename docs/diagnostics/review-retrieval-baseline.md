# Review Retrieval Baseline

Status: initial structural baseline

## Scope

This baseline covers review-oriented retrieval queries for Lenskit implementation,
tests, contracts, and documentation. It provides a versioned input set whose structure,
category coverage, and expected repository targets can be checked reproducibly before
retrieval behavior is changed.

## Goldset

- file: `docs/retrieval/review_queries.v1.json`
- format: a top-level list following `docs/retrieval/queries.v1.json`, with the
  loader-tolerated additive `category` field
- queries: 20
- minimum queries: 20
- required categories: `agent_pack`, `claim_evidence`, `citation_map`,
  `post_emit_health`, `bundle_surface`, `bundle_manifest`, `retrieval`, `router`,
  `cli`, `contracts`, `security`, `source_acquisition`, `pr_schau`, `range_ref`,
  `lenses`
- expected targets: repository-path patterns and symbol/text patterns; path-like
  targets must resolve to existing files/directories, and symbolic targets must occur
  in repository text outside the goldset and its guard test

The static guard is
`merger/lenskit/tests/test_review_retrieval_goldset.py`. It checks compatibility with
the existing query shape, minimum size, unique non-empty query text, complete category
coverage, expected-pattern presence, existence of path-like targets, and textual
presence of symbolic targets outside the goldset and its guard test.

## Does not mean

- Retrieval is globally good.
- Ranking is optimal.
- Semantic search is implemented.
- A hit proves correctness.
- A miss alone proves code absence.
- The goldset is complete.

## Baseline Type

Structural baseline only. This slice does not run or commit retrieval metrics and does
not change retrieval, routing, indexing, or ranking behavior. This document closes only
the structural-goldset subtask; it does not close the full blueprint acceptance criteria
for reproducible retrieval baseline metrics or miss diagnostics. Those remain tracked by
`TASK-AGENT-FRONTDOOR-004`.

## Follow-up

`TASK-AGENT-FRONTDOOR-004` remains open to connect this goldset to deterministic
`retrieval_eval` metrics, expected-target hit reporting, and miss diagnostics reconciled
with the existing taxonomy. Ranking improvements remain a separate later slice.
