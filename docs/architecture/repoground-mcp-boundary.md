# RepoGround MCP Boundary

RepoGround MCP is a read-first boundary for existing RepoGround snapshots.

The MCP surface reads existing Brief Bundles. Reading a bundle must never trigger snapshot
creation, refresh, Git mutation, network synchronization, pull-request actions, patch writing,
shell execution, review automation, or secret access. An explicitly configured live-freshness
check may run a bounded local read-only Git probe; it reports drift and never repairs it.

RepoGround has a local stdio protocol server. It is not a networked MCP protocol server:
there is no TCP/HTTP listener, authentication layer, remote scheduler, or service deployment in
this slice. The server binds existing code-level handlers and resources to MCP JSON-RPC without
creating a parallel truth or retrieval layer.

RepoGround MCP may later expose integrated Agent Workbench resources when they are deterministic
read-only code-understanding surfaces. Mutable Patch Evaluation Sidecar authority for patch
application, worktrees, shell/test execution, and patch-evaluation artifacts is defined separately
in [RepoGround Agent Workbench Boundary](repobrief-agent-workbench-boundary.md). That authority
must not be smuggled into RepoGround resources or read-only tools.

## Local stdio protocol server

The implementation lives in:

```text
merger.repoground.cli.mcp_stdio
```

The checkout-independent launcher lives in:

```text
scripts/repoground-mcp-stdio.py
```

Start the default read-only server with an absolute launcher path:

```bash
python3 /absolute/path/to/repoground/scripts/repoground-mcp-stdio.py \
  --bundle-root /absolute/path/to/briefs \
  --repo-root /absolute/path/to/repository
```

It implements the MCP initialization lifecycle and the `tools/list`, `tools/call`,
`resources/list`, `resources/templates/list`, and `resources/read` methods over newline-delimited
stdio JSON-RPC messages. Standard output is reserved for protocol messages. Client setup and the
stable command contract are documented in [RepoGround MCP stdio](../usage/repoground-mcp-stdio.md).

`--repo-root` is the sole checkout permission for the protocol server. Without it, live freshness
is `not_comparable` and no Git probe runs. A tool argument or bundle manifest cannot redirect the
server to inspect another checkout. A manifest-recorded local path remains evidence only; it does
not grant filesystem authority.

## Resources-first surface

RepoGround MCP exposes these stable resources:

- `repoground://snapshot/{stem}/manifest`
- `repoground://snapshot/{stem}/canonical`
- `repoground://snapshot/{stem}/reading-pack`
- `repoground://snapshot/{stem}/health`
- `repoground://snapshot/{stem}/availability`
- `repoground://snapshot/{stem}/artifact/{role}`

These resources are read-only views over files that already exist in a Brief Bundle.

The concrete code-level resource adapter lives in
`merger.repoground.core.mcp_resources`. It implements resource template listing and
resource reads for `manifest`, `canonical`, `reading-pack`, `health`, `availability`, and arbitrary
`artifact/{role}` resources. Each read returns health, freshness, and availability context or an
explicit explanation when the manifest is unavailable. Resource content retains its existing
size, path, and integrity checks.

## Read-only tools

The MCP tools available by default are:

- `ask_context`
- `grounding_verify`
- `live_freshness`

The underlying read-only library surface also contains:

- `snapshot_list`
- `snapshot_status`
- `artifact_get`
- `required_reading_resolve`
- `range_get`
- `query_existing_index`

Read-only tools must not write files, refresh bundles, create snapshots, mutate Git state, open
pull requests, apply patches, run shells, execute reviews, execute fixes, merge changes, or read
secrets. A stale, missing, degraded, or invalid snapshot must be reported as such instead of being
silently regenerated.

`ask_context` exposes the same request/context-pack semantics as `repobrief ask`: it builds a
context pack from existing artifacts and must not create or refresh snapshots.

`grounding_verify` exposes the same declaration/verdict semantics as the Answer Grounding
verifier: it checks declared citations, ranges, task-profile evidence, and caveats against existing
inputs. It must not run reviews, apply fixes, mutate Git, read secrets, or authorize merges.

`live_freshness` compares the snapshot's recorded commit and cleanliness with the one checkout
explicitly configured at server startup. It returns `fresh`, `stale`, `unknown`, or
`not_comparable`. It does not compare remote branches and does not claim pull-request freshness.

## Bounded local Git probe

The live-freshness probe is a narrow exception to the general no-Git read boundary. It may run
only local, read-only Git operations required to establish:

- repository presence;
- current `HEAD`;
- branch name;
- working-tree dirtiness, including untracked files.

The probe:

- never invokes `git_fetch`, `git_pull`, or `git_push`;
- disables optional locks and terminal prompts;
- disables fsmonitor and the untracked cache for the probe;
- ignores global and system Git configuration;
- has a fixed timeout;
- is bound to the operator-provided `--repo-root` in MCP mode.

A dirty snapshot, dirty current tree, or changed `HEAD` is `stale`. Missing cleanliness evidence
is never treated as fresh. No Git subprocess runs when `--repo-root` is absent.

## Explicit write path

RepoGround exposes one explicit write handler:

- `snapshot_create`

The handler lives in `merger.repoground.core.mcp_tools`. It may write only Brief Bundle
artifacts. It must not be reachable as a side effect of resource reads or read-only tools.

The stdio server does not list or accept `snapshot_create` by default. The operator must start it
with both `--enable-snapshot-create` and an explicit `--repo-root`.

When enabled:

- the source repository is fixed to the startup `--repo-root`;
- the output root is fixed to the startup `--bundle-root` directory, or the parent of an exact
  manifest supplied as `--bundle-root`;
- the MCP client cannot supply replacement `repo` or `output_root` arguments;
- the MCP client must select an explicit snapshot profile;
- existing timeout, size, output-path, and output-not-inside-repository guards remain active.

This opt-in does not add Git mutation, patch, PR, shell, review, fix, secret, or merge authority.

## Forbidden operations

RepoGround MCP must not expose or indirectly trigger these operations:

- `git_push`
- `git_pull`
- `git_fetch`
- `create_pr`
- `apply_patch`
- `run_shell`
- `auto_review`
- `auto_fix`
- `auto_merge`
- `secret_read`
- `snapshot_create_side_effect`

The forbidden list applies to resource reads, read-only tools, and write-tool orchestration unless
a later architecture document explicitly narrows a safe operation. By default, absence of
permission is the design.

## Negative semantics

RepoGround MCP preserves RepoGround negative semantics. A successful resource read, tool result,
health check, index query, protocol exchange, or `fresh` verdict does not establish:

- `truth`
- `correctness`
- `completeness`
- `runtime_behavior`
- `test_sufficiency`
- `regression_absence`
- `repo_understood`
- `claims_true`
- `forensic_ready`

MCP improves access to evidence. It must not turn access or freshness into proof.


## Bounded legacy alias

Only `repoground://snapshot/...` is an active resource surface. Former schemes are rejected rather than translated. The rule is governed by `docs/contracts/repoground-naming-hard-cut.v1.json`.
