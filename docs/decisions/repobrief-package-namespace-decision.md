# RepoBrief package namespace decision

Status: decided on 2026-07-12

## Decision

The repository remains `heimgewebe/lenskit` and the Python namespace remains
`merger.lenskit` throughout the 2.x line. **RepoBrief** remains the product name
and `repobrief` remains the primary user-facing CLI name. `rlens` remains a
compatibility/runtime name where already supported.

This is not a branding compromise. It separates the stable internal import
identity from the product vocabulary users and agents see.

## Evidence

The organization code search found external references in `infra`,
`vault-gewebe`, `metarepo` and `vibe-lab`. Inside this repository,
`merger.lenskit` appears 1,218 times across 356 files. The exact inventory and
search limitations are recorded in
`repobrief-package-namespace-decision.v1.json`.

A same-major import rename would therefore create widespread churn, service and
systemd migration risk, and a likely compatibility alias. It would not improve
RepoBrief's evidence quality, runtime safety or user workflow.

## Future gate

A future breaking-major rename is allowed only with a complete consumer
inventory, tested compatibility plan, deprecation period, service-entrypoint
migration and rollback plan. Until then, new user documentation should say
**RepoBrief** and code should continue to import `merger.lenskit`.
