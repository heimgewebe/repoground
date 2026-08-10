# RepoGround vs grep/read v4 — measurement-contract proof

Scope: benchmark measurement semantics plus one hash-bound full-repository
readback. This proof does **not** claim that RepoGround is generally better than
bounded grep/read, and it does not change the product retrieval algorithm.

## Why v4 is required

The first fresh full-repository run of the v3 harness on 2026-08-10 exposed two
measurement contaminants that can materially change the comparison:

1. The grep/read baseline iterated query tokens in wording order and stopped as
   soon as `k` unique paths had been collected. A framing token such as `find`
   could therefore fill the whole result set before subject terms such as
   `agent`, `reading`, or `pack` were searched.
2. Goldsets, earlier benchmark reports, and earlier retrieval-promotion
   diagnostics remained eligible retrieval targets. Those artifacts can contain
   the benchmark questions or expected target names, so either side could learn
   from the measurement itself instead of repository implementation evidence.

These findings do not invalidate the v3 locator/evidence binding fixes. They do
invalidate using v3 full-repository totals as a fair product-preference result.
A changed comparator contract is therefore versioned explicitly as v4 rather
than silently redefining v3.

## v4 contract

The v3 evidence-safety rules remain in force:

- the canonical CLI default remains `docs/retrieval/review_queries.v1.json`;
- `review_queries.v2.json` remains opt-in and separates `expected_paths` from
  `expected_evidence`;
- legacy `expected_patterns` remains all-path for backward-compatible scoring;
- evidence is scored only from content visible in the compared condition and
  only when that payload belongs to an expected path;
- RepoGround compact-response accounting preserves content identity, range
  references, freshness, and fallback metadata.

v4 adds two symmetric fairness rules:

- grep/read evaluates every distinct non-framing query term before ranking. Paths
  are ordered deterministically by distinct matched query terms descending,
  matched query terms present in the repository path descending, then repository
  path lexicographically. The result therefore cannot depend on which generic
  prompt word happened to occur first in the sentence.
- both RepoGround and grep/read receive the same exact repository-path exclusion
  set for self-measurement artifacts. The exclusion set is derived from the
  selected question file plus these bounded patterns:
  `docs/retrieval/review_queries.v*.json`,
  `docs/proofs/repoground-vs-grep-read*`, and
  `docs/diagnostics/retrieval-v*-default-promotion-*`.

The report persists the resolved exclusions as repository-relative paths, along
with the benchmark script, index, question-set, and repository-tree hashes.

## Regression boundary

Regression coverage proves that a repository containing many files matching only
`find` cannot crowd out a file matching all meaningful subject terms. Separate
coverage proves that benchmark/goldset artifacts are excluded from both the
RepoGround and grep/read conditions.

## Fresh full-repository readback

The v4 harness was run against the healthy exact-current publication for
RepoGround `main` at `182b73f27b9e16141c2a2016a5db051dbb73010e`. The bound
SQLite index SHA-256 is
`495c5ddbacb6e6ea86160489e6d617a29fb3e603f6022ca49500a9f4b681e868`.

Canonical v1 report:

- report SHA-256:
  `d86338098533d594b7f7b9adda1eaf5e7835b44cf1be45d8f0ffbe53c7c7521a`;
- status: `inconclusive`;
- RepoGround missing expected targets: **35**; grep/read: **53**;
- false-confidence cases: **20** for both conditions;
- RepoGround aggregate compaction: **93.84%** reduction, all cases pass.

Opt-in v2 report:

- report SHA-256:
  `2ef3d054b07db549a88e29cecea5b4647899ac2962807393c13d93fb2b579302`;
- status: `fail` because of `quality_or_freshness_regression`;
- RepoGround missing expected targets: **29**; grep/read: **51**;
- false-confidence cases: **18** for both conditions;
- RepoGround aggregate compaction: **93.84%** reduction, all cases pass;
- the decisive local regression is category `agent_pack`: grep/read has zero
  missing targets and zero false-confidence cases, while RepoGround has one
  missing target and one false-confidence case.

The aggregate target advantage is therefore real in this bounded corpus but is
not sufficient for a RepoGround preference. The fail-closed category rule
correctly prevents better global totals from hiding a local regression.

## Decision boundary

Historical v2 and v3 reports remain diagnostic evidence for their exact harness
versions only. Under v4, payload compaction already clears its acceptance gate;
the next measured product bottleneck is retrieval target coverage, beginning with
the `agent_pack` regression. `context_compose` should not be prioritized from
this benchmark until retrieval reaches an evidence-safe category result.
