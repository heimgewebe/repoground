# RepoGround Agent Utility T025 proof

Task: `REPOGROUND-AGENT-UTILITY-V1-T025`

Base commit: `6baca4b5751143c6493d3df1b5c0d4df64c141f4`

Observed on: 2026-08-08

## Decision gate

T025 had to distinguish two competing explanations for the remaining Heim-PC Doctor degradation after T024:

1. **Doctor-contract hypothesis:** CPython 3.10.12 is supported for the canonical RepoGround host contract and Doctor incorrectly treats the Python 3.12 CI/release baseline as a hard host requirement.
2. **Host-runtime hypothesis:** Python 3.12 is intentionally part of the canonical readiness contract, while Python >=3.10 only supports narrower core paths; the Heim-PC therefore needs a separate runtime migration if full readiness is desired.

Fresh host readback established CPython 3.10.12 and no executable `python3.12` in `PATH`. The global RepoGround wrapper remains byte-identical to `scripts/ops/repoground-cli-wrapper` (`sha256:6f12e8c0bb598f0d91c83139a7e9bfb3e072af6b43e29a0da9f16d56892a7e16`), and `repoground.service` is active/running with zero restarts.

The decisive product authority is `docs/GETTING_STARTED.md`, not the internal `CORE_PYTHON_MINIMUM` constant in isolation. The repository architecture marks `docs/GETTING_STARTED.md` as normative for product boundaries. That contract states that:

- CPython 3.12 is the reproduced CI and release-candidate baseline;
- another interpreter from Python 3.10 may run individual core paths;
- `repoground doctor` intentionally reports such an interpreter as `degraded` rather than silently treating it as release-equivalent.

**Decision:** the Host-runtime hypothesis is currently supported. The existing Doctor behavior is consistent with the normative product contract. T025 therefore must not weaken the required Python check merely to make the Heim-PC Doctor green.

## Rejected RepoGround-side candidate fix

An initial candidate patch on commit `512594c38a39c02ae9954c87c2c839a7a008b609` changed a supported non-3.12 interpreter from required `degraded` to `available` while retaining a `does_not_establish: [ci_release_equivalence]` marker.

The candidate was technically well-tested:

- focused Doctor tests passed;
- Ruff passed;
- the release contract passed;
- the exact candidate head passed all GitHub CI, including `pytest-full`, browser tests, release-candidate, CodeQL and contract/security gates.

Those green tests did **not** prove the semantic change was correct. Codex review on the exact head identified the missing contract dimension: `docs/GETTING_STARTED.md` still promises `degraded`, and making the required Python check `available` can let `doctor --strict` succeed on a runtime that the onboarding contract does not treat as reproduced readiness.

That P2 finding was upheld. The candidate Doctor/test changes were reverted instead of broadening the normative support claim without evidence. The final T025 RepoGround diff is evidence-only; it does not change Doctor, launcher, CI, release gates, service code, locks or runtime requirements.

## Host follow-up registration

T025 is not allowed to replace the OS-managed system Python. The existing wrapper already provides the correct extension point:

```text
REPOGROUND_PYTHON=${REPOGROUND_PYTHON:-python3}
```

The bounded follow-up is therefore to provision a dedicated, rollback-capable CPython 3.12 runtime and bind CLI/service execution through `REPOGROUND_PYTHON`, while leaving `/usr/bin/python3` and system-wide Python defaults untouched.

Canonical Bureau intake was used instead of writing Registry/Queue state by hand:

- idempotency key: `repoground-t025-python312-followup`
- event: `4635`
- candidate: `candidate-eb1aed44105a6a9ad2f9fbaf`
- source binding: this T025 task digest `c51ead7962ae2f96d7eaffc20248d1847461966104dc7093b8a6a2a72ae0fe75`
- candidate assessment: `promote`
- target identifier checked: `REPOGROUND-AGENT-UTILITY-V1-T026`

The intake result explicitly does **not** establish Registry task truth, Queue truth, claim authority or dispatch authority. Promotion to a canonical Registry task is currently fail-closed because the installed Bureau controller is still source-bound to `88c404515b8d699e9518ce77778bbd6f88b63b9c`, while the freshly cloned Bureau Registry is on `764348f8cf79b0e45877c3fc993bceed26064453`; the task publisher reports `release-registry-identity-mismatch` / stale runtime. T025 does not bypass that controller invariant with a manual Registry PR.

## Regression and non-regression evidence

The final branch restores `merger/repoground/core/doctor.py` and `merger/repoground/tests/test_doctor.py` byte-for-byte to the T025 base revision. Therefore:

- Python 3.10.12 remains a non-baseline `degraded` required Doctor check;
- Python below the declared core minimum remains blocked;
- Python 3.12 remains the reproduced CI/release baseline;
- the canonical wrapper contract and T024 behavior are unchanged;
- no Host-Python installation or service mutation is performed by T025.

## Nonclaims

This proof does not establish that:

- CPython 3.10.12 is defective, unsafe or incapable of running useful RepoGround core paths;
- every RepoGround feature fails outside Python 3.12;
- the OS-managed system Python should be replaced;
- the Bureau intake candidate is already a Registry task or queue entry;
- `REPOGROUND-AGENT-UTILITY-V1-T026` is claimable before the Bureau controller/Registry identity mismatch is resolved;
- optional Rust/Bash adapters are relevant to the Python-runtime decision.

## Closeout boundary

The RepoGround product decision is resolved: keep the documented Doctor semantics and do not ship the rejected readiness broadening. The necessary Host mutation is registered in canonical Bureau intake and assessed for promotion, but canonical task publication remains administratively blocked by the stale Bureau controller. This proof therefore records the completed T025 product investigation without claiming that the future Host migration has already occurred or that Bureau has already published T026 as task truth.
