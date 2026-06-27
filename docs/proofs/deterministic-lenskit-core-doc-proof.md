# Deterministic Lenskit Core Documentation Proof

## Scope

This slice adds the missing normative core-boundary document. It does not add a
runtime producer, contract artifact, new Primary Lens ID, retrieval mode,
consumer integration, or bundle surface.

## Deterministic evidence

`merger/lenskit/tests/test_deterministic_lenskit_core_doc.py` mechanically checks:

- the documented Primary Lens list equals the implementation's `LENS_IDS` in
  exact order;
- `canonical_md`, snapshot drift, Agent Reading Pack, and health-report authority
  boundaries remain explicit;
- Facet, Relation, State, Task Context, Lens Card, and Relation Card remain
  additive layers;
- LLM inference, embeddings, semantic reranking, autonomous review findings,
  patch generation, and automatic commits remain outside the core;
- required negative semantics and seven change gates remain present.

The slice also fixes one stale status sentence in the Agent Consumption Contract:
Export Safety, Lens Cards, and Relation Cards now exist as scoped surfaces, while
Agent Reading Pack v2 card indexes and promoted Retrieval v2 remain open.

## Does not establish

- Documentation matches every runtime path.
- The repository is understood.
- Existing contracts are correct or complete.
- Runtime behavior or tests are sufficient.
- Regressions are absent.
- Any deferred feature should now be implemented.
