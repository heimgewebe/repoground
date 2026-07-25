# RepoGround Legacy T010 — Pythonista Build Modularization Proof

## Bound scope

- Task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T010`
- Repository: `heimgewebe/repoground`
- Base: `c91d640bce2b14c4a78a64e83169d56c818fa662`
- Measured implementation head: `ceac34b51566e264b3ba7794a0fdb4d60101e7f2`
- Measurement: `repoground-legacy-t010-pythonista-build-v1.measurement.json`
- Measurement SHA-256: `fbbda078508db8e2a8788980ca035cbce7191296de86126d634c7d368071e0a3`

The proof commit may be a documentation-only descendant of the measured implementation head. No production code may change between the measured head and this proof without regenerating the evidence.

## Implemented boundary

`build.py` remains the Pythonista-compatible entrypoint, while portable responsibilities live in explicit standard-library modules:

- `import_contract.py`: package import versus direct flat-script bootstrap; package mode leaves `sys.path` unchanged.
- `source_mode.py`: iOS capability gates, source-mode decisions, and two-phase pre-pull logic.
- `cli_args.py`: CLI parser contract.
- `cli_output.py`: scan/output options, delta metadata, and report delivery.
- `cli_runner.py`: dependency-injected headless orchestration.

`build_helpers.py` follows the same explicit package/flat import contract. The parity guard reads the modular CLI surface rather than assuming a monolith.

## Review repair

The first PR head failed the repository maintainability ratchet because two newly extracted functions remained above the permitted new-code threshold:

- `cli_runner.py::_validate_cli_request`
- `source_mode.py::run_pre_pull_two_phase`

The measured implementation head separates:

- iOS capability checks, local flag conflicts, and central control-plane validation;
- plan-result logging, hard-failure aggregation, apply-result checks, and self-repository restart warnings.

GitHub lint run `30172906567` is green and reports no new complexity violation.

## Behaviour and portability evidence

- Direct `build.py --help` from an unrelated directory without `PYTHONPATH`: passed on the initial extraction head.
- Package import without `sys.path` mutation: passed.
- Flat and package parser defaults: equal.
- New portable modules: standard-library top-level imports only.
- Initial exact help output against the base: byte-identical, SHA-256 `e18411e4dbd2a40ca15408cd00017ad375c8462b5a0396718bbc03fbc10d978a`.
- Initial mocked scanner and writer call serialization: identical.
- Current-head Frontend Parity Guard run `30172906565`: passed.

## Complexity and performance

- `build.py`: 4,029 → 3,630 lines.
- `main_cli`: 298 lines / complexity 62 → 3 lines / complexity 1.
- New complexity violations at the measured implementation head: zero according to lint run `30172906567`.
- `cli_runner.py`: 301 lines after review repair.
- `source_mode.py`: 210 lines after review repair.

Performance was measured on initial extraction head `bd90535b1e4d2a850c2b9491de9296bc655f8c75`:

- package import median: 0.08 s → 0.08 s; RSS 24,792 KiB → 25,368 KiB;
- direct help median: 0.09 s → 0.09 s; RSS 31,552 KiB → 30,964 KiB.

The later review repair only splits helper functions, but exact performance equality for `ceac34b5…` is not claimed because performance was not rerun on that head.

## Current-head validation

For implementation head `ceac34b51566e264b3ba7794a0fdb4d60101e7f2`:

- contracts-validate `30172906849`: passed;
- task-index `30172906555`: passed;
- ai-context guard `30172906589`: passed;
- Frontend Parity Guard `30172906565`: passed;
- Doc-Freshness `30172906605`: passed;
- lint `30172906567`: passed;
- CodeQL `30172906572`: passed;
- test-suite `30172906599`: passed, including `pytest-full`, browser tests, WebUI JS tests, and release-candidate checks.

The initial local full suite produced 4,801 passed, 2 skipped, and 33 host-infrastructure failures in the unchanged Patch Evaluation Sidecar tests. GitHub clean-host CI is the authoritative full-suite gate.

## Follow-up boundaries

- `RBAW-V1-T006` owns production sandbox resource budgets and infrastructure-error semantics.
- `REPOGROUND-LEGACY-RECONCILIATION-V1-T014` owns:
  - final Pythonista size and performance convergence;
  - a native Pythonista loader smoke beyond the CPython direct-script contract;
  - any justified replacement of the dynamic module API object with a typed runtime facade.

This proof does not establish native Pythonista loader behaviour beyond the tested direct-script contract, current-head performance equality after the helper split, or completion of parent task T004.
