# RepoGround 3 migration inventory

Baseline: `3c342b23274fe1d87483d82b2ef88334fa35fa06`

## Core migration in this repository

- canonical package: `merger.repoground`
- compatibility namespace: `merger.lenskit`
- product command: `python -m merger.repoground` or `scripts/repoground`
- canonical entry modules: `frontends.pythonista.build`, `cli.serve`,
  `cli.ground`, `cli.mcp_stdio`
- release identity: `3.0.0`
- new service environment prefix: `REPOGROUND_`, with bounded `RLENS_`
  fallback

## Intentionally retained legacy vocabulary

The following remain because they identify persisted 2.x contracts, stored
artifacts, compatibility APIs or historical evidence rather than current
branding:

- schema and artifact identifiers containing `repolens`, `repobrief` or
  `rlens` until a paired versioned contract migration exists;
- legacy command/module wrappers and `RLENS_*` fallback variables during 3.x;
- historical changelog, proofs, task board entries and benchmark evidence;
- existing bundle filenames already stored outside the repository.

These are an allowlist category, not permission to introduce new product
surfaces under the former names.

## External consumer cutover required after the core PR

Search and migrate exact references in at least `infra`, `vault-gewebe`,
`metarepo`, `vibe-lab`, Grabowski's rLens tools, systemd user units, local
runtime paths and generated-bundle registries. Each consumer requires its own
isolated branch, tests and rollback evidence. The currently running legacy
service must remain online until the RepoGround service passes a parallel
smoke test.

## Irreversible operations deliberately deferred

- GitHub repository rename `heimgewebe/lenskit` -> `heimgewebe/repoground`
- service-unit cutover and restart
- package/domain publication or reservation
- deletion of compatibility wrappers

These happen only after the core diff is reviewed, CI is green and consumer
references are inventoried against live state.

## Canonical live inventory

The normative machine-readable inventory is `docs/architecture/repoground-3-migration-inventory.v1.json`; the architecture contract is `docs/architecture/repoground-3-migration.md`.
