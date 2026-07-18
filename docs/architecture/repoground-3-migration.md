# RepoGround 3 migration architecture

Status: normative migration record; compatibility lifetimes are surface-specific

Baseline: `3c342b23274fe1d87483d82b2ef88334fa35fa06`

Machine inventory: `docs/architecture/repoground-3-migration-inventory.v1.json`

Compatibility exit contract: `docs/contracts/repoground-compatibility-exit.v1.json`

## Decision

RepoGround is the only current product identity. The canonical repository target
is `heimgewebe/repoground`, the primary command is `repoground`, and the sole
implementation namespace is `merger.repoground`.

Lenskit, repoLens, rLens and RepoBrief are not parallel products. They remain
only where an exact historical statement, a persisted 2.x identifier, or a
bounded compatibility delegate requires them.

## One implementation tree

All implementation modules live below `merger/repoground`. The package
`merger/lenskit` contains only the tested 3.x import bridge. Legacy launchers
must delegate into RepoGround and emit warnings on stderr, never on a
machine-readable stdout protocol.

The short package `repoground` is a facade for installed entry points. It does
not own an engine, cache, registry, service or command dispatcher.

## Command model

| Capability | Canonical command |
|---|---|
| capture and bundle publication | `repoground build` |
| indexed retrieval | `repoground query` / `repoground search` |
| architecture, symbol and call navigation | `repoground graph` |
| integrity and freshness checks | `repoground verify` |
| evidence and snapshot operations | `repoground ground` |
| HTTP and Web service | `repoground serve` |
| MCP stdio service | `repoground mcp` |

A command must execute existing functionality or fail explicitly. No placeholder
subcommand is permitted.

## Persisted identities

RepoGround 3.0 does not reinterpret 2.x data. Existing schema IDs, `kind`
values, filenames, bundle generations and manifest fields retain their exact
meaning. Readers accept only the documented legacy identifiers. Conflicting
legacy and new identity fields fail closed.

A future persisted-identity migration needs a new version and a paired producer,
schema, reader, contradiction test and rollback path. Product branding alone is
not such a migration.

## Environment variables

New configuration uses `REPOGROUND_*`. Each documented `RLENS_*` fallback has its own owner, review date and removal criteria in the compatibility exit contract. When both old and new values are set, the RepoGround value wins. `RLENS_SERVICE_UNIT` is no longer accepted after the HTTP service cutover.

## Service cutover

The service cutover is complete only when `repoground.service` is enabled, active,
health-checked, query-tested and bound to an immutable RepoGround runtime. The retired
`rlens.service` must be inactive and disabled before its local unit file is removed.
A foreign process that still launches an old MCP command blocks only that MCP/storage
compatibility surface; it does not justify reactivating the old HTTP service. Live host claims
remain evidence-bound and are not inferred from this document alone.

## External consumers

External repositories are migrated in their own clean worktrees with separate
leases. Active consumers are listed in the machine inventory. Historic proofs,
completed experiment names and persisted contract keys are not rewritten merely
to make a search result disappear.

## Name policy

Current public documentation and active internal imports use RepoGround. The
machine inventory defines the explicit path categories where retired names are
allowed. Tests reject old internal import statements and old product names in
the listed current public documents.

## Rollback

Before the GitHub rename, rollback means reverting the core merge while leaving
the running legacy service untouched. After the rename, GitHub redirects remain
verified and the old service unit can be re-enabled with its unchanged legacy
launcher and environment file. Persisted 2.x artifacts never require rollback
because they are not rewritten.

## Non-claims

This architecture document alone does not prove that the GitHub rename, external
consumer migration or service cutover has happened. Those are live-state claims
and require GitHub, process, systemd, health and Bureau evidence.
