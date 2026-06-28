# Graph Provenance-Coherent Compilation Proof

## Status

This change implements the G2 slice identified by the Graph Current-State Audit.

## Problem

The Graph Index compiler previously loaded `architecture.graph.v1` and `entrypoints.v1` as unchecked JSON. It copied provenance from the graph document without proving that both source documents belonged to the same run or to the current bundle. A structurally invalid, stale, or mixed-run source pair could therefore influence the derived Graph Index.

## Implemented boundary

`compile_graph_index()` now performs these steps before distance calculation:

1. Load both source documents.
2. Validate the graph against `architecture.graph.v1.schema.json`.
3. Validate the entrypoint document against `entrypoints.v1.schema.json`.
4. Require identical non-empty `run_id` values.
5. Require identical `canonical_dump_index_sha256` values.
6. When the bundle pipeline invokes the compiler, pass the current bundle `run_id` and the actual SHA-256 of its finalized dump index as explicit expected provenance.
7. Propagate structured provenance failures instead of silently omitting the Graph Index.

If `jsonschema` is unavailable, compilation fails closed. It does not emit a supposedly validated Graph Index under degraded validation capability.

The retrieval loader also fails closed when validation support or its packaged schema is unavailable, returning `validation_unavailable` and no graph object.

## Diagnostics

`GraphIndexCompilationError` exposes deterministic machine-readable fields:

- `code`
- `message`
- optional `source`
- ordered `errors`

Schema errors use stable JSON paths. Diagnostic volume is bounded; omitted errors are counted rather than silently discarded. The architecture CLI serializes this structure to stderr and returns exit code `2` for compilation failures.

## Bundle behavior

The bundle path still does not generate graph or entrypoint source documents. This preserves the G2/G3 boundary.

- If both prerequisite sources are absent, the existing clean fallback remains: no Graph Index is emitted.
- If exactly one prerequisite exists, the missing companion source is a fail-closed `source_not_found` error; no Graph Index is written.
- If both sources exist but validation or provenance coherence fails, the error propagates and no Graph Index is written.
- If both sources are valid and explicitly bound to the current run and dump index, the derived Graph Index is emitted and registered as a derived retrieval index.

## Historical audit reconciliation

The Graph Current-State Audit remains a commit-pinned historical diagnosis. Its finding that a stale Graph Index once influenced ranking was not rewritten. The audit regression test now checks the current G1 behavior separately: `stale_or_mismatched` remains visible diagnostically but is not used for ranking.

## Verification surface

Focused tests cover:

- valid coherent compilation;
- graph-source schema rejection;
- entrypoint-source schema rejection;
- source run-ID mismatch;
- source dump-hash mismatch;
- current-bundle run/hash mismatch;
- missing `jsonschema` fail-closed behavior;
- deterministic schema diagnostics;
- conditional bundle emission;
- missing-both-sources fallback;
- missing-single-source fail-closed behavior for each source role;
- bundle-manifest registration with current provenance;
- structured CLI failure output;
- graph end-to-end compilation with schema-valid sources;
- G1 audit reconciliation.

## Non-claims

This slice does not establish:

- graph or entrypoint completeness;
- correctness of detected imports or entrypoints;
- repository understanding;
- runtime reachability or causality;
- change impact;
- test sufficiency;
- automatic source-artifact production;
- default Graph Index use in retrieval;
- regression absence outside the executed checks.

## Retrieval path boundary

An explicitly selected Graph Index is constrained to the SQLite index artifact directory. The query runtime performs only lexical checks on the caller value and passes a filename to the root-bounded loader. This prevents an arbitrary caller-controlled path from reaching the file-open expression while preserving explicit missing-file errors and diagnostic fallback for invalid graph contents.
