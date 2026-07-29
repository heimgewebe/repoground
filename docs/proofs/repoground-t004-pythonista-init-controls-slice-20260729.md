# T004 follow-up: MergerUI init/state/controls mixins

Task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T004` (partial slice).

## Change

After the first mixin slice (prescan/browser/merge_run), remaining `MergerUI`
methods were extracted:

- `merger_ui_init.py` — `__init__`, bottom bar construction
- `merger_ui_state.py` — save/restore last state and pool serialization
- `merger_ui_controls.py` — selection, extras sheet, profile, parsers

`build.py` is now a thin composition shell on base
`ede8465246051896955441c7f959379a5926a09d`.

## Review follow-up

The review on PR #1122 found that the three new mixin modules retained lookups
against the former `build.py` module namespace. Importing the classes succeeded,
but constructing or using them could fail at runtime with `NameError`.

The follow-up now:

- declares an exact `BUILD_GLOBAL_NAMES` contract for all six mixins;
- wires every declared dependency from `build.py` and rejects missing names;
- extends the contract test to every extracted mixin;
- keeps the active Pythonista view pointer authoritative in `build.py` instead
  of copying mutable state into `merger_ui_controls.py`;
- relocates the two unchanged C901 baseline identities without raising any
  complexity ceiling.

## Validation

- `ruff check --config ruff-ci.toml .`: PASS
- `pytest -q merger/repoground/tests/ -k pythonista`: 66 passed
- `pytest -q merger/repoground/tests/test_graph_maintainability.py merger/repoground/tests/test_pythonista_mixin_global_contract.py`: 17 passed
- `python scripts/ci/check_graph_maintainability.py --root . --format json`: PASS
  - finding count: 191 / budget 193
  - max complexity: 138 / budget 138
  - excess total: 2340 / budget 2348
- `python scripts/ci/check_module_reachability.py --root . --format json`: PASS
- AST parity check against the base `MergerUI`: no base method missing; only
  `close_view` intentionally changed to clear shared state through `build.py`.
- Full local suite attempt: 5174 passed, 12 skipped; 33 sidecar sandbox tests
  were blocked together by host namespace exhaustion
  (`bwrap: Creating new namespace failed: Resource temporarily unavailable`).
  This is host infrastructure evidence, not a Pythonista assertion failure.

## Boundaries

- Does not close full T004.
- Does not touch concurrent foreign dirty work on `service/app.py` or
  `bundle_access.py`.
