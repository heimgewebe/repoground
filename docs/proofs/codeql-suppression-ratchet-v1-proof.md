# Lenskit CodeQL suppression ratchet v1 proof

## Trigger

PRs #952 and #953 closed the observed Lenskit code-scanning findings. The
resulting `main` tree intentionally retained 30 inline
`lgtm[py/path-injection]` comments at filesystem sinks whose project-specific
validation barriers are not modeled by CodeQL.

A clean SARIF result alone would not reveal a future bare suppression, a moved
suppression attached to a different sink, or an inventory entry that cited no
real regression test. This slice adds a fail-closed review surface for those
comments.

## Ratchet design

`config/codeql-path-suppressions.v1.json` groups the 30 sites into 12 authority
and validation boundaries. Every boundary records:

- expected occurrence count;
- exact file set;
- exact source statements and enclosing Python scopes, independent of line
  numbers;
- authority rationale;
- validation rationale;
- concrete pytest node IDs.

`scripts/ci/check_codeql_suppressions.py`:

- tokenizes every tracked Python source file, `.pyi`/`.pyw` file, and Python-shebang
  script plus equivalent non-excluded local source, considering only actual comment tokens;
- broadly detects spacing, case, and multi-rule variants that could be
  interpreted as path-injection suppressions, then rejects every noncanonical
  marker form, bare suppression, and unknown boundary ID;
- rejects count, file, scope, or exact-statement drift;
- rejects comment-only suppressions that are not inline with a sink;
- rejects missing rationale, invalid inventory structure, and missing test
  files or test functions;
- fails closed when a source containing a suppression cannot be tokenized.

The CodeQL workflow runs the ratchet before CodeQL initialization. The existing
raw-SARIF clean gate remains mandatory after analysis.

## Runtime scope

The eight existing Python runtime modules changed only by suppression-comment
annotation. AST comparison against base
`f0a652bd9ad9a1e155ffb69e7c27fdbb826aca1b` was identical for all eight files.
The new executable behavior is confined to the standard-library-only CI
checker and its tests. Most added lines are declarative inventory and negative
tests rather than runtime product logic.

## Local validation

- suppression inventory: 30 sites across 12 boundaries, pass;
- ratchet unit and negative tests: 20 passed;
- 29 unique inventoried pytest node IDs: 42 parametrized cases passed;
- focused and adjacent security/API suite: 157 passed;
- default Ruff on new Python files: passed;
- repository `ruff-ci.toml` ratchet: passed;
- JSON parsing, workflow YAML parsing, Python byte compilation, and
  `git diff --check`: passed;
- planning-registration ratchet: zero findings and zero control errors;
- runtime-module AST comparison: eight of eight unchanged;
- direct runtime proofs confirm internal Prescan directory symlinks are skipped
  and read-only SQLite access uses `mode=ro&immutable=1`.

## Required live proof

Local validation cannot establish the behavior of GitHub's current CodeQL
runner. The pull request must show:

1. `Validate CodeQL suppression inventory` succeeds before analysis;
2. ordinary CodeQL analysis succeeds;
3. `Require clean raw CodeQL SARIF` reports no results;
4. the remaining repository checks are green.

After merge, the `main` CodeQL analysis must remain at zero current results.

## Non-claims

This proof does not establish that every suppression is forever necessary, that
the referenced tests are sufficient, that upstream validation cannot regress,
that all filesystem races are eliminated, that CodeQL detects every
vulnerability, or that green CI alone proves runtime correctness or merge
readiness.
