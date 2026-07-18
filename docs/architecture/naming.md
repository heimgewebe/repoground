# RepoGround naming and vocabulary

RepoGround is the sole current public product name. The repository target,
command name and documentation identity are `repoground`; the canonical Python
implementation namespace is `merger.repoground`.

## Current product vocabulary

| Capability | RepoGround 3 term | Canonical surface |
|---|---|---|
| repository ingestion and bundle generation | RepoGround build | `repoground build` |
| indexed retrieval | RepoGround query | `repoground query` |
| architecture and call navigation | RepoGround graph | `repoground graph` |
| freshness and evidence checks | RepoGround verify | `repoground verify` |
| snapshot and evidence operations | RepoGround ground | `repoground ground` |
| HTTP and Web service | RepoGround service | `repoground serve` |
| MCP stdio integration | RepoGround MCP | `repoground mcp` |

The canonical Markdown artifact remains the sole content authority. Sidecars,
indexes, graphs, reading packs and health reports remain derived navigation or
diagnostic surfaces according to their declared contracts.

## Compatibility vocabulary

Lenskit, repoLens, rLens and RepoBrief are retired product names. They may appear
only in the surface-specific compatibility categories recorded in
`docs/contracts/repoground-compatibility-exit.v1.json`:

- deprecated import, command and script delegates;
- exact persisted 2.x schema, kind and artifact identifiers;
- historical changelog, task, benchmark, diagnostic and proof records;
- migration inventories that explain external consumer work.

A compatibility name does not create a second implementation or a second
product. New code, documentation and examples use RepoGround. Each removable
adapter has an owner, a review date, measurable usage and a zero-usage gate;
unknown usage blocks removal.

## Stability boundaries

The 3.0 rename changes product and implementation identity. It does not silently reinterpret stored bundles. Any future persisted identifier migration requires a
paired producer, schema, reader and test change. The full migration and rollback
contract is recorded in
`docs/decisions/repoground-3-naming-and-migration.md`.
