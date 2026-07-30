# T011 residual: artifact source access extraction

Bureau task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T011`

## Context

After the first T011 decomposition landed on main (modules
`bundle_roles`, `bounded_artifact_read`, `sqlite_artifact_read`,
`citation_projection`, `call_graph_validation`) and T012 service-router
split merged as PR #1124, `bundle_access.py` still mixed orchestration
with the shared fingerprint / bounded source-load cluster used by both
query and call-navigation paths.

## Change

Extracted `merger/repoground/core/artifact_source_access.py` owning:

- strong/weak stat identity and fingerprint matching
- cache-validation mode (`REPOGROUND_CACHE_VALIDATION` + legacy strict hash)
- stable descriptor-bound artifact and manifest reads
- registered-role source load (`_read_registered_artifact_source`)
- source currency checks (`_artifact_source_is_current` and helpers)

`bundle_access.py` re-exports the historical private names so external
callers and the public facade keep the same import path.

## Structural result

| File | Lines (approx) |
| --- | ---: |
| `bundle_access.py` before residual | 2618 |
| `bundle_access.py` after residual | 2225 |
| `artifact_source_access.py` (new) | 471 |

Delta on the facade is about **-393 lines** without deleting fail-closed
validation (code moved, some tests retargeted to the owning module).

## Validation

- `pytest merger/repoground/tests/test_call_navigation.py test_bundle_access_decomposition.py test_bundle_access_boundary.py test_source_citation_projection.py`: 100 passed
- `ruff` F401 on touched modules: pass
- `scripts/ci/check_graph_maintainability.py`: pass

## Boundaries

- Foreign dirty worktree `REPOGROUND-LEGACY-RECONCILIATION-V1-T004-current-20260727` was not modified (its uncommitted residue enlarges `bundle_access` and was not ported).
- Does not close parent T004; T010 remains blocked on native T017; T013/T014 remain separate.
- Does not claim call-navigation orchestration extraction (still in facade).

## Does not establish

- Production readiness of every dynamic consumer
- That residual facade size meets a final T014 monolith budget
