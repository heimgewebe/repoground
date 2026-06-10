# rLens Source Acquisition v1 — Blueprint

Status: implemented (`task/rlens-source-acquisition-v1`); control plane hardened
(TASK-SERVICE-003B): central source-mode validation enforced at `/api/jobs` and
all surfaces, schema-validated report contract, manual link-rejecting tar writer.
Schema: `lenskit.source_acquisition_report.v1`
(`merger/lenskit/contracts/source-acquisition-report.v1.schema.json`).

## Problem

A local repo can sit on a branch that has no upstream tracking branch. Concrete
case: `weltgewebe` checked out on `pr-1164-api-strict` while `origin/main`
exists but the branch has no `@{u}`. The existing bounded pre-pull then correctly
reports `skipped_no_upstream` — `git rev-parse @{u}` fails, so there is nothing to
fast-forward.

Operators want rLens to scan *the remote default branch* in that situation,
**without** mutating the local checkout.

## Why "git pull always" is wrong

Forcing an upstream, switching branches, resetting, or running `git pull` to
"make pre-pull work" would silently discard or rewrite local work, move the
operator's HEAD, or fetch+merge in a single non-inspectable step. The pre-pull
boundary (see `docs/service-api.md`, *Mutation Boundary Classification*) is
deliberately fast-forward-only and never switches branches. The fix is not to
loosen that boundary; it is to add an explicitly *non-mutating* way to scan
remote content.

## Source modes

`JobRequest.repo_source_mode` selects how the on-disk content to scan is
acquired:

| Mode              | Local git mutation         | Scans                         |
| ----------------- | -------------------------- | ----------------------------- |
| `local_current`   | none                       | current local working tree    |
| `local_ff`        | fast-forward-only pre-pull | current local working tree    |
| `remote_snapshot` | none                       | isolated remote materialization |

### Backwards compatibility

`repo_source_mode is None` (the default) preserves existing behaviour, derived
from the legacy `pre_pull`/`plan_only` flags:

* `pre_pull=True and not plan_only` → effective mode `local_ff`.
* `pre_pull=False` or `plan_only=True` → effective mode `local_current`.

When `repo_source_mode` is set explicitly it wins.

## Source-mode control plane (validation)

The source-mode rules live in one place — `validate_source_mode_request()` in
`merger/lenskit/service/source_acquisition.py` — and are enforced identically by
every surface so a client can never out-permit the API:

* **`/api/jobs` is the hard boundary.** `JobRequest` runs the validator and
  FastAPI maps a contradictory body to **HTTP 422** *before* any job hash, reuse
  check, git or network access. The CLI, repoLens/Pythonista headless and the
  WebUI run the same rules locally (CLI/headless: exit 2; WebUI: blocked submit
  with a visible error) but they are surfaces, not the control instance.

Rejected combinations (explicit `pre_pull` only; a bare `repo_source_mode` with
the default `pre_pull` is accepted):

| Combination | Reason |
| ----------- | ------ |
| `remote_snapshot` + `pre_pull=true` | `remote_snapshot` never mutates the local repo. |
| `local_current` + `pre_pull=true` | `local_current` scans as-is; it never fast-forwards. |
| `local_ff` + `pre_pull=false` | `local_ff` *is* a fast-forward pre-pull. |
| `local_ff` + `plan_only=true` | `local_ff` would mutate; `plan_only` forbids mutation. Use `local_current` (plan-only) or `remote_snapshot` (non-mutating remote check). |
| `remote_ref` on any non-`remote_snapshot` mode | the ref only means something for `remote_snapshot`. |
| explicit non-default `remote_ref_policy` on any non-`remote_snapshot` mode | the policy only means something for `remote_snapshot`. |

`local_ff` + `plan_only` is **never** silently smoothed to `local_current`: a
silent coercion would hide a contradictory intent. The default policy
(`upstream`) is inert on local modes and therefore tolerated, so no inert field
drifts the job hash.

## Security invariants

`remote_snapshot`:

* never mutates local hub repos (no fetch into them, no merge, no checkout);
* never sets an upstream;
* never switches branches;
* remote URL is never persisted as cache remote config;
* uses a **job-bound** cache/temp directory under the validated `merges_dir`:
  `<merges_dir>/.rlens-source-snapshots/<job_id>/<repo>/`;
* works even when the local branch has no upstream.

`local_ff` keeps the existing bounded pre-pull semantics unchanged.

All surfaces enforce:

* no `shell=True`; every git command is an explicit argument list;
* `GIT_TERMINAL_PROMPT=0` for all git calls;
* git subprocess output decoded `encoding="utf-8", errors="surrogateescape"`;
* remote URLs, stderr, exceptions and reports are credential-redacted;
* snapshot extraction is hardened by a manual writer (never `tarfile.extract`):
  it extracts only regular files and ordinary directories and **rejects** every
  symlink, hardlink, FIFO and device member, plus absolute paths, `..` traversal
  and any write through an existing symlinked path component;
* job-bound snapshot roots/worktree dirs are rejected when symlinked or escaped,
  and stale worktree files are removed before each extraction.

## Ref resolution

### Ref selection

- Explicit `remote_ref` wins.
- Otherwise exactly `remote_ref_policy` is used.
- Missing `upstream` remains `missing_ref`; rLens does not guess `default_branch` unless that policy is selected.
- `upstream` uses the configured tracking remote and branch, not implicitly `origin`.
- `default_branch` uses `origin/HEAD` by default.
- Explicit tags: `refs/tags/<tag>` supported.
- Explicit commit SHA works if reachable through fetched heads/tags or if the server permits direct SHA fetch.
- Branch names with slash should be passed as `refs/heads/<branch>` if they are not intended as `<remote>/<branch>`.

This is what solves the concrete case: `remote_snapshot + default_branch` scans
the remote default branch regardless of the local branch's upstream state.

## Provenance model

The `source_acquisition_report` distinguishes, per repo, with no silent loss:

* `original_path` — the local hub repo path.
* `scan_path` — the snapshot path (remote_snapshot) or the local repo path.
* `source_mode` — `local_current` / `local_ff` / `remote_snapshot`.
* `resolved_ref` — the remote ref that was resolved.
* `resolved_commit` — the commit SHA that was materialized.
* `local_repo_mutated` — `const: false` (schema-enforced, not merely conventional) for remote_snapshot.

## Materialization

For `remote_snapshot`:

1. Determine the target remote (from the ref policy or tracking branch). Read its URL from the local repo (missing → `missing_remote`).
2. Resolve the ref (above).
3. Build a bare cache git dir under the job-bound snapshot root. The cache does not
   store the remote URL as `remote.origin.url`. Heads and tags are fetched directly from the selected remote URL without storing it as cache config:
   `git --git-dir <cache_git_dir> fetch --no-write-fetch-head --prune <remote_url> +refs/heads/*:refs/remotes/<remote_name>/* +refs/tags/*:refs/tags/*`
   This avoids
   credential-at-rest leakage in `<cache_git_dir>/config` and `FETCH_HEAD`.
4. `rev-parse` the resolved ref to a commit.
5. `git --git-dir … archive --format=tar <commit>` and extract safely in Python.

Safe extraction is a hand-rolled writer: it extracts only regular files and
ordinary directories, and rejects absolute paths, `..` traversal, any write
through an existing symlinked path component, and every symlink, hardlink, FIFO
or device member outright (v1: security before convenience — links are rejected,
not followed). `tarfile.extract` is never used.

## Plan-only semantics

`remote_snapshot + plan_only` is a **dry plan**: ref resolution via remote query
is allowed, but there is no snapshot materialization, no scan, no local repository mutation and
no bundle content write. A diagnostic `source_acquisition_report` artifact is still written so the planned ref/commit is inspectable. The
report status for the repo is `planned`.

## Job hash / reuse

`repo_source_mode`, `remote_ref` and `remote_ref_policy` are part of the job
content hash. Because moving ref names are not content-stable, a *succeeded*
`remote_snapshot` job is never reused (`/api/jobs` refuses reuse, like an
effective pre-pull). Active identical jobs are still reused.

## Known limits

* Submodules are **not** recursively materialized in v1. A `.gitmodules` file in
  the snapshot raises the report warning `submodules_not_expanded`.
* Git-LFS is **not** automatically smudged in v1. LFS filters in `.gitattributes`
  or detected LFS pointer files raise `lfs_not_smudged`.
* Symlinks and hardlinks committed in the source are **not** reproduced in the
  snapshot in v1: such tar members are rejected, so a repo that relies on
  committed symlinks will fail extraction (`extract_failed`) rather than be
  silently rewritten. This is a deliberate security-over-convenience choice.
* A snapshot is *committed* content; it is not guaranteed identical to artifacts
  generated from a locally-modified tree.
* The `source_acquisition_report` is a provenance/diagnostic signal (structure),
  not a truth verdict: it does not prove the snapshot is byte-identical to a
  locally generated bundle. Reports and logs are credential-redacted via explicit
  redaction gates with tests; this reduces leakage, it is not an absolute
  guarantee that credentials can *never* appear.
* Job-bound snapshots remain under `merges_dir` for the life of the job output;
  no persistence/cleanup optimization is in scope for this PR.

## Non-goals

* No auto-upstream as a default.
* No `reset` / `rebase` / `stash` / `checkout` / `switch` / `clean` in the user repo.
* No `git pull` in product code.
* No "clone missing repos into the hub" feature.
* No parallelization, no omnipull build-out, no self-restart.
