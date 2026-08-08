# RepoGround Agent Utility T025 proof

Task: `REPOGROUND-AGENT-UTILITY-V1-T025`

Base commit: `6baca4b5751143c6493d3df1b5c0d4df64c141f4`

Observed on: 2026-08-08

## Decision gate

The host runtime is CPython 3.10.12. Before this change, `repoground doctor --json` classified the required `python` check as `degraded` with cause `python_version_outside_ci_release_baseline`, while the same check reported `core_minimum: 3.10` and `core_runtime_supported: true`.

The repository keeps Python 3.12 as the explicit reproducible validation baseline: both the full pytest job and the release-candidate job in `.github/workflows/test-suite.yml` use Python 3.12. T025 does not change that baseline or either CI gate.

Decision: the Doctor status was too strict for a supported host runtime. Runtime support and CI/release equivalence are different claims. A host interpreter that meets the declared core minimum should not degrade the required Doctor status solely because it differs from the CI/release baseline.

Counterhypothesis: CPython 3.10.12 is actually unsupported and the host must migrate to Python 3.12. The current RepoGround contract does not support that conclusion: `CORE_PYTHON_MINIMUM` remains 3.10 and the pre-change Doctor evidence itself reports `core_runtime_supported: true`. Therefore T025 does not mutate or replace the operating-system Python runtime.

## Bounded implementation

`check_python_runtime()` now records whether the CI/release baseline matches separately from whether the core runtime is supported.

- Python below 3.10 remains `blocked`.
- Supported Python outside the 3.12 baseline is `available`, retains cause `python_version_outside_ci_release_baseline`, and explicitly does not establish `ci_release_equivalence`.
- Python 3.12 remains the reproduced CI/release baseline and keeps the baseline-match path unchanged.
- No CI workflow, release gate, dependency lock, wrapper, service, adapter, or operating-system runtime is changed.

## Local verification before publication

Focused Doctor regression gate:

```text
python3 -m pytest -q merger/repoground/tests/test_doctor.py
19 passed in 0.29s
```

Branch-local CLI readback on CPython 3.10.12 reports:

```text
python.status = available
python.cause = python_version_outside_ci_release_baseline
python.evidence.core_runtime_supported = true
python.evidence.ci_release_baseline = 3.12
python.evidence.ci_release_baseline_matches = false
python.does_not_establish = [ci_release_equivalence]
```

The branch-local overall Doctor remains `degraded` before commit because freshness correctly detects the intentionally dirty implementation worktree. That freshness result is independent of the Python-runtime classification and is not overridden by T025.

Live pre-change host evidence also established that `repoground.service` is active/running with zero restarts and that `/home/alex/.local/bin/repoground` is byte-identical to the tracked canonical wrapper (`sha256:6f12e8c0bb598f0d91c83139a7e9bfb3e072af6b43e29a0da9f16d56892a7e16`).

## Nonclaims

This change does not establish that:

- Python 3.10 is CI/release-equivalent to Python 3.12;
- every future RepoGround feature will remain compatible with Python 3.10;
- the optional Rust or Bash structure adapters are available;
- a dirty or revision-mismatched checkout is fresh;
- the operating-system Python should be upgraded or replaced.

Exact-head GitHub CI and the post-merge live wrapper/Doctor/service readback remain required before T025 can be treated as closed.
