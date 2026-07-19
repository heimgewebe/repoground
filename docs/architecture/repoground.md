# RepoGround

RepoGround is the sole current product name for the repository-context system.
It turns a repository state into deterministic, citable context for humans,
coding agents, reviews and MCP clients.

The canonical repository target is `heimgewebe/repoground`, the canonical Python
namespace is `merger.repoground`, and the canonical command is `repoground`.
Lenskit, repoLens, rLens and RepoBrief remain only as surface-specific, measured
compatibility adapters or as immutable historical/versioned identifiers. Their owners,
review dates and removal criteria are defined in the compatibility exit contract.

## Purpose

A RepoGround build may produce a bundle containing:

- canonical repository content,
- a bundle manifest,
- an agent reading pack,
- citation and range surfaces,
- retrieval indexes,
- symbol, relation and graph surfaces,
- health and surface diagnostics,
- optional profile-specific reports.

The canonical content is the content authority inside one generated bundle.
Sidecars are navigation, diagnostic, evidence-index or cache surfaces. They help
consumers locate and inspect canonical content; they do not replace it.

A bundle is a snapshot at generation time. It does not automatically represent
the current working tree, the latest GitHub state or a pull-request diff unless
that provenance is explicitly present and checked.

## Commands

The primary command surface is:

```text
repoground build
repoground query
repoground graph
repoground ground
repoground serve
repoground mcp
repoground service-client
```

`ground` contains snapshot and evidence-access operations inherited from the
former RepoBrief surface. `serve` contains the local service inherited from
rLens. These are subcommands of one product, not separate products.

No warning delegate or alternate entry point is part of the active command
surface. Unknown active use of a former command blocks closeout instead of
reactivating an alias.

## Read/create separation

RepoGround has two operation classes:

1. create operations, such as `build`, `ground snapshot create` and explicit
   publication operations, which may write selected output artifacts;
2. read operations, such as `query`, `ground snapshot status`, artifact lookup,
   range resolution, MCP resource reads and freshness checks, which must not
   refresh or mutate source state.

A stale or degraded bundle must be reported as stale or degraded. A read path
must not silently regenerate it.

## MCP boundary

RepoGround MCP is a local stdio boundary over existing repository bundles and
explicitly enabled tools. The implemented contract is documented in
[RepoGround MCP Boundary](repoground-mcp-boundary.md). The local MCP stdio server
binds the existing read-only resource and tool handlers; it is not a network
service and grants no implicit shell, Git, patch, pull-request, review, secret,
fix or merge authority.

The explicit `snapshot_create` handler remains hidden unless the operator
enables it at server startup. Stable startup and generic client configuration
are documented in [RepoGround MCP stdio](../usage/repoground-mcp-stdio.md).
Older schema and kind identifiers retain their exact versioned data meaning.
They do not create an alternate MCP scheme or command surface.

## Agent Workbench boundary

RepoGround is the evidence, snapshot, citation, retrieval and deterministic
analysis layer. Read-only code-understanding surfaces may include AST symbols,
static references, ranges, relations, graph availability and query helpers.

Patch application, mutable worktrees, shell or test execution, sandboxing and
patch-evaluation production belong to an external execution/evaluation layer.
RepoGround may read or link explicit external evidence; it must not create that
evidence or interpret it as approval.

## Non-goals

RepoGround must not:

- trigger implicit refresh during read operations,
- mutate Git as a side effect of reading,
- create pull requests or write patches from the deterministic core,
- generate review verdicts or infer approval,
- treat tests as release authorization,
- claim runtime correctness, completeness or test sufficiency,
- introduce LLM inference into the deterministic core.

A bounded freshness probe may read local `HEAD` and working-tree status from an
explicitly configured checkout. It must not fetch, pull, push, repair or switch
branches, and it must not infer remote freshness.

## Negative semantics

A successful RepoGround operation or valid artifact does not by itself establish:

- truth or correctness,
- completeness,
- runtime behavior,
- test sufficiency,
- regression absence,
- repository understanding,
- claim validity,
- review or merge readiness.

## Profiles

Snapshot profiles are machine-readable policy labels. Each profile classifies
artifact roles as `required`, `recommended`, `optional`, `not_applicable` or
`profile_excluded`. A missing required artifact is a profile-readiness signal;
it is not proof that repository content is wrong.

## Naming hard cut and persisted contracts

Active commands, modules, environment variables, runtime paths, resource schemes
and generator identities use RepoGround exclusively. The immediate rule and its
negative audit are defined in
[`repoground-naming-hard-cut.v1.json`](../contracts/repoground-naming-hard-cut.v1.json).

Existing versioned schema IDs, `kind` values and historical artifact identifiers
retain their exact meaning. They are data contracts, not public aliases, and are
not silently reinterpreted for branding. A future migration requires a new
versioned producer, schema, reader, contradiction test and rollback path.
