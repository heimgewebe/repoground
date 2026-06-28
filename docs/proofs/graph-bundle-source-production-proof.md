# Single-Repo Bundle-Bound Graph Source Production Proof

## Status

This implements the first safe G3 slice from the Graph Current-State Audit.

## Implemented boundary

For retrieval or dual output, the ordinary merge pipeline now creates
`architecture.graph.v1` and `entrypoints.v1` source artifacts when the output
contains exactly one repository and neither source already exists. Both sources
receive the actual bundle run ID and finalized dump-index SHA-256. The graph's
`generated_at` is replaced with the merge clock value, and file nodes carry the
repository name.

The producer derives its Python source set from the emitted chunk index rather
than rescanning the complete repository. Only paths with full source contact,
without truncation and with declared source coordinates, are materialized into a
temporary filtered tree for static analysis. Redacted, truncated, unverifiable,
or out-of-scope files cannot silently influence the retrieval Graph Index.

Existing source pairs remain supported. Partial pairs are not silently repaired;
the provenance-coherent compiler fails closed. Unexpected source-production
failures propagate and remove any partially written pair. Multi-repository
automatic production is explicitly skipped because the current Graph Index
identity uses `file:<path>` without a repository discriminator.

If the retrieval surface contains no eligible Python source, the producer emits
a schema-valid empty pair and reports `no eligible full-contact Python sources`
diagnostically. This is an explicit empty observation, not evidence that the
repository contains no Python code.

The source documents are registered as diagnostic, derived, regenerable,
staleness-sensitive artifacts. They are inputs to the retrieval Graph Index, not
canonical repository truth and not runtime observations.

## Verification

Tests cover deterministic single-repository production, actual bundle provenance,
repository labels, Graph Index compilation, derived-manifest and bundle-manifest
registration, full-contact path selection, exclusion of truncated or unverifiable
sources, explicit empty-surface diagnostics, malformed chunk-index rejection,
cleanup after write failure, partial-pair preservation, propagated producer
failures, and explicit multi-repository non-production.

## Non-claims

This does not establish graph completeness, import correctness, runtime causality,
change impact, retrieval benefit, or multi-repository graph identity. It does not
auto-enable graph ranking.
