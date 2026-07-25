# RepoGround Legacy T010 — Pythonista Build Modularization Proof

## Bound scope

- Task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T010`
- Repository: `heimgewebe/repoground`
- Base: `c91d640bce2b14c4a78a64e83169d56c818fa662`
- Measurement: `repoground-legacy-t010-pythonista-build-v1.measurement.json`
- Measurement SHA-256: `5739d73fa94c66422a92f76ac0536bd37d2f6c6ff1faa91615d79af347d23f9d`

## Implemented boundary

`build.py` remains the Pythonista-compatible entrypoint, while portable responsibilities now live in explicit standard-library modules:

- `import_contract.py`: package import versus direct flat-script bootstrap; package mode leaves `sys.path` unchanged.
- `source_mode.py`: iOS capability gates, source-mode decisions, and two-phase pre-pull logic.
- `cli_args.py`: CLI parser contract.
- `cli_output.py`: scan/output options, delta metadata, and report delivery.
- `cli_runner.py`: dependency-injected headless orchestration.

`build_helpers.py` now follows the same explicit package/flat import contract. The parity guard reads the modular CLI surface rather than assuming a monolith.

## Behaviour and portability evidence

- Direct `build.py --help` from an unrelated directory without `PYTHONPATH`: passed.
- Package import without `sys.path` mutation: passed.
- Flat and package parser defaults: equal.
- New portable modules: standard-library top-level imports only.
- Exact base/current help output: byte-identical, SHA-256 `e18411e4dbd2a40ca15408cd00017ad375c8462b5a0396718bbc03fbc10d978a`.
- Mocked scanner and writer call serialization: identical.
- Parity guard: passed.
- Targeted Pythonista and parity tests: 69 passed.

## Complexity and performance

- `build.py`: 4029 → 3630 lines.
- `main_cli`: 298 lines / complexity 62 → 3 lines / complexity 1.
- Highest extracted orchestration complexity: 17 in `cli_runner.py::_validate_cli_request`.
- Package import median: 0.08 s → 0.08 s; RSS 24,792 KiB → 25,368 KiB.
- Direct help median: 0.09 s → 0.09 s; RSS 31,552 KiB → 30,964 KiB.

No material startup regression was observed. The package-import RSS increase is 576 KiB, approximately 2.3 percent; direct-help RSS decreased by 588 KiB.

## Validation boundary

Static checks, formatting, changed-file compilation, diff whitespace validation, parity guard, and the directly affected tests are green.

The local full suite produced 4,801 passed, 2 skipped, and 33 failed. All 33 failures belong to the unrelated patch-evaluation sidecar and share the host error `bwrap: Creating new namespace failed: Resource temporarily unavailable`. An isolated rerun reproduced 33 failures and 10 passes with the same error. Read-only host observation found no configured process/namespace ceiling, but 15 live Bubblewrap processes and 3,189 tasks in the user-service cgroup. No foreign process was altered. GitHub CI remains the authoritative clean-host gate.

## Follow-up boundaries

- `RBAW-V1-T006` owns production sandbox resource budgets and infrastructure-error semantics.
- `REPOGROUND-LEGACY-RECONCILIATION-V1-T014` owns final Pythonista size/performance convergence and any justified remaining UI monolith work.

This proof does not establish GitHub CI success, merge readiness before current-head review, ownership of the observed Bubblewrap processes, or completion of parent task T004.
