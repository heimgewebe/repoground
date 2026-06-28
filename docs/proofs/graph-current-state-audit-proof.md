# Graph Current-State Audit Proof

## Scope

This slice documents the implemented Architecture Graph surface on the pinned
base commit `6f3e4e01` and records the next safe implementation order. It changes
no graph producer, contract, query score, evaluation mode, bundle role, service
endpoint, or default.

## Evidence used

The audit checks the live source for:

- Graph, Entrypoints, and Graph Index contracts;
- producer and compiler call sites;
- CLI provenance placeholders;
- conditional derived-artifact and bundle-manifest registration;
- SQLite-bound staleness detection;
- graph-aware query, eval, and service wiring;
- current Graph Runtime Contract semantics;
- focused graph tests.

A fixed-input probe generated the graph in a detached clean worktree at commit
`6f3e4e01` and recorded files parsed, nodes, edges, entrypoints, evidence levels,
layer coverage, and reachability. Those values are commit-pinned diagnostic
observations, not PR-head metrics or CI thresholds.

## Guard

`merger/lenskit/tests/test_graph_current_state_audit.py` ties the narrative to
selected source call surfaces, the stale-graph condition, CLI provenance
placeholders, priorities, and negative semantics. It checks that the pinned
measurement and its provenance remain declared; it does not regenerate the
historical measurement or prove that those values still describe a later head.

The focused graph and audit suite passed 22 tests. Ruff and `git diff --check`
passed.

## Main finding

The highest-priority gap is detected-but-used stale graph data.
`load_graph_index()` identifies `stale_or_mismatched`, but
`query_core.execute_query()` currently treats that status as usable for graph
ranking. The follow-up must preserve the diagnostic status while reverting
scoring to the lexical baseline.

## Does not establish

This proof does not establish graph completeness, import correctness, entrypoint
completeness, runtime call reachability, causality, retrieval relevance, test
sufficiency, runtime correctness, regression absence, or readiness for
graph-default or Symbol Index promotion.
