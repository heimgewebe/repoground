# Security-alert readback contract v1 -- proof

Finding: `candidate-52e48525291654cff4605a47`

## Scope

Complete audits could not distinguish "zero GitHub code-scanning alerts" from
"alerts API unavailable/unauthorized": a live endpoint read returned `404` while
the required CodeQL check on the same commit was green, and nothing in the
repository captured that ambiguity explicitly. This proof covers a deterministic
classifier, its machine-readable contract, a CI-produced summary artifact, and a
fail-closed exit contract for consumers. It does not prove that CodeQL's own
analysis is complete, that the live GitHub alerts API behaves as documented in
every case, or that every possible transport failure is enumerated.

## Implemented surface

- `merger/repoground/retrieval/security_alert_summary.py` -- deterministic
  classifier (`classify_security_alert_state`), no filesystem, network, or
  subprocess access.
- `merger/repoground/contracts/security-alert-summary.v1.schema.json` -- the
  closed-vocabulary contract for the summary object.
- `scripts/ci/emit_security_alert_summary.py` -- CLI wrapper: reads local raw
  CodeQL SARIF (reusing `scripts/ci/assert_codeql_sarif_clean.collect_results`)
  and an optional captured API-response file, classifies, prints and optionally
  writes the summary, and exits `0` only for `clean`.
- `.github/workflows/codeql.yml` -- emits and uploads
  `security-alert-summary.json` as a workflow artifact from the existing
  `analyze` job, using `if: always()` (guarded on the analyze step having
  produced SARIF output) so the artifact reflects reality even when the job
  fails.
- `docs/architecture/security-alert-readback-v1.md` -- contract documentation,
  including required permissions per evidence path.
- `merger/repoground/tests/test_security_alert_summary.py` -- classifier and
  schema-validation tests.
- `merger/repoground/tests/test_security_alert_summary_cli.py` -- CLI
  behavior and exit-code tests.

## Invariants

1. Repository-local SARIF evidence is authoritative for the current CodeQL analysis
   boundary when it resolves to a definitive state (`clean`/`alerts_present`); it
   needs no additional readback permission or network call.
2. A live API `404` is never classified as `clean` -- GitHub returns `404` for
   both "code scanning disabled" and "caller unauthorized," so it always
   resolves to `unavailable`.
3. Live API `401`/`403` resolves to `unauthorized`.
4. A live API `200` with zero reported open alerts is `clean` only when exhaustive
   pagination is explicitly proven; an unpaginated zero resolves to `unknown`. A
   positive count remains `alerts_present` even when pagination is incomplete.
5. Two definitive evidence sources that disagree resolve to `unknown`, not a
   silent pick of either side.
6. No evidence supplied resolves to `unknown`, never `clean`.
7. Only `clean` is a pass; `alerts_present`, `unavailable`, `unauthorized`, and
   `unknown` all exit non-zero from the CLI -- fail closed on unknown rather
   than treating missing endpoint data as clean.
8. Malformed evidence (wrong types, out-of-range counts, unsupported fields,
   inconsistent `available`/`alert_count` or `status_code`/`open_alert_count`
   pairing) is rejected with `SecurityAlertSummaryError` rather than silently
   coerced.
9. The CLI never performs the live HTTP call itself and never handles a
   credential; API evidence is supplied as a pre-captured JSON file, keeping the
   contract's own permission footprint at `contents: read` only.
10. The emitted summary validates against `security-alert-summary.v1.schema.json`
   for every tested state.

## Verification

Focused command:

```text
pytest -q \
  merger/repoground/tests/test_security_alert_summary.py \
  merger/repoground/tests/test_security_alert_summary_cli.py \
  merger/repoground/tests/test_codeql_sarif_gate.py \
  merger/repoground/tests/test_codeql_suppression_ratchet.py \
  merger/repoground/tests/test_github_main_ruleset.py \
  merger/repoground/tests/test_github_actions_node_runtime.py
```

Result: 69 passed, 0 failed.

Also run and green:

```text
python3 scripts/ci/check_codeql_suppressions.py
python3 scripts/ci/check_github_actions_pins.py
python3 scripts/ci/check_reusable_workflow_contracts.py
git diff --check
```

Repository-wide GitHub CI (including `codeql.yml` itself, `contracts-validate.yml`,
and the full test suite) is authoritative for the published change.

## What this does not establish

- That GitHub's live code-scanning alerts API will continue to return exactly
  these status codes for these conditions in the future.
- Severity, exploitability, or remediation priority of any alert reported by
  either evidence source.
- That CodeQL's Python analysis itself has no coverage gaps.
- Permission to create issues, patches, commits, pushes, or merges.
