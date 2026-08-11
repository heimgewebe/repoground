# RepoGround lock-generator compatibility proof

## Scope and revision

- Bureau task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T023`
- Bureau run: `BUR-RUN-20260811T004920Z-0690a97b3c`
- Reproduction baseline: `b733157e022ceb39a64d51417046450e5e02a6d8`
- Branch: `bureau/repoground-legacy-reconciliation-v1-t023/0690a97b3c`
- Product source and product dependency inputs: unchanged

The tests below used the repository's digest-pinned Playwright image:

`mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d`

The image reported CPython 3.12.3 and pip 26.2 before any package operation.

## Incompatible reproduction

An ephemeral container installed `pip-tools==7.6.0` with the image's pip 26.2
and invoked `python -m piptools compile --dry-run` against
`requirements/repoground-dev.in`.

Observed contract and result:

```text
Python=3.12.3 pip=26.2 pip-tools=7.6.0
compile exit=1
ImportError: cannot import name 'stdlib_pkgs' from
pip._internal.utils.compat
```

The traceback occurs while importing `piptools.sync`; pip-tools has not opened
or resolved the RepoGround dependency input at that point. This is an internal
API compatibility failure, not a dependency-resolution conflict and not
evidence that any RepoGround package is unsatisfiable.

The failing pip was implicit in the old contract: the compiler input pinned
only pip-tools, whose dependency range allowed the resolver to select a newer
pip. The checked-in tool lock happened to contain the earlier compatible pair
`pip==26.1.2` and `pip-tools==7.5.3`, but the input did not state a durable
three-part generator contract.

## Compatible counterexample

A separate fresh container used the same image and revision but installed
`pip==25.3` with `pip-tools==7.6.0`. Both inputs compiled successfully in
read-only dry-run mode:

```text
Python=3.12.3 pip=25.3 pip-tools=7.6.0
dev exit=0 browser exit=0
```

The incompatible reproduction and compatible counterexample are separate
container lifetimes; no package state was shared between them.

## Supported contract and command

There is one supported core lock-generator contract. Its machine-readable
version source is `requirements/repoground-lock-tools.in`:

- CPython 3.12.3;
- pip 25.3;
- pip-tools 7.6.0.

The only supported external commands are the write and read-only modes of the
same wrapper:

```bash
scripts/release/compile_dependency_locks.sh
scripts/release/compile_dependency_locks.sh --check
```

The release policy is the canonical prose contract. Getting-started,
contribution and CI surfaces delegate to the read-only wrapper command and to
the same machine-readable version source. No CI lock-generation step invokes
pip-tools directly or installs an implicit latest pip.

## Failure and publication behavior

`compile_dependency_locks.py` reports expected and observed CPython, pip and
pip-tools versions before copying inputs or invoking pip-tools. A real negative
run on the host observed CPython 3.10.12, pip 26.1.1 and missing pip-tools,
returned 2, and left the SHA-256 of all four checked-in locks unchanged.

Generation copies reviewed inputs and current locks into a temporary tree.
That preserves reviewed package selections unless a human changes an input,
while still refreshing hashes deterministically. Checked-in files are not
published until all four staged compilations succeed. Replacement files and
rollback copies are prepared on the target filesystem; a tested synthetic
failure during the second replacement restored the already replaced first
lock.

Positive and negative tests cover:

- acceptance of the exact supported three-version environment;
- a pip 26.2 mismatch with all expected/observed versions in the report;
- environment failure before any compiler call or lock rewrite;
- compilation failure after one staged output without a checked-in rewrite;
- publication only after all four staged outputs exist;
- rollback after a synthetic mid-publication failure.

## Reproducibility and dependency comparison

Two consecutive canonical generations were run: one write-mode generation
followed by `--check`. The first reported all locks already current after the
corrected staging contract; the second reported all locks reproducible. The
resulting reviewed surfaces are:

| Lock | Packages | SHA-256 | Baseline product versions |
| --- | ---: | --- | --- |
| runtime | 37 | `b9ebf3e71fbddbc39e7247fffcda2944208bcdae918383c8145dc873d8881b1b` | unchanged byte-for-byte |
| dev | 47 | `a02aaec2005dbcb3cf6a35bfdd758d076840a112032e4683ebd3d2091a632a5f` | unchanged byte-for-byte |
| browser | 19 | `56e71118a2362b17e0da56a25f07236e99884d13eecae4c3d0b9ce892112af88` | unchanged byte-for-byte |
| lock-tools | 8 | `b42407392eaf8421771aa5d200cd5a8a1ea68034a5998ece08acf589b9040b79` | intentionally changed tool-only closure |

The runtime, dev and browser files have no Git diff from the baseline; their
package/version sets and hashes are identical. The only dependency-version
changes are confined to the generator lock:

| Tool package | Baseline | Supported closure |
| --- | --- | --- |
| build | 1.5.1 (yanked) | 1.5.0 |
| packaging | 26.2 | 26.3 |
| pip-tools | 7.5.3 | 7.6.0 |
| pip | 26.1.2 | 25.3 |
| setuptools | 83.0.0 | 84.0.0 |

Click 8.4.2, pyproject-hooks 1.2.0 and wheel 0.47.0 are unchanged. These are
lock-generation tools, not RepoGround product dependencies.

Both the dev and browser locks installed with `--require-hashes` into separate
empty targets in the supported container; representative imports passed.

## Local validation and limits

Completed checks:

- focused lock/release tests: 64 passed;
- bounded lock/release/workflow-control regression: 93 passed;
- release contract scan: pass, zero findings;
- workflow control-plane inventory: 21 classified workflows, zero errors;
- repo-wide Ruff via `ruff-ci.toml`: pass;
- shell syntax, Python compilation and `git diff --check`: pass;
- frontend parity guard: pass (no JobRequest or UI change);
- dev and browser isolated `--require-hashes` installs: pass.

The full non-browser/non-live-doc suite was attempted. It reached 9% with no
reported failure, then stopped producing progress for several minutes and was
manually interrupted. It is therefore not claimed as passing. GitHub CI is
also not claimed here; it must be read directly after the branch is pushed.

This proof establishes the revision-bound lock-generator behavior and local
checks above. It does not establish vulnerability absence, future package-index
availability, cross-platform equivalence, product correctness, release
readiness, deployment permission or GitHub CI success.
