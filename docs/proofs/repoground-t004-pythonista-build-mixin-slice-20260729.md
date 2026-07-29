# T004 follow-up: Pythonista build.py mixin decomposition

Task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T004` (partial slice; does not close full T004).

## Change

`merger/repoground/frontends/pythonista/build.py` was 3630 lines. The largest
`MergerUI` method groups were moved into explicit mixins without behavior change:

- `merger_ui_prescan.py` — prescan sheet/pool UI
- `merger_ui_browser.py` — PR-Schau browser and delta import
- `merger_ui_merge_run.py` — merge run path and post-success form reset

`build.py` is now ~1877 lines. Dual package/flat import contract preserved.
Mixin free-variables are wired from `build` after module load so tests can still
patch `build.ui`.

## Validation

- `pytest merger/repoground/tests/ -k pythonista`: 63 passed
- Focused suites: reset, import policy, import contract, pre_pull

## Open T004 remainder

- `bundle_access.py` and `service/app.py` remain large (foreign dirty worktrees observed for concurrent service and bundle_access slices; not touched here)
- further MergerUI `__init__` decomposition
- full C901 budget re-measure after remaining monoliths
