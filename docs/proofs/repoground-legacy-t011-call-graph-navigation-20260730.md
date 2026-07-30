# T011 residual: call-graph navigation extraction

Bureau task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T011`

Base: `4921ea05` (includes T005 #1126, T011 artifact-source #1125, T012 #1124).

## Change

Extracted call-graph navigation from `bundle_access.py` into
`merger/repoground/core/call_graph_navigation.py`:

- `find_references` / `get_callers` / `get_callees` and private loaders
- process-local warm caches for call/symbol navigation
- call-graph role constants and validation bindings used by navigation

`bundle_access.py` re-exports public and historical private names for API parity.
Shared artifact-source helpers remain in `artifact_source_access` (prior residual).

## Structural result

| File | Lines |
| --- | ---: |
| `bundle_access.py` before | 2224 |
| `bundle_access.py` after | ~1130 |
| `call_graph_navigation.py` (new) | ~1229 |

Facade reduced by about **~1090 lines** for this residual.

## Validation

- `pytest` related (`call_navigation|bundle_access|symbol_index|call_graph|citation`): **500 passed**, 10 skipped
- focused call navigation: 49 passed
- `ruff` F401/C901 on touched modules: pass
- `scripts/ci/check_graph_maintainability.py`: pass

## Does not establish

- Full T011 bureau closeout
- Parent T004 closeout
- That call-nav performance is improved (structure only)
