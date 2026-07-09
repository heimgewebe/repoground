# RepoBrief MCP Boundary

RepoBrief MCP is a read-first boundary for existing RepoBrief snapshots.

The MCP surface reads existing Brief Bundles. Reading a bundle must never trigger snapshot creation, refresh, Git access, pull-request actions, patch writing, shell execution, review automation, or secret access.

This document defines the boundary before an MCP protocol server exists. Code-level MCP-shaped handlers may exist before protocol binding; their presence is not evidence that an MCP server or MCP resources are deployed.

RepoBrief MCP may later expose integrated Agent Workbench resources when they are deterministic read-only code-understanding surfaces. Mutable Patch Evaluation Sidecar authority for patch application, worktrees, shell/test execution, and patch-evaluation artifacts is defined separately in [RepoBrief Agent Workbench Boundary](repobrief-agent-workbench-boundary.md). That authority must not be smuggled into RepoBrief resources or read-only tools.

## Resources-first surface

RepoBrief MCP should expose stable resources before tools. Planned resources are:

- `repobrief://snapshot/{stem}/manifest`
- `repobrief://snapshot/{stem}/canonical`
- `repobrief://snapshot/{stem}/reading-pack`
- `repobrief://snapshot/{stem}/health`
- `repobrief://snapshot/{stem}/availability`
- `repobrief://snapshot/{stem}/artifact/{role}`

These resources are read-only views over files that already exist in a Brief Bundle.

## Read-only tools

The initial MCP tools are read-only helpers:

- `snapshot_list`
- `snapshot_status`
- `artifact_get`
- `required_reading_resolve`
- `range_get`
- `query_existing_index`
- `ask_context`
- `grounding_verify`

Read-only tools must not write files, refresh bundles, create snapshots, mutate Git state, open pull requests, apply patches, run shells, execute reviews, execute fixes, merge changes, or read secrets. A stale, missing, degraded, or invalid snapshot must be reported as such instead of being silently regenerated.

## Read-only frontdoor tools

`ask_context` exposes the same request/context-pack semantics as `repobrief ask`: it builds a context pack from existing artifacts and must not create or refresh snapshots.

`grounding_verify` exposes the same declaration/verdict semantics as the Answer Grounding verifier: it checks declared citations, ranges, task-profile evidence and caveats against existing inputs. It must not run reviews, apply fixes, mutate Git, read secrets, or authorize merges.

Both tools are code-level MCP-shaped handlers only. Their presence does not establish MCP server availability, transport security, authentication, runtime correctness or answer correctness.

## Explicit write path

RepoBrief exposes one code-level MCP-shaped write handler for a future protocol adapter:

- `snapshot_create`

The handler lives in `merger.lenskit.core.repobrief_mcp_tools`. It may write only Brief Bundle artifacts. It must not be reachable as a side effect of resource reads or read-only tools.

`snapshot_create` requires:

- an explicit repository,
- an explicit snapshot profile,
- a controlled output root,
- a timeout guard,
- a size guard.

The current implementation is a deterministic tool handler, not an MCP protocol server. It does not expose transport, authentication, network binding, resource routing, or scheduler behaviour by itself.

## Forbidden operations

RepoBrief MCP must not expose or indirectly trigger these operations:

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

The forbidden list applies to resource reads, read-only tools, and future write-tool orchestration unless a later architecture document explicitly narrows a safe operation. By default, absence of permission is the design.

## Negative semantics

RepoBrief MCP must preserve RepoBrief negative semantics. A successful resource read, tool result, health check, or index query does not establish:

- `truth`
- `correctness`
- `completeness`
- `runtime_behavior`
- `test_sufficiency`
- `regression_absence`
- `repo_understood`
- `claims_true`
- `forensic_ready`

MCP can improve access to evidence. It must not turn access into proof.
