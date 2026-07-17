# RepoGround 3 naming and migration decision

Status: accepted for 3.0

## Decision

The public product, repository target, command and documentation identity is
**RepoGround** / `repoground`. The canonical Python implementation lives in
`merger.repoground`.

The former names Lenskit, repoLens, rLens and RepoBrief are not independent
products in 3.x. Their capabilities are expressed as RepoGround operations:

| Former surface | RepoGround 3 surface |
|---|---|
| repoLens dump/bundle emitter | `repoground build` |
| rLens HTTP/Web service | `repoground serve` |
| RepoBrief snapshot/ask tools | `repoground ground` and `repoground query` |
| RepoBrief MCP stdio | `repoground mcp` |

## One implementation tree

`merger.repoground` is authoritative. `merger.lenskit` contains only a
deprecated package-path bridge whose search path points at the canonical
package. Legacy entry modules are warning delegates. No compatibility file
may contain a second copy of product logic.

## Compatibility window

The compatibility bridge is supported throughout 3.x and is scheduled for
removal in 4.0. It exists so installed services and external consumers can be
migrated without stopping the currently running legacy service first.

Persisted 2.x bundle roles, schema identifiers, environment variables and
artifact filenames are not globally rewritten. Readers accept only the exact
legacy identifiers already specified by their contracts. New public examples
and entry points use RepoGround. A later contract revision may introduce new
persisted identifiers only as a producer+schema+reader+test change.

New service variables are `REPOGROUND_HOST`, `REPOGROUND_PORT`,
`REPOGROUND_HUB`, `REPOGROUND_MERGES` and `REPOGROUND_TOKEN`. The corresponding
`RLENS_*` variables remain fallback inputs during 3.x.

## Rollback

Before the GitHub repository is renamed or the service is cut over, rollback
is a branch reset to the pre-3.0 main commit. After cutover, rollback means
restoring the old service command while retaining the 3.x compatibility
bridge; persisted bundles are not rewritten during either direction.

## Non-claims

This decision does not establish trademark clearance, package or domain
reservation, GitHub rename completion, external-consumer migration, runtime
deployment, or removal of historical references.
