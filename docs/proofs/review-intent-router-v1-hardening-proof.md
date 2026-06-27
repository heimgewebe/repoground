# Review-Intent Router v1 Hardening Proof

## Scope

This follow-up hardens the merged opt-in Review-Intent Router without promoting it to the default and without adding semantic retrieval, embeddings, graph composition, CLI integration, service integration, or bundle emission.

## Reproduced defects

The merged implementation was falsified with three deterministic fixtures:

1. A single file with more than 50 highly ranked chunks displaced other matching files before path deduplication. A request for ten paths returned one path despite additional matching paths in the index.
2. A fixed 200-candidate ceiling caused `k=250` to return only 200 paths despite 300 unique matching paths.
3. The audit accepted unrelated canonical and chunk-index files because it recorded hashes without verifying their relationship to the SQLite index, bundle manifest, or audited Git commit.

A fourth diagnostic defect was reproduced: a stopword-only review request fell back to the legacy query path while evaluation still declared review-intent ranking active.

## Implemented controls

- Candidate collection now expands deterministically until the requested unique-path pool is available or the matching result set is exhausted.
- The former fixed 200-chunk ceiling is removed.
- Explain output records collection attempts, final chunk window, exhaustion, and unique-path count for each lane variant.
- Non-executable review plans are explicitly marked `review_intent_fallback`; evaluation records requested, executed, fallback, and error query counts.
- The audit requires a bundle manifest and verifies required artifact roles, path containment, byte sizes, SHA-256 values, clean generator state, and generator commit equality with the clean audited repository HEAD.
- The audit reports expected-target recall globally and per category in addition to query Recall and MRR, and fails on target-total drift or per-category target-recall regression.

## Deterministic evidence

Regression tests cover:

- more than 50 leading chunks from one path;
- 300 unique matching paths with `k=250`;
- stopword-only fallback and truthful evaluation conditions;
- manifest hash mismatch;
- explicit artifact/manifest path mismatch;
- manifest generator commit mismatch;
- per-category MRR and expected-target-recall gates.

The pre-commit focused suite passed 89 retrieval, evaluation, graph, audit, schema, and compatibility tests. Ruff and `git diff --check` passed for the changed surface.

The regenerated clean snapshot is bound to bundle manifest SHA-256 `5a503d05a6dbd38ca5574659436b711dd41887e24cf80b828ec83b33908c19b5` and implementation commit `f1d34debaae6bbce0ce74803b2747ee41bfab931`. All nine gates pass. Query Recall is 100%, while expected-target recall is explicitly reported as 50% (30 of 60), preventing those two measurements from being conflated.

## Does not establish

- Retrieval results are relevant, correct, sufficient, or complete.
- Expected-target coverage is general retrieval quality.
- A missing result proves repository absence.
- Passing audit gates proves the repository was understood.
- Passing audit gates proves claims true, tests sufficient, runtime correct, or regressions absent.
- The opt-in mode is ready for default promotion.
- A commit-bound snapshot proves later live-repository state.

## Remaining boundary

Default promotion and CLI, service, bundle, manifest-consumer, facet-aware, relation-aware, symbol-aware, graph-aware, semantic, and embedding integrations remain outside this hardening slice.
