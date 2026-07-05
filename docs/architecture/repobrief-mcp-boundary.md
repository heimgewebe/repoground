# RepoBrief MCP Boundary

RepoBrief MCP is a read-first boundary for existing RepoBrief snapshots.

The MCP surface reads existing Brief Bundles. Reading a bundle must never trigger snapshot creation, refresh, Git access, pull-request actions, patch writing, shell execution, review automation, or secret access.

This document defines the boundary before an MCP server exists. It is a contract for future implementation, not evidence that MCP resources or tools are implemented today.

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

Read-only tools must not write files, refresh bundles, create snapshots, mutate Git state, open pull requests, apply patches, run shells, execute reviews, execute fixes, merge changes, or read secrets. A stale, missing, degraded, or invalid snapshot must be reported as such instead of being silently regenerated.

## Later explicit write path

A later MCP implementation may add one explicit write tool:

- `snapshot_create`

`snapshot_create` may write only Brief Bundle artifacts. It must not be reachable as a side effect of resource reads or read-only tools.

Any future `snapshot_create` tool requires:

- an explicit repository,
- an explicit snapshot profile,
- a controlled output root,
- a timeout guard,
- a size guard.

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
