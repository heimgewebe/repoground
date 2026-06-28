# Graph Stale-Index Baseline Fallback Proof

## Scope

This slice changes only the handling of an explicitly supplied Graph Index whose `canonical_dump_index_sha256` does not match the SQLite retrieval index. Fresh, schema-valid Graph Indexes keep their existing opt-in scoring behavior. The lexical default remains unchanged.

## Previous behavior

`load_graph_index()` correctly returned `stale_or_mismatched`, but `query_core.execute_query()` still set `graph_used=true`. Graph proximity, entrypoint bonus, graph weights, and the graph-conditioned test penalty could therefore alter result scores after a provenance mismatch had already been detected.

## Implemented behavior

- Only `graph_status="ok"` loads a Graph Index into the ranker.
- `stale_or_mismatched` remains visible in per-hit explain diagnostics.
- A mismatched Graph Index reports `graph_used=false`, distance `-1`, and graph bonus `0.0`.
- No graph reason labels or graph-conditioned test penalty are applied.
- Query and evaluation results fall back to the same lexical ordering and scores as the baseline run.
- `docs/architecture/graph-runtime-contract.md` now defines the same semantics.

## Deterministic evidence

`test_stale_graph_is_diagnostic_only` compares a lexical run with a run supplied the same Graph Index after changing only its canonical dump hash. It proves identical path ordering and scores while preserving mismatch diagnostics.

`test_eval_stale_graph_is_diagnostic_only` verifies the evaluation path reports the mismatch, does not use graph scoring, and produces the same top results and reciprocal rank as its baseline lane.

`test_retrieval_eval_claim_boundaries_graph_present_when_graph_actually_used` now binds its positive fixture to the real dump hash. The paired stale-graph test proves that a mismatched graph is absent from `claim_boundaries.evidence_basis`.

Fresh-graph reranking remains covered by the existing positive tests. The focused graph, query, API, evaluation, anti-hallucination, and planning suites passed 360 tests. Ruff, Planning Ratchet, JSON validation, and `git diff --check` passed.

## Does not establish

- The Graph Index is complete or correct.
- Entrypoints or import edges are complete.
- Runtime call reachability or causality.
- Graph-aware ranking is generally beneficial.
- Test coverage is sufficient or regressions are absent.
- Graph ranking is ready for default promotion.
- Automatic Graph/Entrypoints production or bundle discovery exists.
