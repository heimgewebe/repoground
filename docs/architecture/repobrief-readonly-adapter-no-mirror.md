# RepoBrief Read-only Adapter without Mirror Authority v1

Status: implemented and locally runtime-validated on 2026-07-12
Task: `TASK-REPOBRIEF-READONLY-ADAPTER-NO-MIRROR-001`

## Purpose

The adapter is a small read-only interface over **already existing** RepoBrief
bundles. A consumer supplies a configuration containing allowed directories and
exact bundle manifests. The adapter does not search for repositories, mirror
Git state or repair missing evidence.

Implementation:

- `merger/lenskit/core/repobrief_readonly_adapter.py`
- config schema: `merger/lenskit/contracts/repobrief-readonly-adapter-config.v1.schema.json`
- CLI: `repobrief adapter list` and `repobrief adapter call`
- compatibility contract: `docs/contracts/repobrief-readonly-adapter-compatibility.v1.json`

## Security model

Configuration resolves relative paths against the config directory, resolves
symlinks, and rejects a manifest outside every configured root. Only exact
registered manifests become visible. There is no recursive discovery fallback.

Artifact content reads additionally require:

- a path inside the registered bundle directory;
- manifest-declared byte length and SHA-256;
- a maximum size of 16 MiB;
- UTF-8 text. Binary content is described but not returned.

An integrity mismatch returns `blocked`; it is not smoothed into missing or
success. SQLite and Python-symbol indices are hashed both before and after each
delegated query. If postflight integrity fails, the already computed result is
discarded.

## Interface

| Action | Purpose |
| --- | --- |
| `snapshot_list` | List exact registrations from the config. |
| `snapshot_status` | Read health, availability and snapshot-bound freshness. |
| `artifact_get` | Resolve and optionally integrity-check one manifest role. |
| `canonical_range_get` | Resolve an existing range against canonical snapshot content. |
| `required_reading_resolve` | Project required/recommended/missing reading for a task profile. |
| `query_existing_index` | Query an existing SQLite index in read-only mode. |
| `symbol_search` | Query an existing Python symbol index. |
| `workbench_artifact_get` | Read only a bounded static Workbench role. |
| `runtime_artifact_get` | Read only a bounded diagnostic/runtime role. |

Every response includes an empty write list, forbidden operations and explicit
non-claims.

## Forbidden authority

No adapter action can clone, fetch, pull or push Git; run a shell; inspect a live
worktree as fallback; create or refresh a snapshot; write bundle files; apply a
patch; create a pull request; read secrets; or issue a review/merge verdict.

## CLI, library and MCP relationship

The library class is the canonical adapter implementation. The CLI is a thin
JSON wrapper over the same class. Existing MCP-shaped resources remain separate
transport adapters over RepoBrief access helpers.

Some MCP resources are analogous to adapter reads, but parity is not implied:
MCP can enumerate a supplied bundle root, while this adapter lists only explicit
config registrations. The exact relationship and unbound methods are recorded
in the compatibility contract. No MCP server, authentication or network binding
is created by this implementation.

The existing MCP `snapshot_create` function remains a separate explicit write
tool. It is not reachable through adapter dispatch.

## Runtime evidence

A redacted `full-max` bundle from commit `052c1dcd…` contained 21 manifest
artifacts. Post-emit health, surface validation, export safety and agent export
all passed. Adapter listing, index queries, symbol search and the usefulness
evaluation were then executed while hashing every bundle file before and after.
The inventories were byte-identical and no SQLite sidecar appeared.

Machine-readable evidence:

- `docs/diagnostics/repobrief-readonly-adapter-validation-20260712T2053Z.json`

## Non-claims

This implementation does not establish remote freshness, repository
understanding, answer correctness, MCP deployment, transport security,
authentication, test sufficiency, review completeness or merge readiness.
