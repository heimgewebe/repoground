# Graph Current-State Audit Proof

## Scope

This slice documents the implemented Architecture Graph surface and records the next safe implementation order. It changes no graph producer, contract, query score, evaluation mode, bundle role, service endpoint, or default.

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

A fixed-input live probe generated the current repository graph and recorded files parsed, nodes, edges, entrypoints, evidence levels, layer coverage, and reachability. Those values are diagnostic observations, not CI thresholds.

## Guard

`merger/lenskit/tests/test_graph_current_state_audit.py` keeps the audit tied to source facts. It fails when the producer call surface, conditional bundle compilation, stale-graph behavior, exploratory CLI provenance, measured values, priorities, or negative semantics drift without updating the audit.

The focused graph and audit suite passed 22 tests. Ruff and `git diff --check` passed.

## Main finding

The highest-priority gap is detected-but-used stale graph data. `load_graph_index()` identifies `stale_or_mismatched`, but `query_core.execute_query()` currently treats that status as usable for graph ranking. The follow-up must preserve the diagnostic status while reverting scoring to the lexical baseline.

## Does not establish

This proof does not establish graph completeness, import correctness, entrypoint completeness, runtime call reachability, causality, retrieval relevance, test sufficiency, runtime correctness, regression absence, or readiness for graph-default or Symbol Index promotion.
