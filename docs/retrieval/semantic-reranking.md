# Semantic Re-Ranking Pipeline

This document outlines the architectural concept for implementing semantic re-ranking in RepoGround, satisfying Phase F of the Retrieval Project Roadmap.

## Context

Following the "Scope Management Principle" of RepoGround, we define complex algorithmic behavior through documentation and explicit schema contracts *before* modifying core logic. The foundational FTS (Full-Text Search) layer is fast, explainable, and handles filtering effectively. Semantic search is introduced strictly as a **re-ranker** applied to the top candidates retrieved by the lexical engine.

## The Pipeline

The retrieval pipeline consists of two stages:

1. **Candidate Generation (Top-K Lexical):**
   The existing `fts5` index executes the query with any applied metadata filters. Instead of retrieving just `K` results, it over-fetches a candidate pool (e.g., K = 50).
2. **Semantic Re-Ranking (Top-N Semantic):**
   The semantic engine processes the queries and candidate pool. Vectors for candidate chunks are retrieved (or calculated dynamically) and compared against the query vector. The top N items (e.g., N = 10) are returned.

## `embedding-policy.v1` Contract

The parameters for this re-ranking step are defined by the `embedding-policy.v1.schema.json` contract. This defines:
- **`model_name`**: Identifies the text embedding model used.
- **`dimensions`**: Specifies the expected vector size.
- **`provider`**: Delineates `api` vs `local` model execution.
- **`similarity_metric`**: Distance metric to compute similarity (e.g., `cosine`).
- **`fallback_behavior`**: Crucially, if the semantic service fails (e.g., API timeout), the policy determines whether to `fail` the request or `ignore` the error and yield the pre-semantic candidates.

### Runtime dimension invariant

For the local provider, RepoGround validates the actual query-vector and document-vector dimensions before calculating similarity. Both must equal the policy's positive `dimensions` value. A mismatch is reported as `dimension_validation: mismatch`; `fallback_behavior: ignore` keeps the unchanged pre-semantic candidate scores and ordering, while `fallback_behavior: fail` raises a bounded error without exposing model internals. A matching size proves only shape compatibility, not semantic quality or model identity.

A direct runtime caller must provide a positive integer `dimensions` value. Omitting it, passing a boolean, or passing a non-positive or non-integer value is rejected instead of preserving the historical silent-ignore behavior. A one-dimensional document vector returned for exactly one candidate is normalized to a one-row batch before validation and scoring; this does not relax the declared dimension or candidate-count checks.

Python lists and tuples may contain ordinary component scalars or vector rows supplied as array-like objects with a one-dimensional `.shape`, such as NumPy arrays or tensors. RepoGround distinguishes zero-dimensional array scalars from vector rows, validates every row dimension, and preserves the original batch count. This keeps the optional pure-Python path consistent with array-backed providers without importing NumPy merely for shape validation.

RepoGround does not infer model identity from vector size. Different models can emit vectors with the same dimension, and runtime fingerprinting would require a separately versioned provenance contract covering model artifacts, revisions, tokenizer state, provider configuration, and reproducible loading. Phase F1 therefore proves shape compatibility only; model identity and semantic quality require independent evidence.

## Evaluation Strategy

We employ a strict **improvement delta vs non-semantic** strategy.

Semantic re-ranking must prove its worth against the established baseline:
- `lenskit eval` will generate metrics (like `recall@10`) using the lexical-only approach.
- The same gold queries (`queries.v1.json`) are evaluated using the semantic re-ranker.
- The measurable difference between the two strategies constitutes the "improvement delta".

All evaluation outputs MUST conform to the existing `retrieval-eval.v1.schema.json` contract.

Semantic re-ranking runs are represented using the same schema as lexical baselines. They are distinguished in evaluation reports via an explicit run label or engine marker carried in the existing `retrieval-eval.v1` structure (no schema extension is introduced in Phase F1). If the current schema lacks such a dedicated marker, Phase F2 will introduce it.

## Stop Criterion

The Phase F1 goal is considered successfully met when the semantic pipeline demonstrates a **measurable improvement** in standard metrics (e.g. `recall@k`) **without introducing new failure classes**. This ensures stability while augmenting the "Retrieval OS" with deeper intent matching capabilities.
