# rLens Service Auth Hardening v1 Self-Review

PR: #948
Reviewed implementation head SHA: `1ca9f8116a23b8558bdeb18f5b4b37aaebd17489`
Reviewed implementation diff SHA256: `aa8d9668e980418b151f98a42f1bd4cdfe1b2f29f4ec403158a55aae6f00e142`
Reviewed implementation diff bytes: `19729`
Diff hash basis: `git diff --binary origin/main...1ca9f8116a23b8558bdeb18f5b4b37aaebd17489 -- .`
Base: `origin/main` / `a3d1fcae20419e00cedc883dd73f995611ee648b`

## Evidence boundary

This file records a critical review of the implementation diff above. It is committed separately and is therefore not part of the reviewed implementation hash. A final merge gate must still verify the live PR head, the live GitHub diff, mergeability, all CI checks, comments and reviews.

## Reviewed files

- `.gitignore`
- `docs/adr/001-secure-fs-navigation.md`
- `merger/lenskit/cli/rlens.py`
- `merger/lenskit/core/chunker.py`
- `merger/lenskit/core/merge.py`
- `merger/lenskit/core/redactor.py`
- `merger/lenskit/service/app.py`
- `merger/lenskit/service/auth.py`
- `merger/lenskit/tests/test_redactor_private_keys.py`
- `merger/lenskit/tests/test_rlens_server_security.py`
- `merger/lenskit/tests/test_service_auth_hardening.py`
- `tests/test_security_root_policy.py`

Coverage: all implementation-diff files reviewed.

## Verdict

**PASS for the reviewed implementation diff, with merge readiness conditional on live CI.**

## Findings and resolutions

### Correctness

- Confirmed that SHA-1/MD5 uses in the changed identifier paths are non-security identifiers and now declare `usedforsecurity=False` for FIPS-compatible runtimes.
- Found and fixed stale authorization state: repeated `init_service` calls retained an earlier root grant and previous hub roots.
- The service now rebuilds its allowlist from the current configuration and explicitly removes `/` when the loopback-plus-bearer condition is false.

### Security

- Confirmed that `RLENS_FS_TOKEN_SECRET` signs filesystem tokens but is not accepted by `verify_token`; it can no longer activate `/` browsing by itself.
- Bearer and query-token comparisons now use `hmac.compare_digest`.
- Query-token support remains for browser-native clients; Uvicorn access logging is disabled so request URLs cannot disclose those credentials.
- Found and fixed a false security claim in the draft: PGP private-key blocks were documented as covered but were not redacted.
- Private-key redaction now covers generic, RSA, EC, DSA, OpenSSH and PGP labels while requiring matching begin/end labels.

### Regression risk

- Allowlist reset is fail-closed during reconfiguration: stale roots are revoked rather than retained.
- Hub, merges and home roots are rebuilt after reset; behavior tests verify that current roots remain while prior roots disappear.
- Disabling the standard access log reduces HTTP request observability. This is safer than leaking URL credentials, but a redacting access-log replacement remains a separate improvement.

### Tests

- Focused security/redaction suites: `25 passed`.
- Broad service, API, artifact, context, diagnostics, trace, redaction and chunk suites: `234 passed, 1 skipped`.
- Combined test-isolation regression covering root policy, dump retrieval and Atlas lifecycle: `19 passed`.
- Ruff CI ratchet scope (`F401`, `F811`) passed on changed Python files.
- `git diff --check` passed.
- The local monolithic 3,579-test invocation was attempted twice and stalled reproducibly at 16% without an assertion failure. One process-global MagicMock contamination was fixed, but the monolith still requires the GitHub `pytest-full` gate for authoritative completion.

### Integration

- The branch was rebased onto current `origin/main` before review.
- The only rebase conflict was `.gitignore`; both the existing core-dump rules and the new `.grabowski/` exclusion were preserved.
- No Git mutation, snapshot refresh, PR creation, runtime deployment or merge authorization is performed by the changed service code.

## Non-claims

This self-review does not by itself establish complete security correctness, absence of all side channels, full-suite success, runtime deployment correctness, review completeness, regression absence or merge readiness. Those remain conditional on the live PR diff and GitHub checks.
