# Graph Current-State Audit

## Scope

This audit records the implemented Architecture Graph surface on the clean `origin/main` base commit `6f3e4e01`. It is a commit-pinned diagnosis, not a self-updating description of later PR heads. It changes no producer, contract, ranking rule, bundle surface, or default. It does not establish runtime causality or graph completeness.

## Executive finding

Lenskit already has contracts for `architecture.graph`, `entrypoints`, and `architecture.graph_index`; static Python import extraction; entrypoint extraction; graph-index compilation; conditional bundle registration; staleness detection; and opt-in graph-aware query/eval ranking.

The stack is implemented but not production-coherent. The ordinary merge pipeline does not produce the prerequisite Graph and Entrypoints artifacts. More seriously, `query_core.execute_query()` still uses a Graph Index after `load_graph_index()` has classified it as `stale_or_mismatched`. This detected mismatch can therefore change ranking. The current Graph Runtime Contract explicitly permits that behavior. It is the highest-priority defect found here.

## Contracts and evidence

| Surface | Contract | Current producer |
| --- | --- | --- |
| Architecture Graph | `architecture.graph.v1.schema.json` | static Python AST imports |
| Entrypoints | `entrypoints.v1.schema.json` | `__main__.py` and `if __name__ == "__main__"` |
| Graph Index | `architecture.graph_index.v1.schema.json` | directed distances from extracted entrypoints |

The contracts allow evidence levels `S0`, `S1`, and `S2`. Current producers emit S0/S1 entrypoints and S1 import edges only. No runtime-observed S2 producer exists. The artifacts do not themselves carry `authority`, `canonicality`, or `does_not_establish`; the final manifest decorates the Graph Index when present.

## Producer boundaries

`generate_import_graph_document()` handles Python files only. It emits import edges, retains unresolved modules as external strings, assigns every node `layer="unknown"`, leaves `repo` empty, and uses wall-clock `generated_at`. Nodes and edges are sorted, but complete document bytes are not reproducible because time changes. Absolute imports are not generally resolved to local files.

`generate_entrypoints_document()` emits `module_main` with S0 evidence and `cli` with S1 evidence. Although the contract allows `web`, `worker`, and `test`, the current producer does not emit them.

`compile_graph_index()` computes breadth-first directed distances, but it does not validate both input documents before compilation, require equal run IDs, require equal canonical dump hashes, or emit structured negative semantics. Its identity fields come from the Graph input only.

## CLI and merge behavior

The architecture CLI exposes `--entrypoints`, `--import-graph`, and `--graph-index`. Standalone source extraction uses a random UUID-derived run ID and a placeholder hash of 64 zeroes. Those outputs are exploratory, not dump-bound or byte-deterministic.

The normal merge path does not call the Graph or Entrypoints producers. It only compiles a Graph Index when sibling files named `<stem>.architecture_graph.json` and `<stem>.entrypoints.json` already exist. When compiled, the Graph Index is registered as `graph_index_json`, `authority=retrieval_index`, `canonicality=derived`, regenerable and staleness-sensitive. Integration tests cover registration and missing-prerequisite fallback.

The historical bundle `lenskit-max-260626-2038`, generated from commit `05bbd0d608afa8faf581887a455d4dcf6fa15ae9`, contains no Graph Index artifact. It predates the audited commit `6f3e4e01`; therefore it is context only, not current-state evidence for this audit.

## Validation and stale behavior

`load_graph_index()` reports `ok`, `not_found`, `invalid_json`, `invalid_schema`, `stale_or_mismatched`, or `unreadable`. Staleness correctly compares the Graph Index hash with the canonical dump hash recorded in SQLite.

Two gaps remain:

1. Without `jsonschema`, validation is skipped with only a log warning; the returned object does not expose a machine-readable degraded-validation state.
2. `query_core.execute_query()` accepts both `ok` and `stale_or_mismatched` as usable. Explain output reports the mismatch, but graph proximity, entrypoint bonus, and the graph-conditioned test penalty can still affect scores.

## Retrieval use

Graph ranking is already opt-in through explicit Graph Index paths in the query CLI, eval CLI, service query model, and Python API. It combines normalized BM25, graph proximity, entrypoint bonus, and test penalty. Explain diagnostics expose graph status, node ID, distance, bonus, and use state. The default query path does not auto-discover or use a graph. Review-Intent evaluation rejects simultaneous graph or semantic comparison.

## Live measurement

A fixed-input probe against this repository produced:

| Metric | Value |
| --- | ---: |
| Python files seen / parsed | 361 / 360 |
| Graph nodes | 1,060 |
| File / external nodes | 360 / 700 |
| Import edges | 4,197 |
| Unknown-layer share | 1.0 |
| Entrypoints | 44 |
| Entrypoint S0 / S1 | 2 / 42 |
| Reachable / unreachable nodes | 366 / 694 |

One intentionally invalid fixture failed AST parsing. These values describe this commit and current heuristics only; they are not contract values or CI thresholds. The 100% unknown-layer share and external-node majority show that the graph is a useful diagnostic prototype, not yet a strong architecture signal.

## Capability matrix

| Capability | Status |
| --- | --- |
| Contracts | implemented |
| Static Python import graph | implemented, heuristic |
| Entrypoint extraction | implemented, narrow |
| Graph Index compilation | implemented, under-validated |
| Standalone CLI | implemented, exploratory provenance |
| Automatic source-artifact emission | absent |
| Conditional bundle registration | implemented |
| Staleness detection | implemented |
| Safe stale handling | absent |
| Machine-readable degraded schema validation | absent |
| Graph-aware query/eval | implemented, opt-in |
| Graph auto-discovery from bundle | absent |
| Layer enrichment | absent |
| Runtime S2 evidence | absent |
| Symbol Index | absent |

## Prioritized follow-ups

1. **G1 — Ignore mismatched Graph Indexes. Complexity: medium.** Preserve `stale_or_mismatched` in diagnostics but apply no graph bonus, entrypoint bonus, or graph-conditioned penalty.
2. **G2 — Provenance-coherent compilation. Complexity: medium to high.** Validate both inputs and require equal run IDs and canonical hashes before compiling.
3. **G3 — Bundle-bound source production. Complexity: high.** Decide whether merge should produce Graph and Entrypoints with the actual run identity, controlled clock, roles, health, and surface checks.
4. **G4 — Resolution and layer quality. Complexity: high.** Improve local-module resolution and layers only after a graph goldset exists.
5. **G5 — Symbol and wider graph experiments. Complexity: high.** Only after G1-G4; never claim runtime call reachability or impact.

## Does not establish

This audit does not establish repository understanding, graph or entrypoint completeness, import correctness, runtime reachability, causality, architectural importance, change impact, retrieval relevance, test sufficiency, runtime correctness, regression absence, default-promotion readiness, or Symbol Index readiness.
