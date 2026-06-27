# Deterministic Lenskit Core

## Status and purpose

This document is the normative boundary for Lenskit's deterministic core. It is
an architecture contract, not runtime evidence, a bundle artifact, a health
report, a review result, or proof that an implementation matches the contract.
Concrete claims must still resolve to the current repository and, for a bundle,
to its `canonical_md` and associated provenance.

Lenskit is a deterministic lens apparatus for language models, coding agents,
developers, and CI diagnostics. Its job is to create reproducible snapshots,
strict addresses, controlled navigation views, and explicit diagnostic limits.
It is not itself a coding agent or review oracle.

## Content authority and live state

Within one emitted dump bundle:

- `canonical_md` is the sole content authority.
- JSON indexes and sidecars are navigation, diagnostics, evidence addressing, or
  caches according to their declared role.
- Agent Reading Packs are entry and navigation surfaces, not truth.
- Health and surface reports describe performed checks, not repository
  understanding or claim truth.

A dump is a snapshot at generation time. It does not automatically represent a
later working tree, PR diff, GitHub state, runtime, deployment, or test run. When
current state matters, the live repository or explicitly supplied diff must be
checked separately.

## Deterministic processing invariant

For the same accepted inputs, configuration, dependency capability profile, and
repository bytes, a deterministic Lenskit producer must emit the same semantic
result. Stable ordering, controlled vocabularies, explicit fallback states, and
machine-readable degradation take precedence over hidden inference.

Determinism does not establish correctness. A stable mistake remains a mistake.

## Stable Primary Lens layer

The Primary Lens answers only:

> What is this accepted repository path primarily?

It remains single-label and uses exactly these seven IDs:

- `entrypoints`
- `core`
- `interfaces`
- `data_models`
- `pipelines`
- `ui`
- `guards`

New concerns such as contracts, tests, retrieval, evidence state, task relevance,
or file relations must not be smuggled into this ID set. They belong to additive
layers and require their own controlled contracts.

## Additive lens layers

The detailed semantics are defined in `docs/architecture/lens-model.md`. The
core distinguishes:

- **Facet:** an additional deterministic view of one path; zero or more may apply.
- **Relation:** a declared or derived connection between addressable targets.
- **State:** an epistemic, evidence, or resolution condition.
- **Task Context:** why a target is navigatively relevant to an explicit task.
- **Lens Card:** a small derived navigation projection of controlled lens data.
- **Relation Card:** a small derived navigation projection of one relation.

These layers do not replace the Primary Lens, canonical content, or cited
ranges. Cardinality and ordering do not imply priority, importance, causality,
risk, or completeness.

## Validation semantics

A validator `pass` means only that the checks declared by that validator passed
under the recorded capability and input conditions. Depending on the validator,
this may establish schema conformance, controlled vocabulary use, producer
coherence, hash equality, or link resolution.

A pass does not establish:

- `truth`
- `correctness`
- `completeness`
- `repo_understood`
- `claims_true`
- `runtime_behavior`
- `runtime_correctness`
- `test_sufficiency`
- `regression_absence`
- `review_complete`
- `answer_safe_without_citations`
- `forensic_ready`

Unavailable optional dependencies must remain visible as machine-readable
capability or degradation states. They must not silently turn a skipped full
validation into a successful full validation.

## Core exclusions

The deterministic core does not contain or require:

- LLM inference or LLM advisory decisions;
- embeddings;
- semantic reranking;
- free-form semantic summaries as authority;
- autonomous review findings or verdicts;
- impact, safety, approval, or test-sufficiency judgements;
- patch generation or patch application;
- automatic commits, branches, pull requests, merges, or CI approval;
- a repository mirror, worktree manager, or writable MCP control plane.

Read-only adapters may later expose existing artifacts, but an adapter must not
become a second source of truth or a hidden mutation layer.

## Change gates

A change belongs in the deterministic core only when all applicable gates hold:

1. **Authority gate:** canonical content and derived surfaces remain distinct.
2. **Compatibility gate:** established contracts and Primary Lens IDs are not
   silently reinterpreted.
3. **Determinism gate:** equal accepted inputs produce equal semantic outputs.
4. **Negative-semantics gate:** every new diagnostic or navigation artifact says
   what it does not establish.
5. **Measurement gate:** retrieval changes are measured against a versioned
   goldset before any promotion decision.
6. **Provenance gate:** snapshot-bound claims bind to the relevant manifest,
   hashes, ranges, and source state.
7. **Scope gate:** no review verdict, patch automation, LLM, embedding, or hidden
   network dependency enters under a navigation or diagnostic label.

## Existing controlled surfaces

The current architecture already includes scoped implementations for required
reading, consumption declarations and validation, export safety diagnostics,
Primary Lens audit, Facets, Lens Cards, PR Delta Cards, Relation Cards, and an
opt-in deterministic Review-Intent Router. Each retains its own contract and
negative semantics.

Existence of these surfaces does not establish their consumer adoption, bundle
emission, general usefulness, retrieval completeness, or readiness for default
promotion. Missing integration remains an explicit follow-up, not an implied
feature.

## Relationship to other architecture documents

- `docs/architecture/lens-model.md` defines Lens primitives and layer semantics.
- `docs/architecture/two-layer-artifact-pattern.md` defines content versus
  derived artifact roles.
- `docs/architecture/agent-consumption-contract.md` defines required-reading and
  declaration-comparison surfaces.
- `docs/architecture/answer-compliance.md` defines answer-side declarations and
  their limits.
- `docs/architecture/artifact-inventory.md` records concrete artifact roles.

This document governs the boundary between those systems; it does not replace
their contracts or implementation-specific proofs.
