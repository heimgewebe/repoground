# Graph Source Roots Contract Proof

## Status

Implements `TASK-GRAPH-SOURCE-ROOTS-CONTRACT-001`, the contract-first G4c slice following the packaging edge-case goldset.

## Delivered surface

- Draft-07 schema `architecture.source_roots.v1.schema.json`;
- minimal schema-valid example;
- architecture semantics and non-claims;
- regression tests for schema validity, canonical relative paths, duplicate roots, closed object shape, and explicit rejection of auto-discovery fields.

## Invariants

The repository root remains implicit. Declared roots are additional, relative POSIX paths. They are unique and have no order-based precedence. The contract forbids absolute paths, backslashes, leading `./`, repeated separators, and dot or parent segments.

The schema intentionally has no `autodiscover` field. Directory-name inference is therefore outside the v1 contract rather than silently enabled by convention.

## Boundary

This task does not change `import_graph.py`, bundle graph-source production, CLI arguments, graph schemas, graph ranking, or the G4b baseline. No import edge changes in this slice.

A later consumer must add repository-context validation for directory existence and source-surface membership, then preserve unresolved output when two declared roots expose different files under one module name.

## Verification

`test_architecture_source_roots_schema.py` validates the schema and example and falsifies noncanonical and ambiguous declaration shapes. The dedicated workflow runs JSON parsing, focused pytest, Ruff, and `git diff --check`.

## Non-claims

The contract does not establish effective runtime `sys.path`, installed-package state, build-backend interpretation, editable-install behavior, import-hook behavior, runtime order, runtime causality, graph completeness, retrieval benefit, or readiness for default graph ranking.
