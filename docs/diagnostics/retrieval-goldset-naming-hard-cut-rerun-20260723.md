# Retrieval Goldset Naming Hard-Cut Revalidation — Rerun

Status: lexical retrieval rerun complete, no recall regression observed

## Scope

This closes out audit finding `candidate-49b5e257c0aa81203efa2e0f`: revalidate the
canonical retrieval goldset after the RepoGround naming hard cut
(`docs/contracts/repoground-naming-hard-cut.v1.json`). It does not change
`eval_core`, query routing, ranking, or any default runtime behavior.

## What changed

Retired product names describing a *current* CLI/runtime surface were replaced
with the current name in the active goldset and adjacent docs:

- `docs/retrieval/review_queries.v1.json` (`RQ-11`, `RQ-12`): "Find the Lenskit
  query CLI command..." / "...Lenskit retrieval eval CLI command..." →
  "RepoGround query CLI command" / "RepoGround retrieval eval CLI command".
  The CLI's actual `prog` is `repoground` (`merger/repoground/cli/main.py`)
  with `query` and `eval` subcommands; it was never named `lenskit`.
- `docs/retrieval/workbench_usefulness_goldset.v1.json`: every question's
  `expected_paths` pointed at compatibility-alias modules removed by
  `5926118f` ("hard cut RepoGround compatibility aliases") —
  `repobrief_readonly_adapter.py`, `repobrief_access.py`,
  `repobrief_mcp_resources.py`, `repobrief_latest_complete.py`. None of these
  files exist any more; the real, current modules are `readonly_adapter.py`,
  `bundle_access.py`, `mcp_resources.py`, and `latest_complete.py`
  respectively (confirmed via `git log --follow`). `symbol_query`/
  `expected_symbols` for the adapter class were similarly corrected from
  `RepoBriefReadonlyAdapter` to the actual current class,
  `RepoGroundReadonlyAdapter`. Query prose describing "RepoBrief" as the
  live snapshot/adapter/MCP surface was corrected to "RepoGround" to match.
- `docs/retrieval/queries.md`, `docs/retrieval/semantic-reranking.md`: prose
  described the current system/CLI as `lenskit`; corrected to `RepoGround` /
  `repoground eval`.

`kind` fields that are versioned data ids (e.g.
`repobrief.workbench_usefulness_goldset`, `lenskit.graph_quality_goldset`,
`repolens.pr_schau.delta`) were intentionally left unchanged: they are exact,
actively-checked producer/consumer contract identifiers under the hard cut's
`versioned_data_contracts` policy, not aliases for a live command, class, or
file surface. `docs/retrieval/*.example.json` synthetic fixtures with
non-repository paths (e.g. `brief.md`, `src/app.py`) were left unchanged for
the same reason: they do not bind to real repository targets.

Guard-relation and graph-quality goldset `object`/`subject` paths that do
point at real repository files were spot-checked against the working tree;
all resolve. One `guard_relation_goldset.v1.json` case intentionally targets a
non-existent path (`merger/repoground/core/router.py`) as a negative control
for "same basename, wrong layer" — that absence is by design, not staleness.

## Regression coverage added

Three new tests fail closed if a retired product name (`lenskit`, `repobrief`,
`repolens`, `rlens`) re-enters an active query, expected path/symbol, or
retrieval doc, while exempting the `kind` versioned-data-id fields:

- `merger/repoground/tests/test_review_retrieval_goldset.py::test_goldsets_do_not_describe_retired_products_as_current_surface`
- `merger/repoground/tests/test_workbench_usefulness.py::test_repository_goldset_questions_do_not_describe_retired_products_as_current`
- `merger/repoground/tests/test_retrieval_docs_naming_hard_cut.py::test_active_retrieval_docs_do_not_describe_retired_products_as_current`

## Rerun method

`naming_audit.scan_repository` does not cover this class of drift: it scans
`.py`/`.sh`/`.js`/`.html` under `merger/repoground`, `repoground`, `scripts`,
`tests` for executable command/environment/storage aliases, not prose or JSON
goldset fields under `docs/`. The gap above was undetected until this audit.

To check whether the `review_queries.v1.json` wording fix (`RQ-11`, `RQ-12`)
changed measured lexical recall, a repo-local, whole-file self-hosted index
was built from this working tree (`docs/`, `merger/`, `scripts/`, `tests/`;
1,025 text files, one FTS chunk per file) using the existing
`index_db.build_index`, then evaluated with the existing
`review_eval.run_review_retrieval_baseline` against the full 20-query
`review_queries.v1.json`, once with the committed (post-fix) text and once
with the prior (`Lenskit`-worded) text from `HEAD`.

```text
                                   before   after
overall recall@10                  15.0     15.0
RQ-11 (query CLI command) hit      false    false
RQ-12 (retrieval eval CLI) hit     false    false
```

Both CLI-category queries miss their expected top-10 targets identically
before and after the wording fix, and the goldset-wide `recall@10` is
unchanged (`15.0` in both runs). The wording correction is therefore
naming-accuracy only; it does not move measured recall in either direction.

## Measurement boundary — what this rerun does and does not establish

- This is a repo-local, ad hoc, whole-file lexical index (one FTS chunk per
  file, no function-level chunking, no canonical bundle, no graph/semantic
  signal). It reuses the existing `index_db` and `review_eval` production
  code paths verbatim; it does not reuse the canonical bundle producer
  pipeline, so absolute recall numbers here are not comparable to
  bundle-based canonical measurements (e.g.
  `docs/diagnostics/repobrief-canonical-retrieval-measurement-20260711.json`).
- It establishes only that the naming fix in `review_queries.v1.json` is
  recall-neutral under lexical retrieval on this snapshot; it does not
  establish general retrieval quality, ranking sufficiency, review
  completeness, or default-promotion readiness for any mode.
- A miss for RQ-11/RQ-12 is not evidence that `cmd_query.py`/`cmd_eval.py`
  are unreachable in the canonical, function-level-chunked bundle index; it
  reflects the coarser granularity of this ad hoc rerun index only.
- No committed goldset, contract, or default runtime evaluation path was
  changed by this rerun; it is a one-off diagnostic artifact, not a new CI
  gate.
