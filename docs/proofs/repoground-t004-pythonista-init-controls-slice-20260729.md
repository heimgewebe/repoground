# T004 follow-up: MergerUI init/state/controls mixins

Task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T004` (partial slice).

## Change

After the first mixin slice (prescan/browser/merge_run), remaining `MergerUI`
methods were extracted:

- `merger_ui_init.py` — `__init__`, bottom bar construction
- `merger_ui_state.py` — save/restore last state and pool serialization
- `merger_ui_controls.py` — selection, extras sheet, profile, parsers

`build.py` is now a thin composition shell (~788 lines) on base
`ede8465246051896955441c7f959379a5926a09d`.

## Validation

- `pytest merger/repoground/tests/ -k pythonista`: 65 passed

## Boundaries

- Does not close full T004
- Does not touch concurrent foreign dirty work on `service/app.py` or `bundle_access.py`
