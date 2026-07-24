# RepoGround Core Complexity and Module Reachability v1 — Proof

Slice of `REPOGROUND-LEGACY-RECONCILIATION-V1-T004`. **This slice does not close
T004** — see "Open T004 acceptance gaps".

## Binding

- Base commit: `5188d2faf335aaaefe4d27122df71d770647cb5b`
- Complexity policy: `config/repoground-graph-maintainability.v1.json`
- C901 baseline: `config/repoground-c901-baseline.v1.json`
- Reachability policy: `config/repoground-module-reachability.v1.json`
- Gates: `scripts/ci/check_graph_maintainability.py`, `scripts/ci/check_module_reachability.py`
- Benchmark: `scripts/benchmarks/repoground_core_paths.py`
- Bound measurements:
  - `docs/proofs/repoground-core-complexity-v1.before.measurement.json` (commit `bf43b2ed`, clean worktree)
  - `docs/proofs/repoground-core-complexity-v1.after.measurement.json` (commit `b3fbeb92`, clean worktree)
  - `docs/proofs/repoground-core-complexity-v1.reachability.measurement.json`

## Current-main port verification

The five-commit slice was originally prepared on branch
`refactor/legacy-reconciliation-t004-core-complexity-v1` at
`f8dbf49f4ccbea3cce2886888f06ace96aa8dcd5`. That historical checkout was
read only and was not taken over, reset or modified. Its commits were replayed
individually, without conflict, onto current RepoGround base
`dc67fdcf668942fdf4b5baef4989ce6e1e952c21` in the isolated branch
`refactor/legacy-reconciliation-t004-core-complexity-v2`.

The port was revalidated on the current tree rather than relying on the old
proof summary:

- focused maintainability, reachability and sidecar-integrity suite: 44 passed;
- full repository pytest task `5cb9d09f4af6413fbcd21be6`: terminal success,
  4,748 passed and 2 skipped, exit status 0, lifecycle receipt
  `48d67e772ccab492509282ec99f77eb145cd2ffdf06967cfc5e6eb09ccda1cf9`;
- graph-maintainability gate: pass at 198 C901 findings, maximum 148 and
  excess mass 2533;
- module-reachability gate: pass, 199 production modules measured, no
  unproven or documentation-only module and no findings;
- review hardening: plain strings no longer count as dynamic imports,
  non-equality `__name__` comparisons no longer count as entry points,
  script-style sibling imports require a direct-execution main guard,
  symbol/call-graph sidecars reject every non-canonical SHA-256 digest, and
  sidecar paths require the canonical `.bundle.manifest.json` base suffix so a
  malformed base cannot be overwritten by a secondary artifact.

The historical before/after performance measurements below remain bound to
their recorded commits. Conflict-free replay and current tests do not turn them
into measurements of the later base. The reviewed pull-request head and its
complete diff SHA-256 are recorded separately at delivery time.

## Task re-audit

The task was registered on 2026-07-17 against a much older tree. Three of its
premises no longer hold as written:

- The historical target `repobrief_access.py` is today `merger/repoground/core/bundle_access.py`.
- `REPOGROUND-LEGACY-RECONCILIATION-V1-T003` already decided the product boundary
  (`docs/architecture/product-boundaries.md`): Atlas stays as an explicitly bounded
  optional observation subsystem, OmniWandler and the standalone Repomerger were
  removed from the active tree. No further removal is proposed here.
- A C901 ratchet already existed, but it only blocked *new or worse* identities.
  Total complexity could therefore stay flat forever, which is what the T004
  acceptance criterion about a real, budgeted decrease is aimed at.

## Established

### Complexity fell, measured with the repository's own Ruff configuration

`ruff check --config ruff-ci.toml --select C901 --output-format json .`

| Dimension | T004 reference (recorded 2026-07-17) | Slice start `5188d2fa` (measured) | Now (measured) |
| --- | --- | --- | --- |
| Findings | 213 | 200 | 198 |
| Single-function maximum | 170 | 170 | 148 |
| Excess mass above threshold | not recorded | 2654 | 2533 |

The 213/170 figures are the values the task recorded in July; they are quoted,
not re-measured. The slice-start column was re-measured for this proof from a
clean export of `5188d2fa`, and is the reference the budget is bound to.

The C901 baseline file at `5188d2fa` listed 203 identities, three more than that
commit's scan actually produced: earlier merges had resolved findings without
re-recording the file. The ratchet permits that direction, which is why the
baseline count alone was never a measure of complexity.

The maximum moved because `merge.write_reports_v2` fell from 170 to 73 and its
two nested hotspots — `process_and_write` (27) and `generate_chunk_artifacts` (17)
— fell below the threshold entirely and left the baseline.

No `# noqa: C901`, no threshold change, no new exclude and no reclassification
was used: `ruff-ci.toml` is byte-identical to `5188d2fa` (it selects `F401`,
`F811` and, for this scan, `C901` on the command line, and its only exclusion,
`**/fixtures/**`, predates the slice).

### The decrease is now budgeted, not merely recorded

`config/repoground-graph-maintainability.v1.json` gains `complexity.budget` with
three ceilings that the *current* scan must satisfy: finding count (198),
single-function maximum (148) and excess mass (2533).

The budget is fail-closed:

- A missing or malformed budget is itself a finding, so deleting the budget
  cannot disable the ratchet.
- Every ceiling must be bounded by at least one recorded reference scan, and a
  dimension no reference bounds is a finding. Without that rule the excess-mass
  ceiling — the one dimension the July reference never recorded — could have been
  raised without limit.
- Two references are recorded: the historical T004 scan (213 findings / maximum
  170) and the slice-start scan of `5188d2fa` (200 / 170 / 2654 excess). A
  ceiling above either is rejected, so the slice must beat where it actually
  started, not only the older and laxer figure.
- Excess mass is budgeted alongside the count because splitting one hotspot
  legitimately raises the finding count while lowering real complexity; a budget
  on count alone would penalise the correct refactor.

The C901 baseline was re-recorded from the current scan (198 identities, maximum
148, five identities tightened, none new). That re-recording is a consequence of
the measured reduction, not a substitute for it: a rewritten baseline still has
to satisfy the three budget ceilings, and those cannot be raised.

### Monolith decomposition

`merge.write_reports_v2` carried its whole artifact pipeline in nested closures.
It is split along responsibilities:

- `merger/repoground/core/artifact_io.py` — atomic writes, file hashing,
  deterministic JSON coercion. Dependency-free leaf.
- `merger/repoground/core/bundle_sidecars.py` — symbol index, call graph,
  lens/concept/relation cards, PR delta artifacts. Each writer takes the manifest
  path and its data and returns a path or `None`. It imports `artifact_io` and the
  card producers, never `merge`, so no import cycle exists.
- `merger/repoground/core/merge.py` — module-level dump-index, chunk-record,
  split-part and single-file report writers driven by an explicit
  `_ReportRunConfig` instead of closures.

Behaviour equivalence was checked directly, not only by the test suite: the same
deterministic fixture repository was bundled from a clean export of `096ab21b^`
(pre-refactor) and of `b3fbeb92`, and the produced artifact trees were compared
file by file — twice, once in `dual` mode without splitting, and once with
`split_size=40000` and `redact_secrets=True` so that the extracted split-part and
single-file writers are both exercised (the split run produces seven parts). In
both runs the artifact set, every path, the manifest, the dump index and all 81
chunk records are identical; the only differences are the wall-clock generation
timestamp and the citation identifiers derived from the canonical hash it changes.
A control run of the *same* export against itself produces exactly the same class
of difference, so it is run-to-run noise, not a refactor effect.

`merge.py` did not shrink (7 093 → 7 138 lines); the decomposition moved
complexity out of one function, not code out of the module.

### Reachability evidence

`scripts/ci/check_module_reachability.py` collects positive evidence of use for
every production module and classifies it as `reachable` or `unproven`. It never
classifies a module as dead.

199 production modules, 0 unproven, 0 documentation-only, 6 test-only. The
`allowed_unproven` and `allowed_documentation_only` lists are empty; the six
test-only modules are declared individually. Two Pythonista sibling modules that
were previously misclassified (`build_helpers` and `build_utils`) are now
resolved from their real script-style product imports. No code was removed by
this change.

Evidence is separated into three classes, and the classes are what the policy
acts on:

| Class | Kinds | Observed |
| --- | --- | --- |
| production | `static_import_product` (172), `runtime_surface_reference` (50), `static_import_script` (20), `module_main_block` (14), `dynamic_string_reference` (0), `package_of_referenced_module` (4), `package_data_reference` (1) | required |
| test | `static_import_test` (164), `dynamic_string_reference_test` (0), `package_of_test_referenced_module` (0) | must be declared if it is all a module has |
| documentation | `documented_invocation` (83) | never sufficient |

Six false-PASS risks are handled explicitly:

- **Documentation is not runtime.** `config/` and `docs/` are excluded from the
  runtime corpus. A module path listed in a C901 baseline or in a recorded
  measurement is not a consumer. Documentation-only evidence is a separate,
  weaker class that must be declared in the policy; nothing currently relies on
  it. This document is itself part of the documentation corpus and therefore
  contributes `documented_invocation` evidence to every module it names — which
  is exactly why that class can never carry a module on its own.
- **Tests are not production.** Test and fixture sources feed their own evidence
  class. A production module that only its own tests import is reported as
  `test_only` and must be declared in the policy; an undeclared one fails the
  check, and a stale declaration fails it too. Six modules remain in that
  class. `test_only` is not `dead`: deletion needs positive evidence of non-use.
- **Strings are not loaders.** Plain strings and docstrings in product or test
  code do not establish dynamic reachability. Only literal arguments passed to
  a bound `importlib.import_module` or `__import__` call can emit dynamic-import
  evidence. Strings that name existing packaged data files form a separate
  `package_data_reference` class and can establish only their containing
  package, not an arbitrary module.
- **A comparison is not automatically an entry point.** Only the exact equality
  guard `__name__ == "__main__"` (in either operand order) emits
  `module_main_block`; inequalities and other comparisons do not.
- **Script-style local imports are qualified only against real modules.** This
  captures the Pythonista sibling imports without guessing from names. A
  `from package import symbol` statement credits `package.symbol` only when
  that exact production module exists, so functions and classes cannot
  masquerade as submodules.
- **Substrings are not references, and unreadable source is not absence.**
  Corpus matching is token-exact, so longer names and backup paths do not credit
  a module. An unreadable or unparsable product or script source is a finding;
  deliberately invalid test fixtures are recorded separately and only
  under-claim evidence.

The policy itself is validated before it is used: a wrong `kind`/`version` or a
missing, empty or non-string `package_roots` is a finding, so a malformed policy
cannot fall back to defaults and report a pass over the wrong tree.

### Runtime and memory

`scripts/benchmarks/repoground_core_paths.py` drives the real production entry
points over a deterministic synthetic repository: bundle write (archive and dual),
retrieval index build, retrieval query, cold service-application import and the
optional Atlas scan. Wall time is the minimum of seven samples. For the in-process
cases, peak allocation is measured with `tracemalloc` in one separate run so
tracing overhead never contaminates the timing samples;
`service_app_import` is the exception — it runs in a subprocess and reports
allocation from the timed runs themselves, which the measurement records as
`peak_traced_measured_separately: false`. Its wall time therefore carries
tracing overhead in both the before and the after measurement.

Same host, same Python (3.10.12), same benchmark script digest, same fixture,
seven samples, clean worktrees, before `bf43b2ed` → after `b3fbeb92`:

| Case | Wall before (s) | Wall after (s) | Δ | Peak before (B) | Peak after (B) | Δ |
| --- | --- | --- | --- | --- | --- | --- |
| `bundle_write_archive` | 0.124117 | 0.126338 | +1.8% | 1 989 130 | 1 984 296 | −0.2% |
| `bundle_write_dual` | 0.300833 | 0.301638 | +0.3% | 3 943 328 | 3 937 435 | −0.1% |
| `retrieval_index_build` | 0.017941 | 0.017642 | −1.7% | 399 111 | 399 111 | 0.0% |
| `retrieval_query` | 0.000586 | 0.000584 | −0.3% | 57 264 | 57 264 | 0.0% |
| `service_app_import` | 1.102161 | 1.098461 | −0.3% | 24 228 716 | 24 278 421 | +0.2% |
| `atlas_scan` (optional) | 0.004829 | 0.004897 | +1.4% | 80 024 | 80 024 | 0.0% |

`bf43b2ed` is the commit before the decomposition and `b3fbeb92` the commit after
it, so the pair brackets the refactor. The closing commit of this slice is not
re-measured: it changes only gate code (`module_reachability.py`, the two check
scripts, the two policies and their tests), none of which is imported by any
measured path.

Every delta is within ±2% and both signs occur, so the refactor is
performance-neutral within this host's noise. Atlas is optional and is measured
only when `--include-atlas` is passed; its absence is recorded as a skip, never as
a failure.

No timing gate is applied. Absolute wall time is not reproducible across hosts, so
the script records evidence and leaves comparison to a same-host before/after pair.

## Verification commands

```text
python3 -m pytest -q
python3 -m pytest -q merger/repoground/tests/test_graph_maintainability.py merger/repoground/tests/test_module_reachability.py
python3 scripts/ci/check_graph_maintainability.py --root . --format json
python3 scripts/ci/check_module_reachability.py --root . --format json
ruff check --config ruff-ci.toml .
ruff check --config ruff-ci.toml --select C901 --output-format json .
python3 scripts/benchmarks/repoground_core_paths.py --samples 7 --include-atlas
python3 tools/parity_guard.py
git diff --check
```

## Does not establish

- that the remaining C901 debt is acceptable;
- that `merge.iter_report_blocks` (148),
  `scripts/proofs/guard_relation_validates_schema_audit.py::analyze` (138),
  `snapshot_preflight.consumption_preflight` (116) or `atlas.AtlasScanner.scan`
  (114) are maintainable — they are untouched;
- that the July 2026 reference figures (213 / 170) are reproducible; they are
  quoted from the task record, not re-measured;
- that any module is dead, or that a reachable module is executed at runtime;
- that a test-only module has a production consumer;
- completeness of dynamic loader discovery;
- cross-host comparability of the recorded timings;
- memory use outside the Python allocator;
- absence of regressions on paths the benchmark or the differential bundle
  comparison does not drive.

## Open T004 acceptance gaps

This slice does not close T004. The following remain open and need their own
Bureau follow-up tasks; they are deliberately not claimed here:

1. `merge.iter_report_blocks` (148) is now the repository maximum and is untouched.
   It is a 1 000-line generator over shared local state; splitting it needs its own
   slice with block-level golden output tests.
2. `merger/repoground/frontends/pythonista/build.py` (4 029 lines),
   `merger/repoground/core/bundle_access.py` (3 209 lines) and
   `merger/repoground/service/app.py` (2 394 lines) are not decomposed.
3. `merge.py` itself did not shrink: the extracted report writers still call
   `merge` module functions, so moving them into their own module would create an
   import cycle. Breaking that cycle is a separate slice.
4. The six declared test-only modules are a recorded gap, not a resolved one.
   Each needs its own decision — production consumer, retirement with evidence of
   non-use, or an accepted test-support role.
