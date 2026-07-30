# T011 residual: symbol-index access extraction

Bureau task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T011`

Base: `2debb756` (includes call-graph navigation extract #1127).

## Change

Extracted symbol-index load/search into
`merger/repoground/core/symbol_index_access.py`:

- `search_symbol_index` / `_search_symbol_index_full`
- `_load_symbol_index` / `_load_symbol_index_source`
- `_symbol_record` / `_symbol_source_range` / `_registered_source_error`
- `SYMBOL_INDEX_ROLE` / `SYMBOL_SEARCH_KIND` / `MAX_SYMBOL_SEARCH_K`

`bundle_access` re-exports these for historical import paths. Call-graph
navigation continues to resolve symbol helpers via the facade reexports.

## Structural result

| File | Lines |
| --- | ---: |
| `bundle_access.py` before | 1124 |
| `bundle_access.py` after | ~842 |
| `symbol_index_access.py` (new) | ~333 |

## Validation

- Focused symbol/call/bundle tests: 81 passed
- Broader related suite: see commit CI
- maintainability / F401: pass

## Does not establish

- Full T011/T004 bureau closeout
- Query/range extraction (still on facade)
