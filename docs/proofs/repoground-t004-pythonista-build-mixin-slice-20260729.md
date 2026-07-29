# T004 follow-up: Pythonista build.py mixin decomposition

Task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T004` (partial slice; does not close full T004).

## Change

`merger/repoground/frontends/pythonista/build.py` was 3630 lines. The largest
`MergerUI` method groups were moved into explicit mixins without behavior change:

- `merger_ui_prescan.py` — prescan sheet/pool UI
- `merger_ui_browser.py` — PR-Schau browser and delta import
- `merger_ui_merge_run.py` — merge run path and post-success form reset

`build.py` is now about 1900 lines. Dual package/flat import contract is preserved.
The scheduler resolves `build.ui` dynamically so existing tests and Pythonista
integrations can replace that mutable UI surface after import.

## Review remediation and optimization

The initial PR head moved ten C901 identities without re-recording the
complexity baseline. The graph-maintainability check therefore rejected them as
new debt even though their measured complexity was unchanged. The baseline was
re-recorded from the current sorted AST-bound scan:

- findings: 193 -> 191
- maximum complexity: 138 -> 138
- excess complexity mass: 2340 (budget ceiling 2348)
- new or regressed identities after re-recording: 0

The first extraction copied almost every `build.py` global into every mixin.
That preserved lookup behavior but created a hidden, overly broad dependency
surface. Each mixin now declares an exact `BUILD_GLOBAL_NAMES` contract; standard
library dependencies are imported locally; and `build.py` binds only the declared
names through an explicit symbol table. Missing contracts or symbols fail during
import. A structural test derives the actual class-global references with
`symtable` and requires an exact match with each declaration.

## Self-review evidence

The base revision `ffc64368b6cd0ab17df3699bae6c0747ae39a0ea` was compared with
the optimized working tree at AST level:

- all 21 methods remaining directly on `MergerUI` are unchanged;
- 11 of 12 extracted methods are AST-identical;
- the only intentional difference is
  `schedule_merge_form_reset_after_success`, which resolves `build.ui` live to
  retain the existing monkeypatch/runtime replacement contract.

This establishes structural equivalence for the moved Python method bodies. It
does not by itself establish complete Pythonista device behavior.

## Validation

- `pytest merger/repoground/tests/ -k pythonista`: 65 passed
- exact mixin dependency-contract tests: 2 passed
- targeted Ruff check for changed Python files: passed
- graph-maintainability check: passed; 191 findings, maximum 138, excess 2340
- focused suites: reset, import policy, import contract, pre-pull

## Open T004 remainder

- `bundle_access.py` and `service/app.py` remain large (foreign dirty worktrees observed for concurrent service and bundle-access slices; not touched here)
- further `MergerUI.__init__` decomposition
- further reduction of high-complexity methods; this slice relocates responsibilities and narrows coupling but does not claim that the extracted methods are simple
