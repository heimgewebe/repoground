# Naming and vocabulary

RepoBrief is the preferred public name for this system.

This document defines the phase-1 vocabulary migration from legacy Lenskit wording to RepoBrief wording. It changes language and future command direction only. It does not rename Python imports, schema kinds, repositories, or generated artifact formats.

## Phase-1 decision

- Public system name: `RepoBrief`
- Future CLI name: `repobrief`
- Legacy repository name: `lenskit`
- Legacy Python package namespace: `merger.lenskit`
- Compatibility posture: keep existing commands, imports, schema kinds, and generated artifacts valid

## Vocabulary table

| Legacy term | RepoBrief term | Compatibility status |
|---|---|---|
| Lenskit | RepoBrief | preferred public system name |
| lenskit | legacy/internal package | retained in phase 1 |
| dump | Brief Snapshot | preferred user-facing term |
| bundle | Brief Bundle | preferred user-facing term |
| canonical_md | Canonical Brief Source | sole content authority |
| sidecars | Brief Sidecars | navigation and diagnostics |
| agent reading pack | Agent Brief / Reading Pack | retained as compatibility wording |
| output health | Brief Health | formal diagnostic surface |
| post emit health | Brief Health | formal diagnostic surface |
| bundle surface | Brief Surface | artifact-surface coherence |
| range refs | Brief Range References | canonical-source addressing |
| citation map | Brief Citation Map | citation navigation surface |

## Compatibility rules

Phase 1 must not:

- rename `merger.lenskit` imports,
- rename existing JSON `kind` values,
- remove existing CLI commands,
- invalidate existing generated bundles,
- reinterpret Sidecars as truth,
- promote RepoBrief to an autonomous review or patch system.

Phase 1 may:

- add documentation that names RepoBrief,
- add a `repobrief` CLI alias later,
- add RepoBrief command groups while keeping old commands,
- add generated metadata that says RepoBrief is the public system name,
- describe old `lenskit` wording as legacy/internal.

## Artifact authority language

Use these phrases consistently:

- Canonical Brief Source is the sole content authority inside a generated brief.
- Brief Sidecars are navigation, diagnostics, evidence indexes, or caches.
- Brief Health reports performed checks, not repository understanding.
- Brief Bundles are snapshots at generation time.
- Freshness must be explicit; it must not be inferred from naming.

## Future command language

Future user-facing commands should prefer:

- `repobrief snapshot create`
- `repobrief snapshot list`
- `repobrief snapshot status`
- `repobrief artifact get`
- `repobrief required-reading resolve`
- `repobrief range get`
- `repobrief query`
- `repobrief health`
- `repobrief availability`

Existing `lenskit` commands remain compatibility commands until a later migration decision.

## Later rename decision

A later decision may choose one of these paths:

1. brand rename only: repository and package stay `lenskit`, CLI gains `repobrief`;
2. repository rename: GitHub repository becomes `repobrief`;
3. package rename: Python package gains `merger.repobrief`;
4. compatibility bridge: `merger.lenskit` remains while `merger.repobrief` is introduced as a new alias layer.

No later path is selected by this document.
