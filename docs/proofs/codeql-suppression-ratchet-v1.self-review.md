# CodeQL suppression ratchet v1 — self-review

## Binding

- base: `f0a652bd9ad9a1e155ffb69e7c27fdbb826aca1b`
- reviewed implementation head: `b85cc35445d72f6b90f896f509488a4e69f734a6`
- immutable review packet SHA-256:
  `12a5b090cbba63b99d7420e3194a9b74cc9a8ecb9226fa4bf9520e18ce20643e`
- packet bytes: `100555`
- packet context: 20 unchanged lines

The packet contains the complete implementation diff and predates this
self-review and the external-review evidence files.

## Reviewed files

- `.github/workflows/codeql.yml`
- `config/codeql-path-suppressions.v1.json`
- `docs/proofs/codeql-suppression-ratchet-v1-proof.md`
- `docs/testing/codeql-suppression-ratchet.md`
- eight existing runtime modules carrying the 30 suppression comments
- three existing runtime-security test modules
- `merger/lenskit/tests/test_codeql_suppression_ratchet.py`
- `scripts/ci/check_codeql_suppressions.py`

## Review axes

### Correctness

The checker inventories 30 current `py/path-injection` suppressions across 12
explicit trust boundaries. It compares observed comments against exact file,
Python scope, and source-statement tuples while intentionally ignoring line
numbers. This permits harmless line movement but rejects semantic site drift.

The eight changed product modules were AST-compared with the base and remained
identical. Product behavior changes are limited to added tests; the runtime
modules changed only in suppression-comment placement and boundary labels.

### Bypass resistance

The implementation rejects:

- bare or unknown boundary annotations;
- alternate `codeql[...]` markers;
- spacing, case, and multi-rule marker variants;
- marker-like strings that are not Python comments;
- suppressions moved to another file, function/class scope, or statement;
- occurrence-count and file-set drift;
- source paths or test references escaping the repository;
- missing test files and missing pytest function/class nodes;
- tracked Python sources hidden beneath excluded cache/environment directories;
- unparseable suppression-bearing Python source.

The scanner covers tracked `.py`, `.pyi`, `.pyw`, and extensionless
Python-shebang sources, plus equivalent non-excluded local files. It does not
follow extensionless symlinks merely to inspect their shebang.

### Regression risk

The ratchet is isolated to CI and uses only the Python standard library. The
CodeQL workflow runs it before CodeQL initialization. Existing CodeQL analysis
and the raw-SARIF zero-result gate remain separate requirements afterward.

Directory walking prunes cache and environment directories before descending.
Git coverage then fails if a tracked Python source would have been hidden by
those exclusions.

### Tests

Local evidence on the reviewed implementation head:

- 20 ratchet unit and negative tests passed;
- 29 inventory-linked pytest node IDs produced 42 passing cases;
- 157 focused and adjacent security/API cases passed;
- direct tests prove internal Prescan directory symlinks are skipped;
- direct tests prove SQLite read-only paths use `mode=ro&immutable=1`;
- default Ruff passed on changed Python files;
- repository `ruff-ci.toml` passed;
- JSON, YAML, byte compilation, diff check, and planning-registration ratchet
  passed;
- eight of eight changed product modules were AST-identical to base.

### Security and integration

The ratchet does not make a suppression safe. It makes the decision explicit
and reviewable. Runtime validation, CodeQL execution, raw SARIF inspection, test
execution, and merge gates remain independent controls.

The workflow still uses CodeQL action v3 and the repository ruleset does not
currently require named status checks. Those are separate governance and
maintenance concerns, not concealed claims of this patch.

## Review history

1. An initial independent review of implementation head
   `bf0644965cc1aa25c07fb62cac80b47043b00166` returned FAIL. It identified a
   high-severity parser differential for suppression syntax variants and a
   low-severity Python-file discovery gap.
2. The scanner was broadened to detect spacing, case, multi-rule, and alternate
   marker forms while still requiring one canonical inventory form. `.pyi`,
   `.pyw`, and extensionless Python-shebang sources were added. Additional
   negative tests were added.
3. A new independent review of the corrected head and newly hashed packet
   returned PASS with no findings.

## Residual risks

- Test-node existence does not prove test sufficiency or that a test cannot be
  weakened later.
- Upstream validation could regress while a suppression remains at the same
  site; ordinary tests and CodeQL remain necessary.
- CodeQL can have false negatives unrelated to explicit suppressions.
- Edge-case extractor behavior for extensionless symlinks is not established by
  this ratchet.
- A green ratchet does not establish runtime correctness, absence of other
  vulnerabilities, merge readiness, or deployment state.

## Verdict

**PASS** — no known critical, high, or medium finding remains on the bound
implementation packet.
