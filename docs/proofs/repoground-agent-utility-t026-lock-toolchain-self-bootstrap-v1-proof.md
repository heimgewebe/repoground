# RepoGround Agent Utility T026 — Lock Toolchain Self-Bootstrap v1 Proof

## Scope

This proof covers the maintenance gap discovered after PR #1194: the canonical
lock wrapper could validate a pinned `pip`/`pip-tools` toolchain, but it could
not regenerate its own hashed tool lock when one of those direct pins changed.
The wrapper installed the checked-in hash-locked toolchain first, while the
full generator correctly requires the executing versions to match the new
input contract. That stopped generation before a replacement tool lock could
exist.

Base revision: `811449e9f7bc209808c32aa41c7efcb260124355`.

Bureau intake evidence: `candidate-1641c0a381f5bcade9eab9fc`, assessment
`promote`, with no duplicate candidate found.

## Final contract

The existing `scripts/release/compile_dependency_locks.sh` remains the only
supported lock-generation entry point.

### Steady state

When the exact direct `pip` and `pip-tools` pins in the input match the
checked-in tool lock, the wrapper keeps the previous behavior:

1. install `requirements/repoground-lock-tools.lock.txt` with
   `--require-hashes` inside the digest-pinned disposable container;
2. run the canonical full generator;
3. in `--check` mode, require every RepoGround dependency lock to reproduce.

### Direct tool-pin drift

When an exact direct `pip` or `pip-tools` input pin differs from the checked-in
tool lock, the transition is fully hash-chained:

1. install the *current* checked-in tool lock with `--require-hashes`;
2. verify that the executing compiler matches that old hash-bound toolchain;
3. use that compiler only to derive a candidate tool lock for the new exact
   input pins, without changing the checkout;
4. validate that the candidate binds exactly the requested direct pins;
5. install the candidate with `--require-hashes` into an isolated temporary
   package target;
6. with that new hash-bound toolchain, run the normal full generator for all
   four RepoGround locks;
7. install the final generated checked-in tool lock again with
   `--require-hashes` into a second isolated target;
8. disable user site-packages and require the final generator to pass
   `--check`.

No package installation falls back to raw `repoground-lock-tools.in`, and no
implicit `latest pip` path exists.

`--check` remains read-only: if the direct pins differ, it reports the tool-lock
drift and writes nothing instead of attempting a bootstrap.

Malformed, missing, or duplicate direct tool-lock pins fail closed. Bootstrap
also fails before compilation if the executing compiler does not match the
current checked-in hash lock, or if the derived candidate does not bind the new
requested direct pins.

## Focused tests

`pytest merger/repoground/tests/test_dependency_lock_toolchain.py -q`

Result: `14 passed`.

The focused cases prove, among other things:

- exact direct-pin agreement selects the hashed steady-state path;
- a `pip` or `pip-tools` direct-pin difference selects bootstrap mode;
- a missing or duplicate direct tool pin is rejected;
- the bootstrap compiler must match the current checked-in hash lock;
- candidate generation does not rewrite the checked-in old lock;
- a candidate with the wrong requested direct pins is rejected.

Together with `merger/repoground/tests/test_release_packaging.py`, the final
focused release suite reports `72 passed` (Grabowski task
`3f6e8ac797494f7187d5d0a7`, lifecycle receipt
`8d570a350218425b43c70678999a5533b210fc05e6ea091f80141a5d65954044`).

## Release and static validation

Grabowski job `grabowski-job-519acc670fdf` completed successfully with receipt
`70ff2285756ce5e5ad8c2e3b6980d0e0b2c53e6cbe2be9bee993778f0626ffe4`.
It ran the release contract, repository-wide Ruff, shell syntax validation, and
`git diff --check` in one fail-fast chain.

Observed results:

- release contract: `status=pass`, `findings=[]`, four core locks;
- Ruff: `All checks passed!`;
- shell syntax: success;
- diff whitespace validation: success.

## Real steady-state verification

Grabowski job `grabowski-job-186870a0db21` ran the canonical wrapper with
`--check` on the implementation worktree and completed successfully with
receipt
`8e3deb9af75a641f2c5c068f774f5f2852a1c7e5f8677cd39ea4a84d28c20f80`.

Observed environment and result:

- CPython `3.12.3`;
- `pip==26.1.2`;
- `pip-tools==7.6.0`;
- the toolchain was installed from the checked-in hashed tool lock;
- `All RepoGround dependency locks are reproducible.`

This proves that the new bootstrap branch did not weaken the ordinary
hash-bound path.

## Probe: old hash-bound compiler can derive the bridge lock

Before changing the implementation to the final design, Grabowski job
`grabowski-job-b0862bea8304` tested the key architectural premise in the same
digest-pinned container. The current checked-in hash lock installed
`pip==26.1.2` and `pip-tools==7.6.0`; that compiler then resolved a synthetic
new exact target of `pip==25.3` and emitted a hash lock binding:

- `pip-tools==7.6.0`;
- `pip==25.3`.

The job succeeded with receipt
`3ccac503858743ce1d234fd1e16ab9e7b68415193419ea6f70caa4ce019cabb0`.
This removed the need for an unhashed input bootstrap.

## Real fully hash-chained self-bootstrap verification

A separate disposable detached worktree was created from the same base. Only
for this proof, `requirements/repoground-lock-tools.in` was changed from
`pip==26.1.2` to the previously validated compatible `pip==25.3`; the shipped
RepoGround dependency contract was not changed.

Grabowski job `grabowski-job-16a217a436a5` then completed the final wrapper
successfully with receipt
`982ca13a72d66416e81b503c295f308db1ec47646fe2323b9683cf3da29328a2`.

The logs prove the full chain:

1. the current checked-in tool lock was installed with `--require-hashes`,
   yielding `pip==26.1.2` and `pip-tools==7.6.0`;
2. the bootstrap environment explicitly expected and observed that old
   hash-bound compiler;
3. it derived a candidate hash lock for exact `pip==25.3`;
4. that candidate was installed with `--require-hashes` into an isolated
   package target;
5. the candidate toolchain observed `pip==25.3` and `pip-tools==7.6.0`, then
   ran the complete generator;
6. only `requirements/repoground-lock-tools.lock.txt` changed in the synthetic
   scenario;
7. the final generated tool lock was installed again with `--require-hashes`;
8. the final environment again observed `pip==25.3` and `pip-tools==7.6.0`;
9. the final result was `All RepoGround dependency locks are reproducible.`

The candidate and final self-hosted locks were not byte-equivalent in their
transitive closure: the old compiler's candidate selected `wheel==0.48.0`,
while the new toolchain's final reproducible lock selected `wheel==0.47.0`.
That difference is useful evidence that the final reinstall and `--check` are
not redundant: the bridge lock is used only to reach the new compiler; the new
compiler must still produce and prove its own final state.

The disposable worktree and its dedicated path lease were removed after the
successful readback. No synthetic dependency change remains in the real branch.

## Boundaries

This proves that the canonical wrapper can move between reviewed exact direct
tool pins without an unhashed package-install step and can return to a final
self-hosted reproducible hash lock.

It does not prove that arbitrary future `pip`/`pip-tools` pairs are mutually
compatible. The current hash-bound compiler must still be able to resolve a
candidate for the requested exact target, and the target toolchain must pass
the complete final generation and self-check. Reproducibility also remains
bound to the pinned container, package-index content, revision, and supported
platform contract.
