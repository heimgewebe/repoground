# Service API

## Log Streaming (SSE)

Clients MAY reconnect using `Last-Event-ID`.
The server guarantees:
- monotonic event ids starting at 1
- resume from id + 1
- final `event: end`
- Last-Event-ID header overrides last_id query param.

### Edge Cases
- **Garbage Last-Event-ID**: If the `Last-Event-ID` header contains non-numeric values, the server responds with **HTTP 400**.
- **Negative Last-Event-ID**: Negative values are clamped to 0 defensively.
- **Future ID**: If `Last-Event-ID` > `len(logs)`, the stream returns only `event: end`.
- **Reconnect after completion**: If the job is already finished and `Last-Event-ID` matches the total log count, the stream returns only `event: end`.

## File System

### `/api/fs/roots`
Returns a list of allowed root entry points.

**Contract:**
Each entry in the `roots` list guarantees the following fields:
- `id`: The logical identifier (e.g., `hub`, `system`).
- `path`: The absolute path on the server.
- `token`: An opaque navigation token required for subsequent `/api/fs/list` calls.

Example:
```json
{
  "roots": [
    { "id": "hub", "path": "/home/user/repos", "token": "..." },
    { "id": "system", "path": "/home/user", "token": "..." }
  ]
}
```

## Context Lookup

### `POST /api/context_lookup`

Typed read-only facade over stored `context_bundle` artifacts. Returns the context bundle payload for a given artifact ID without re-executing any query.

**Auth:** Provide a token using either `Authorization: Bearer <token>` (preferred) or the `token` query parameter.

**Request:**
```json
{ "id": "qart-<hex>" }
```

**Response (ok):**
```json
{
  "status": "ok",
  "id": "qart-abc123",
  "context_bundle": { "query": "main", "hits": [...] },
  "provenance": { "source_query": "main", "timestamp": "2024-01-01T00:00:00+00:00", "index_id": "test-art", "run_id": null },
  "created_at": "2024-01-01T00:00:00+00:00",
  "authority": "runtime_observation",
  "canonicality": "observation",
  "artifact_shape": "projected",
  "retention_policy": "unbounded_currently",
  "lifecycle_status": "active",
  "expires_at": null,
  "claim_boundaries": {
    "does_not_prove": [
      "Artifact ID stability is limited to this store location.",
      "Runtime artifact does not prove live repository state.",
      "Context bundle is stored in projected API form, not raw execute_query form."
    ]
  },
  "warnings": []
}
```

**Response (not found / wrong type):**
```json
{
  "status": "not_found",
  "id": "qart-abc123",
  "context_bundle": null,
  "provenance": null,
  "created_at": null,
  "warnings": ["Artifact 'qart-abc123' has type 'query_trace', not 'context_bundle'"]
}
```

**Notes:**
- Read-only. Never recomputes, reconstructs, or re-executes a query.
- Only returns artifacts of type `context_bundle`. If the ID exists but refers to a different artifact type, `status: "not_found"` is returned with a warning naming the actual type — no foreign artifact data is leaked.
- Context bundle artifacts are stored automatically when `/api/query` produces a `context_bundle`, for example via `build_context_bundle=true` or an output profile / context mode that includes a context bundle. In those cases, the ID is returned in `artifact_ids.context_bundle` of the query response.
- `trace=true` alone stores a `query_trace`; it does not by itself guarantee `artifact_ids.context_bundle`.
- Extra request fields are rejected with HTTP 422 (`additionalProperties: false` per contract).
- Contract: `merger/lenskit/contracts/context-lookup.v1.schema.json`

## Diagnostics

### `GET /api/diagnostics`

Read-only lookup facade over the persisted diagnostics snapshot.

**Auth:** Standard service auth via `verify_token`; provide a token using either `Authorization: Bearer <token>` (preferred) or the `token` query parameter.

**Behavior:**
- Reads `.gewebe/cache/diagnostics.snapshot.json`.
- Does **not** trigger `POST /api/diagnostics/rebuild`.
- Does **not** modify, rewrite, or mutate the snapshot file.
- Returns a lookup envelope (`status`, `snapshot`, `freshness`, `warnings`) instead of projecting snapshot fields to top-level.

**Response shape:**
```json
{
  "status": "ok",
  "snapshot": { "schema_version": "diagnostics.snapshot.v1", "...": "..." },
  "freshness": {
    "generated_at": "2026-01-01T00:00:00Z",
    "ttl_hours": 24,
    "is_stale": false,
    "age_seconds": 120
  },
  "warnings": []
}
```

**Status semantics:**
- `status` is the **lookup status** (`ok`, `not_found`, `error`).
- Staleness is represented by `freshness.is_stale` (TTL exceeded).
- The endpoint does not remap lookup status to `warn` for stale snapshots.

**Notes:**
- `not_found`: snapshot file does not exist.
- `error`: snapshot file exists but cannot be parsed as JSON.
- `freshness` is `null` if `generated_at` is absent/invalid or if lookup fails.
- Contract: `merger/lenskit/contracts/diagnostics-lookup.v1.schema.json`.

## Trace Lookup

### `POST /api/trace_lookup`

Typed read-only facade over stored `query_trace` artifacts. Returns the trace payload for a given artifact ID without re-executing any query.

**Auth:** `Authorization: Bearer <token>` required.

**Request:**
```json
{ "id": "qart-<hex>" }
```

**Response (ok):**
```json
{
  "status": "ok",
  "id": "qart-abc123",
  "trace": { "query_input": "...", "timings": {}, "..." : "..." },
  "provenance": { "source_query": "main", "timestamp": "2024-01-01T00:00:00+00:00", "index_id": "test-art", "run_id": null },
  "created_at": "2024-01-01T00:00:00+00:00",
  "authority": "runtime_observation",
  "canonicality": "observation",
  "artifact_shape": "raw",
  "retention_policy": "unbounded_currently",
  "lifecycle_status": "active",
  "expires_at": null,
  "claim_boundaries": {
    "does_not_prove": [
      "Artifact ID stability is limited to this store location.",
      "Runtime artifact does not prove live repository state."
    ]
  },
  "warnings": []
}
```

**Response (not found / wrong type):**
```json
{
  "status": "not_found",
  "id": "qart-abc123",
  "trace": null,
  "provenance": null,
  "created_at": null,
  "warnings": ["Artifact 'qart-abc123' has type 'context_bundle', not 'query_trace'"]
}
```

**Notes:**
- Read-only. Never recomputes or re-executes a query.
- Only returns artifacts of type `query_trace`. If the ID exists but refers to a different artifact type, `status: "not_found"` is returned with a warning naming the actual type — no foreign artifact data is leaked.
- Artifacts are stored automatically when `/api/query` is called with `trace=true`. The ID is returned in `artifact_ids.query_trace` of the query response.
- Extra request fields are rejected with HTTP 422 (`additionalProperties: false` per contract).
- Contract: `merger/lenskit/contracts/trace-lookup.v1.schema.json`

## Agent Query Session

When `/api/query` or `/api/federation/query` is called with `trace=true` and a `context_bundle` is present in the result, the response wrapper includes an `agent_query_session` field. This includes context bundles produced by an `output_profile` as well as cases where `build_context_bundle=true`.

**Provenance classification:**  
The `agent_query_session` is always classified as `session_authority: "agent_context_projection"`. This means:
- It is a projection built from query results and runtime artifact references — **not** canonical repository content.
- `artifact_refs.query_trace_id` carries the stable artifact store ID for the `query_trace` artifact (`null` for `/api/federation/query`, which does not produce a standalone query_trace).
- `artifact_refs.context_bundle_id` carries the stable artifact store ID for the `context_bundle` artifact (`null` if storage was not triggered, e.g. when `query_artifact_store` is unavailable).
- `artifact_refs.agent_query_session_id` is **always `null`** in the stored and response payload. The self-ID is circular: the session must be stored before its own ID is known, and no store-update mechanism exists. The assigned ID is instead surfaced via `artifact_ids.agent_query_session` at the top level of the response.
- `claim_boundaries.does_not_prove` explicitly states that the session does not prove live repository state, semantic completeness, or any truth beyond what the referenced artifacts contain at query time.

**Artifact storage per endpoint:**

Storage entries below assume `query_artifact_store` is configured. If the store is unavailable, runtime artifacts are not persisted and the corresponding IDs remain absent or `null`.

| Endpoint | `query_trace` stored | `context_bundle` stored | `agent_query_session` stored |
|---|---|---|---|
| `/api/query` | Yes (when `trace=true`) | Yes (when `trace=true` or `build_context_bundle=true`) | Yes (when session is built) |
| `/api/federation/query` | No (no standalone federation query_trace artifact) | Yes (when `trace=true` or `build_context_bundle=true`) | Yes (when session is built) |

**Context source mapping:**

| `session_meta.context_source` | Top-level `context_source` |
|---|---|
| `projected` | `projected` |
| `federated` | `federated` |
| `both` | `mixed` |
| `none` | `unknown` |

**Schema:** `merger/lenskit/contracts/agent-query-session.v2.schema.json`

**Runtime Artifact Lifecycle Metadata (v1):**

All runtime artifacts stored in the `QueryArtifactStore` (`query_trace`, `context_bundle`, `agent_query_session`) carry explicit lifecycle metadata:

| Field | Value |
|---|---|
| `retention_policy` | `"unbounded_currently"` |
| `lifecycle_status` | `"active"` |
| `expires_at` | `null` |

- No GC (Garbage Collection) is applied.
- No TTL (Time-to-Live) is set.
- No automatic deletion occurs.
- Legacy entries missing these fields are transparently backfilled on read.
- These fields are groundwork for future Retention, MCP, and Agent-Orchestration logic.

## Mutation Boundary Classification

Lenskit API documentation distinguishes four classes for mutation-near buttons or paths. This is a contract boundary, not an implementation of new endpoints:

| Class | Meaning | Agent exposure |
|---|---|---|
| `read-only observation` | Lookup, query, diagnostics, trace, or context access that reads or reports evidence without mutating source repos, working trees, user files, or derived artifact outputs. | May be consumed through authorized read-only adapters. |
| `local artifact generation` | Snapshot, inventory, report, or merge-artifact generation that may write derived files locally, for example under a merges or artifact directory, while still avoiding source-repo or working-tree mutation. | May be exposed only where local artifact writes are explicitly documented, bounded, and authorized; it must not be presented as side-effect-free read-only access. |
| `bounded repo-sync mutation` | Narrow Omnipull-style repo preparation: plan/report, clone missing repos, fetch/prune existing repos, and clean fast-forward only. | Must remain locally authorized, report-producing, and unavailable as a general external Agent tool. |
| `local-only forensic operation` | Broad local filesystem or forensic inspection, especially profiles marked non-exportable. | Must remain local-only unless a reviewed, redacted export artifact is produced. |

Omnipull-shaped paths, if added later, must be documented and tested as `bounded repo-sync mutation`. They are not generic command execution and must not provide arbitrary shell command, branch switching, reset, stash, rebase, untracked-file deletion, or local-change discard semantics. Snapshot and Merger controls must similarly state whether they are read-only observation, local artifact generation, or local-only forensic work before they are exposed beyond the local rLens peer.

## Job Submission & Dispatch

### `include_paths_by_repo` Semantics
When submitting a job with `include_paths_by_repo`, the keys in the dictionary MUST exactly match the repository folder name as it exists on the Hub disk.
- The backend performs **no automatic normalization** (no lowercasing, no path stripping).
- **Strict Mode**: If `strict_include_paths_by_repo: true` is sent, missing keys trigger a `400 Bad Request` (Job Failed) instead of a fallback. This is the default for WebUI "Combined" jobs.
- **Soft Mode (Default)**: If strict mode is false, a missing key logs a warning and falls back to the global `include_paths` (or full scan if none).
- This ensures predictability and prevents ambiguous matches in complex directory structures.

### `pre_pull` Semantics (Bounded Repo-Sync Mutation)

`JobRequest.pre_pull` (`bool`, **default `true`**) requests a fast-forward-only
update of every selected local repo **before** it is scanned, so a fresh dump
reflects current upstream state instead of a stale checkout.

This is classified as a **`bounded repo-sync mutation`** (see *Mutation Boundary
Classification* above), implemented in `merger/lenskit/service/repo_sync.py` and
invoked by the runner *before* `scan_repo()` — never in `core/merge.py`.

**One contract, every surface.** The effective pre-pull is the same everywhere
(rLens service runner, WebUI, rLens-client, repoLens UI + headless):

```
effective_pre_pull = requested_pre_pull and not plan_only
```

`plan_only=true` therefore **never** mutates local repos — no fetch, no merge, no
apply. Requesting both at once is rejected by the CLIs (`--plan-only --pre-pull`
is an error) and the WebUI forces `pre_pull=false` (and disables the checkbox)
while plan-only is active.

**Two-phase (multi-repo safe).** Pre-pull is split into a *plan* phase and an
*apply* phase:

1. **Plan** every selected repo: read HEAD, check the tracked tree, `fetch --prune`,
   and analyze fast-forwardability. The plan phase **never** mutates the working
   tree.
2. Only if **no** repo's plan hard-failed, **apply** the planned fast-forwards.
   Each apply re-verifies HEAD against the plan (`head_changed` guard) before its
   single `merge --ff-only`.

This guarantees that a plan-phase hard failure on one repo cannot leave another repo HEAD or working tree fast-forwarded, because no apply step is started until all plans are free of hard failures. Apply-phase failures are still reported as hard failures; each apply re-verifies HEAD (`head_changed`) and uses only `merge --ff-only`, but the apply phase is not a rollback transaction if an earlier repo was already fast-forwarded.

**Semantics (per selected repo):**

- `fetch --prune` of the existing remote, then a **fast-forward-only** merge of
  the current branch's upstream (`@{u}`). No merge commits, **no conflict
  resolution**, **no branch switch**.
- It uses explicit git argument lists only — **never** a shell, `git pull`,
  `reset`, `rebase`, `stash`, `checkout`, `switch`, or `clean`, and it never
  deletes untracked files or discards local changes.
- Runs non-interactively (`GIT_TERMINAL_PROMPT=0`); auth-required fetches fail
  fast rather than hanging. Clone of missing repos is **out of scope**.

**Per-repo outcomes** (`PrePullStatus`):

| Status | Class | Effect on job |
|---|---|---|
| `up_to_date`, `fast_forwarded` | success | Scan proceeds |
| `planned_fast_forward` | plan-only intermediate | Becomes `fast_forwarded` in apply (never a final status) |
| `skipped_not_git`, `skipped_no_upstream`, `local_ahead` | warning | Logged + added to `job.warnings`; scan proceeds |
| `dirty`, `diverged`, `fetch_failed`, `merge_failed`, `head_changed`, `untracked_would_be_overwritten`, `error` | hard fail | Job fails before any scan; on a multi-repo plan failure, no repo HEADs or working trees were fast-forwarded |

Notes:
- A dirty **tracked** working tree blocks. Harmless non-colliding **untracked**
  files do not block and are preserved across a fast-forward. Untracked files —
  **including ignored ones** — that would be overwritten by, or path-collide
  (file-vs-file or file-vs-directory) with, the upstream fast-forward are
  detected during the plan phase and produce `untracked_would_be_overwritten`
  (hard fail), preventing any apply. The plan-phase check reads paths
  NUL-terminated; if it cannot complete, the repo hard-fails with `error` rather
  than fast-forwarding.
- **Job reuse:** the effective pre-pull (`pre_pull and not plan_only`) participates in the job content hash. A succeeded job
  is **not** reused when the new request has an effective pre-pull
  (`pre_pull=true and not plan_only`) — the user explicitly wants a fresh
  repo-sync check. A `pre_pull=false` (or `plan_only`) request may reuse a
  succeeded job, and an identical **active** job is always reusable.
- **Self-repo caveat:** if the selected repo is the running rLens code itself
  (typically `repos/lenskit`), an actual fast-forward updates files on disk but
  the live Python process keeps its already-loaded modules. The job emits a
  visible restart warning (logs + `job.warnings`) **only on an actual
  `fast_forwarded`** and **never** auto-restarts the service. Restart
  `rlens.service` manually after updating lenskit.
- CLI: `lenskit rlens-client run` (and repoLens headless) send `pre_pull`
  explicitly; disable with `--no-pre-pull`. `--plan-only` implies
  `pre_pull=false`.
