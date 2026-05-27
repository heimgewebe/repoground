# Agent Query Session v1/v2 Consolidation Decision

## Problem
`agent_query_session` exists in two live shapes, and both are legitimate today:
- `v1` is the on-disk file artifact written by the CLI trace flow.
- `v2` is the runtime inline service form returned through the API/runtime path.

The shapes are intentionally different, but the naming is close enough to invite drift and false assumptions about a single canonical schema.

## Current Forms

### v1: File artifact
- Produced by the `lenskit query --trace` path.
- Carries `refs.integrity` with SHA256 values.
- Carries `environment` with `lenskit_version`, `index_path`, and `timestamp_utc`.
- Validated against `merger/lenskit/contracts/agent-query-session.v1.schema.json`.

### v2: Runtime inline service form
- Produced by the service runtime path.
- Carries `artifact_refs` and `claim_boundaries`.
- Carries `session_authority` and top-level `context_source` as projection metadata.
- Does not encode v1-style Integrity/Environment semantics.
- Validated against `merger/lenskit/contracts/agent-query-session.v2.schema.json`.

## Decision Options

### A) Keep v1 and v2 permanently separate, and name them more explicitly
Treat v1 as the file artifact contract and v2 as the runtime projection contract. Document the difference as a stable boundary instead of a migration path.

### B) Add a v2 file variant that inherits Integrity/Environment semantics
Define a file-oriented v2 form that keeps the runtime v2 semantics but adds the file-artifact fields needed for traceability and replay safety.

### C) Deprecate v1 later, but only after a compatible v2 file form exists
Retire v1 only when a file-safe replacement exists and the affected consumers can move without losing integrity or environment data.

## Recommendation
Prefer **A for now**.

Reason: the current repo already ships two different responsibilities. v1 is a persisted trace artifact with integrity and environment metadata; v2 is a runtime projection wrapper with provenance boundaries. Forcing them into a single schema now would either drop important v1 semantics or blur the runtime contract with file-artifact concerns. Keeping them separate avoids schema breakage, avoids data loss, and preserves the current runtime behavior.

If consolidation is still desired later, the safe path is **B before C**: first define a file-safe v2 variant, then deprecate v1 only after consumers are migrated and validated.

## Non-Goals
- No immediate migration from v1 to v2.
- No removal of v1.
- No schema breakage for current runtime artifacts.
- No change to emitted runtime session payloads in this PR.

## Follow-up Work Packages
1. Publish a naming glossary that distinguishes the file-artifact and runtime-inline meanings of `agent_query_session`.
2. If consolidation is required, draft a `v2` file variant that preserves Integrity/Environment semantics.
3. Inventory consumers of the v1 file artifact and confirm which ones would need a migration contract.
4. Only after the above, write a deprecation plan for v1 with explicit compatibility checks.
