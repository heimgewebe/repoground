# RepoBrief Read-only Adapter without Mirror Authority v1

Status: design_ready  
Task: `TASK-REPOBRIEF-READONLY-ADAPTER-NO-MIRROR-001`

## Purpose

This document defines a broader read-only adapter for RepoBrief consumers without granting repository mirror authority.

The adapter is a narrow consumer facade over existing snapshots, bundle artifacts, indexes, ranges, availability reports and task-facing helper results. It is not a repository mirror, not a synchronization layer and not a mutable workbench.

## Decision

RepoBrief should expose one shared read-only adapter contract for CLI, MCP-shaped handlers, library consumers and future Agent Workbench helpers.

The adapter may only read or derive bounded views from already existing RepoBrief evidence surfaces. It must not acquire authority to clone, fetch, pull, refresh, create PRs, apply patches, run shells, read secrets or silently create snapshots.

## Allowed read surfaces

The adapter may expose:

| Surface | Allowed operation | Boundary |
| --- | --- | --- |
| Snapshot inventory | list known snapshots under an explicit bundle root | no filesystem crawl outside configured roots |
| Bundle manifest | read manifest and artifact roles | manifest is inventory, not content truth |
| Canonical brief source | read canonical Markdown ranges or full content when requested | canonical for snapshot only, not live repo |
| Agent reading pack | read required-reading/navigation surface | navigation, not proof of context use |
| Health and availability | read output/post-emit health, bundle surface validation and availability reports | diagnostic only |
| Artifact by role | resolve an artifact path from manifest/known roles | no implicit generation |
| Citation/range lookup | resolve existing citation/range maps | no semantic claim validation |
| Existing indexes | query existing SQLite/chunk/retrieval indexes | stale/missing/degraded remains visible |
| Workbench static artifacts | read existing graph, symbol, relation or card artifacts | static/navigation only |
| Runtime query artifacts | read explicitly named query/session artifacts | debugging/replay only |

## Forbidden operations

The adapter must not:

- clone repositories;
- fetch, pull, push, checkout or mutate Git;
- inspect live working trees as a fallback for missing snapshot data;
- create snapshots as a side effect of reads;
- silently refresh stale or missing bundles;
- create branches or pull requests;
- apply, write, repair or stage patches;
- run shells, tests, linters, build tools or sandboxes;
- read secrets or privileged environment state;
- execute deployment actions;
- generate review verdicts;
- auto-merge or label changes as safe.

## Minimal adapter interface

A later implementation should keep the surface small and explicit:

| Method | Input | Output | Notes |
| --- | --- | --- | --- |
| `snapshot_list` | bundle root, optional repo/profile filters | snapshot summaries | no refresh |
| `snapshot_status` | snapshot id/stem | status, freshness, availability | unknown/stale is reported, not fixed |
| `artifact_get` | snapshot id/stem, role | artifact descriptor and optional content | role lookup only |
| `canonical_range_get` | snapshot id/stem, range or citation id | canonical text span plus provenance | snapshot-bound |
| `required_reading_resolve` | task profile, available roles | required/recommended/missing surfaces | protocol/navigation only |
| `query_existing_index` | snapshot id/stem, query, index selector | ranked hits plus index status | no index creation |
| `workbench_artifact_get` | snapshot id/stem, workbench artifact role | graph/symbol/card descriptor/content | static evidence only |
| `runtime_artifact_get` | explicit artifact id/path | query/session artifact descriptor/content | debugging only |

Every method should return explicit status fields such as `ok`, `missing`, `stale`, `degraded`, `invalid`, `not_applicable` or `forbidden` instead of smoothing failure into empty success.

## Authority metadata

Every returned object should carry, or be nestable under, these fields:

- `authority`: `canonical_snapshot`, `navigation`, `diagnostic`, `static_analysis`, `external_evidence`, or `debugging`;
- `canonicality`: whether the result is canonical content, a sidecar, an index, a diagnostic or a cache;
- `snapshot_identity`: bundle stem/path and manifest hash when available;
- `freshness_status`: `fresh`, `stale`, `unknown`, `not_comparable`, or `not_applicable`;
- `availability_status`: `available`, `missing`, `degraded`, `invalid`, `profile_excluded`, or `not_applicable`;
- `does_not_establish`: negative semantics appropriate to the surface.

## Failure model

The adapter should fail closed for authority crossings:

| Condition | Expected result |
| --- | --- |
| Missing snapshot | `missing`, no fallback to live repo |
| Stale snapshot | `stale`, no refresh |
| Invalid manifest | `invalid`, no artifact inference beyond safe diagnostics |
| Missing artifact role | `missing`, no generation |
| Missing index | `missing`, no index build |
| Requested live Git/read side effect | `forbidden` |
| Requested shell/test/patch operation | `forbidden` |
| Ambiguous artifact | `degraded` or `invalid`, no guess |

## Relationship to MCP

RepoBrief MCP remains read-first. MCP resources and read-only tools may wrap this adapter, but the adapter must not inherit protocol, network, authentication, scheduler or write-tool authority.

A future `snapshot_create` tool remains a separate explicit write exception for Brief Bundle generation only. It must not be callable through read-only adapter paths and must not authorize patch, shell, Git or PR behavior.

## Relationship to Agent Workbench

The Agent Workbench may consume this adapter for deterministic code-understanding surfaces such as symbols, ranges, graph availability, relation hints and query helpers.

Workbench outputs remain evidence or navigation surfaces. They must not state that a patch is correct, that the repo is understood, that tests are sufficient or that a PR is safe to merge.

## Non-goals

This design does not implement:

- an MCP protocol server;
- snapshot creation;
- repository synchronization;
- git mirror management;
- a patch runner;
- a shell/test executor;
- a secret broker;
- auto-review or auto-fix behavior;
- task registry mutation;
- default retrieval promotion;
- proof that the adapter improves agent correctness.

## Acceptance for v1 design

This design satisfies the first bounded step for `TASK-REPOBRIEF-READONLY-ADAPTER-NO-MIRROR-001` if review accepts that it defines:

- allowed read surfaces;
- forbidden mirror/mutation operations;
- a minimal adapter interface;
- required authority/freshness/availability metadata;
- fail-closed behavior for missing/stale/invalid evidence;
- relationship to MCP and Agent Workbench;
- explicit non-goals and non-claims.

A later implementation task should add code-level contracts and tests before any consumer depends on the adapter.

## Does not establish

This document does not establish:

- adapter implementation;
- MCP deployment;
- runtime correctness;
- test sufficiency;
- review completeness;
- retrieval quality;
- repo understanding;
- merge readiness;
- security correctness;
- absence of regressions.
