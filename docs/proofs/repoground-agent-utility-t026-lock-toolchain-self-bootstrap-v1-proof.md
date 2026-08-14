# RepoGround Agent Utility T026 — Lock Toolchain Self-Bootstrap v1 Proof

## Scope

This proof covers the maintenance gap discovered after PR #1194: the canonical
lock wrapper could validate a pinned `pip`/`pip-tools` toolchain, but it could
not regenerate its own hashed tool lock when one of those direct pins changed.
The old hashed toolchain was installed first, so the generator correctly saw a
version mismatch against the new input and stopped before it could create the
replacement lock.

Base revision: `811449e9f7bc209808c32aa41c7efcb260124355`.

Bureau intake evidence: `candidate-1641c0a381f5bcade9eab9fc`, assessment
`promote`, no duplicate candidate found.

## Implemented contract

The existing `scripts/release/compile_dependency_locks.sh` remains the only
supported lock-generation entry point.

- Steady state: direct `pip` and `pip-tools` pins in the input match the hashed
  tool lock, so the wrapper installs only with `--require-hashes` from
  `requirements/repoground-lock-tools.lock.txt`.
- Intentional self-update: an exact direct pin differs, so the digest-pinned
  disposable container installs the exact input pins once and regenerates all
  four locks.
- Verification: after that bootstrap, the freshly generated tool lock is
  installed with `--require-hashes` into an isolated temporary package target.
  User site-packages are disabled for the follow-up generator process and the
  same generator must pass `--check`.
- Fail closed: malformed, missing, or duplicate direct tool-lock pins remain a
  contract error rather than becoming a bootstrap bypass.

No implicit `latest pip` path was introduced.

## Focused tests

`python3 -m pytest merger/repoground/tests/test_dependency_lock_toolchain.py -q`

Result: `11 passed`; together with `test_release_packaging.py`, `69 passed`.

The added cases prove:

- exact direct-pin agreement selects the hashed steady-state path;
- a `pip` or `pip-tools` direct-pin change selects the bootstrap path;
- a missing direct tool pin is rejected;
- an ambiguous duplicate direct pin is rejected.

Ruff on the changed Python/test files passed.

## Real steady-state verification

Grabowski task `9d427dd5ed8443dfae99e846` ran the canonical wrapper with
`--check` on the implementation worktree.

Observed result:

- CPython `3.12.3`;
- `pip==26.1.2`;
- `pip-tools==7.6.0`;
- toolchain installed from the hashed tool lock;
- `All RepoGround dependency locks are reproducible.`

The task terminalized successfully with lifecycle receipt
`82653f261a0e6fdfaba54f1d4d1d59f47bdbb5a66a6e42bead179993e3ba745d`.

## Real self-bootstrap verification

A separate disposable detached worktree was created from the same base. Only
for this proof, `requirements/repoground-lock-tools.in` was changed from
`pip==26.1.2` to the previously validated compatible `pip==25.3`; the shipped
RepoGround contract was not changed.

The first prototype exposed a real environmental assumption: the digest-pinned
Playwright image does not provide `ensurepip`, so a post-generation `venv`
could not be created. That attempt failed after successfully generating the
complete candidate tool lock. The implementation was corrected to use an
isolated temporary `--target` installation instead; no host package was added.

Grabowski job `grabowski-job-748e58b264d3` then completed successfully:

1. the wrapper selected the input bootstrap path;
2. exact `pip==25.3` and `pip-tools==7.6.0` were installed;
3. `requirements/repoground-lock-tools.lock.txt` was regenerated;
4. that fresh tool lock was installed with `--require-hashes` into the isolated
   verification target;
5. the follow-up process observed CPython `3.12.3`, `pip==25.3`, and
   `pip-tools==7.6.0` with user site-packages disabled;
6. the final result was `All RepoGround dependency locks are reproducible.`

Durable job finalization receipt:
`675faedea062bdfa66e0c15d96576a61c99c5686af6695c758c3087a85079003`.

## Boundaries

This proves the canonical wrapper can self-bootstrap a reviewed exact direct
pin change and immediately return to hash-bound verification. It does not prove
that an arbitrary future `pip`/`pip-tools` pair is mutually compatible; that
compatibility still has to be established for the proposed exact versions.
Reproducibility also remains bound to the pinned container, package index
content, revision, and supported platform contract.
