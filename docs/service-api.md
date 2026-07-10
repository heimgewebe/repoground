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
Returns a list of allowed root entry points. `hub` and a configured `merges` root are ordinary service roots. The `system` root (the service user's home directory) is returned only when the service runs on loopback with configured Bearer authentication **and** Home was resolved and registered successfully during startup; merely configuring an overlapping Hub or merges root does not mint the `system` alias.

Home is an optional convenience preset, while authenticated filesystem-root access is the core broad capability. If Home resolution or registration fails, startup continues in explicit root-only mode: `system` is omitted from this response, the startup log records the degradation, and a stale direct request using `root=system` returns `503 Service Unavailable`. Failure to initialize the authenticated filesystem root itself remains fatal and fails startup closed.

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

**Runtime Artifact Lifecycle / Retention Policy (v1):**

All runtime artifacts stored in the `QueryArtifactStore` (`query_trace`, `context_bundle`, `agent_query_session`) carry explicit lifecycle metadata derived from the machine-readable policy in `merger/lenskit/service/runtime_artifact_retention.py`:

| Field | Value |
|---|---|
| `retention_policy` | `"unbounded_currently"` |
| `lifecycle_status` | `"active"` |
| `expires_at` | `null` |
| `ttl_enabled` | `false` |
| `ttl_seconds` | `null` |
| `gc_enabled` | `false` |
| `gc_mode` | `"not_implemented"` |
| `deletion_mode` | `"not_supported_by_policy"` |

- Policy ID: `runtime-artifact-retention.v1`.
- Policy status: `explicitly_deferred`.
- No GC (Garbage Collection) is applied.
- No TTL (Time-to-Live) is set.
- No automatic deletion occurs.
- Store diagnostics expose the policy ID and status without rewriting the store.
- Legacy entries missing these fields are transparently backfilled on read and are not rewritten by lookup.

## Admin Restart

The WebUI hard-refresh control is **browser-only**. It clears browser cache and
storage, then reloads the UI; it does **not** restart the backend service.

### `GET /api/admin/capabilities`

Authenticated capability probe for small admin controls.

**Auth:** `Authorization: Bearer <token>` required.

**Response:**
```json
{
  "service_restart_enabled": true
}
```

`service_restart_enabled` is `true` only when all of the following are true:

- `RLENS_ENABLE_SERVICE_RESTART=1`
- `RLENS_SERVICE_UNIT` is absent or matches `^[A-Za-z0-9_.@-]+$`
- the service is running in the existing local-trust mode (loopback-bound with auth configured)

### `POST /api/admin/restart`

Feature-flagged local admin control that schedules a restart of the configured
rLens systemd user unit. It does **not** pull git changes, rebuild diagnostics,
or restart unrelated services.

**Auth:** `Authorization: Bearer <token>` required.

**Environment:**

- `RLENS_ENABLE_SERVICE_RESTART=1` enables the endpoint and WebUI button.
- `RLENS_SERVICE_UNIT=rlens` selects the systemd user unit (default `rlens`).

**Success (`202 Accepted`):**
```json
{
  "status": "scheduled",
  "unit": "rlens",
  "message": "rLens restart scheduled"
}
```

**Blocked (`409 Conflict`):**
```json
{
  "status": "blocked",
  "reason": "jobs_running",
  "running_jobs": 1
}
```

**Disabled / fail-closed (`403 Forbidden`):**
- feature flag is off
- unit name is invalid
- service is not in the existing loopback+auth local-trust mode

**Scheduler failure (`503 Service Unavailable`):**
```json
{
  "status": "error",
  "reason": "scheduler_failed"
}
```

**Operational notes:**

- Restarts are scheduled via `systemd-run --user --on-active=1s ...`, so the
  HTTP handler schedules the restart before the service is replaced.
- Active jobs block the restart.
- Default is off.

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

**Pre-Pull Report Artifact (Early Diagnostic):**
Every job that reaches the effective pre-pull report-writing boundary produces
a structured `pre_pull_report` JSON artifact, unless writing the report itself fails. This artifact contains structured
per-repo status, phase metadata, HEAD/upstream information, messages, and
credential-redacted standard error. The live job log contains only a concise
digest summary of this report.

- **Early Registration:** The report is written and registered immediately after
  the pre-pull plan/apply phases. This ensures that subsequent cancellations, scan failures,
  or write failures do not lose the structured pre-pull evidence.
- **Exception Phases:** If unexpected errors crash the plan or apply phases before completion,
  the report captures the failure with `phase="plan_exception"` or `phase="apply_exception"`.
- **Skip:** No `pre_pull_report` artifact is produced when effective pre-pull is false
  (`plan_only=true` or `pre_pull=false`).

### Source Acquisition (`repo_source_mode`)

rLens Source Acquisition v1 makes *how the content to scan is acquired* explicit.
See `docs/blueprints/rlens-source-acquisition-blueprint.md` for the full design.

New `JobRequest` fields:

- `repo_source_mode` (`"local_current" | "local_ff" | "remote_snapshot" | null`,
  default `null`). When `null`, behaviour is derived from the legacy
  `pre_pull`/`plan_only` flags (`pre_pull and not plan_only` ⇒ `local_ff`, else
  `local_current`), so existing clients are unaffected.
- `remote_ref` (`string | null`): explicit ref for `remote_snapshot`; wins over the policy. Only valid with `remote_snapshot`.
- `remote_ref_policy` (`"upstream" | "same_branch" | "default_branch"`, default `"upstream"`). A non-default value is only valid with `remote_snapshot`.

**Source-mode control plane (HTTP 422).** `/api/jobs` is the hard boundary: it
validates the source-mode combination *before* job hashing, reuse and any git or
network access, and rejects contradictions with **422** (no job created, no
mutation). The CLI, repoLens headless and the WebUI enforce the identical rules
(`validate_source_mode_request`) so they cannot out-permit the API. Rejected
(explicit `pre_pull` only; a bare `repo_source_mode` is accepted):

- `remote_snapshot` + `pre_pull=true` (remote_snapshot never mutates locally);
- `local_current` + `pre_pull=true` (local_current never fast-forwards);
- `local_ff` + `pre_pull=false` (local_ff *is* a fast-forward pre-pull);
- `local_ff` + `plan_only=true` (local_ff would mutate; plan_only forbids it — **never** silently smoothed to `local_current`);
- `remote_ref` or an explicit non-default `remote_ref_policy` on any non-`remote_snapshot` mode (inert fields are rejected, so they cannot drift the job hash).

Modes:

- **`local_current`** — scan the current local working tree; no git mutation.
- **`local_ff`** — the existing bounded fast-forward-only pre-pull, then scan
  the local tree (classified as `bounded repo-sync mutation`).
- **`remote_snapshot`** — scan an isolated materialization of a remote commit
  (classified as `local artifact generation`: it only writes under the snapshot
  cache and never touches the local repo). Solves the no-upstream case:
  `remote_snapshot + default_branch` scans `origin/HEAD` (fallback `origin/main`)
  regardless of the local branch's upstream.

Ref selection: explicit `remote_ref` wins. Otherwise exactly `remote_ref_policy` is used. Missing upstream remains `missing_ref`; rLens does not guess `default_branch` unless that policy is selected.
For `upstream`, the configured tracking remote is used, not implicitly `origin`.
An explicit commit SHA works if the commit is reachable via fetched heads/tags or if the remote server allows direct SHA fetches.

**Security invariants (`remote_snapshot`):** never mutates local hub repos,
never sets an upstream, never switches branches; uses a job-bound cache under
`<merges_dir>/.rlens-source-snapshots/<job_id>/`; every git call is an explicit
argument list with `GIT_TERMINAL_PROMPT=0`; remote URLs, stderr and reports are
credential-redacted; fetch uses `--no-write-fetch-head` so credential-bearing
URLs are not written to `FETCH_HEAD`; tar extraction uses a manual writer (never
`tarfile.extract`) that extracts only regular files/dirs and rejects absolute
paths, `..` traversal, writes through existing symlinked components, and every
symlink/hardlink/FIFO/device member.

**Plan-only:** `remote_snapshot + plan_only` is a dry-plan: remote ref resolution only, no snapshot materialization, no scan, no local repository mutation and no bundle content write. A diagnostic `source_acquisition_report` artifact is still written so the planned ref/commit is inspectable.

**Job reuse:** `repo_source_mode`, `remote_ref` and `remote_ref_policy` are part
of the job content hash. A *succeeded* `remote_snapshot` job is never reused
(moving ref names are not content-stable); active identical jobs still are.

**Source Acquisition Report Artifact:** `remote_snapshot` jobs produce a
`source_acquisition_report` JSON artifact (schema
`lenskit.source_acquisition_report.v1`, file
`rlens-job-{id}_source_acquisition_report.json`). It distinguishes provenance per
repo: `original_path`, `scan_path`, `source_mode`, `resolved_ref`,
`resolved_commit`, `local_repo_mutated` (always `false`), plus credential-redacted `remote_url_redacted`,
`message`, `stderr` and `warnings`. On failure it is registered as an
early-diagnostic artifact. The report shape is pinned by the JSON-Schema contract
`merger/lenskit/contracts/source-acquisition-report.v1.schema.json`
(`additionalProperties: false`); written reports are validated against it in
tests. The report is a provenance/diagnostic signal (structure), not a proof that
the snapshot equals a locally generated bundle.

**v1 limits:** submodules are not recursively materialized (warning
`submodules_not_expanded` when `.gitmodules` is present); Git-LFS content is not
smudged (warning `lfs_not_smudged` when LFS filters/pointers are detected).

**Surfaces:** CLI `lenskit rlens-client run --source-mode {local-current,local-ff,remote-snapshot}`
with `--remote-ref` / `--remote-ref-policy`; WebUI "Quelle" dropdown (+ ref
policy/ref fields for remote-snapshot); repoLens headless `--source-mode` /
`--remote-ref` / `--remote-ref-policy`. Contradictory `--source-mode`/`--pre-pull`
combinations are rejected before any network access.

## Query Filesystem Boundary

`/api/query`, `/api/federation/query`, and `/api/prescan` treat every request-controlled path as an untrusted relative path beneath an already configured service root.

- absolute paths, `..`, dot segments, empty path segments, backslashes, NUL bytes, and surrounding whitespace are rejected;
- paths are canonicalized after validation, and the resolved target must remain beneath the configured root, so symlink escapes are rejected;
- query indexes are opened read-only;
- embedding policies and graph indexes must remain beside the selected query artifact;
- federation indexes must remain beneath the configured merges directory;
- in service/API mode, bundle paths contained in a federation index must remain beneath that federation index directory. Arbitrary external local bundle paths remain available only to an explicit local CLI invocation.

Internal exception details are written to server logs. HTTP clients receive stable generic errors instead of raw exception text, local paths, database diagnostics, or model-loader details.
