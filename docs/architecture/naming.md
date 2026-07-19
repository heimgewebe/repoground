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

## Hard-cut boundary

Former product names are not active commands, modules, environment variables,
runtime paths, generator names or protocol schemes. The repository audit blocks
those mechanisms immediately; there is no 30-day alias window.

Exact versioned schema IDs, `kind` values and historical evidence may retain their
original spelling because changing them in-place would reinterpret stored data.
They are not public product aliases. The governing contract is
`docs/contracts/repoground-naming-hard-cut.v1.json`.

## Stability boundaries

The 3.0 rename changes product and implementation identity. It does not silently reinterpret stored bundles. Any future persisted identifier migration requires a
paired producer, schema, reader and test change. The full migration and rollback
contract is recorded in
`docs/decisions/repoground-3-naming-and-migration.md`.
