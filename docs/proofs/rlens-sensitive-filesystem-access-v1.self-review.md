# rLens Sensitive Filesystem Access v1 Self-Review

PR: #949
Reviewed implementation head SHA: `a2bcb176b0f12865562f74c2cc3a627a622df80e`
Reviewed implementation diff SHA256: `c199feadc6d2dff693d659389bdfe7f7ea0353c7bccaecddcad3bb822071ba26`
Reviewed implementation diff bytes: `24015`
Diff hash basis: `git diff --binary origin/main...a2bcb176b0f12865562f74c2cc3a627a622df80e -- . ':(exclude)docs/proofs/rlens-sensitive-filesystem-access-v1.self-review.md' ':(exclude)docs/proofs/rlens-sensitive-filesystem-access-v1.external-review.json'`
Base: `origin/main` / `beeb2f14318577177b69d1699fe0aef8078c7fe7`
Source finding: Bureau live-register event `27`.

## Evidence boundary

This file records a critical review of the implementation diff above. It is committed separately and is not part of the reviewed implementation hash. The independent external review is stored in `docs/proofs/rlens-sensitive-filesystem-access-v1.external-review.json`. A final merge gate must still verify the live PR head and diff, mergeability, current CI, comments and reviews.

## Reviewed files

- `README.md`
- `docs/adr/001-secure-fs-navigation.md`
- `docs/service-api.md`
- `merger/lenskit/adapters/filesystem.py`
- `merger/lenskit/adapters/security.py`
- `merger/lenskit/cli/rlens.py`
- `merger/lenskit/service/app.py`
- `merger/lenskit/tests/test_atlas_system_flow.py`
- `tests/test_security_root_policy.py`

Coverage: all implementation-diff files reviewed.

## Verdict

**PASS for the reviewed implementation diff, conditional on the final live PR diff and GitHub CI.**

## Findings and resolutions

### Correctness

- Loopback is a transport boundary, not authorization: other local processes or users can connect to a loopback service.
- Hub and a configured merges directory remain ordinary, explicit operator roots.
- The broad `system` preset and filesystem root are granted only for loopback plus the bearer token actually enforced by `verify_token`.
- The broad capability has explicit state (`sensitive_fs_access`); an overlapping allowlist root cannot silently mint the `system` alias.
- Reinitialization resets both the allowlist and the sensitive capability before rebuilding current configuration.

### Security

- Found and closed an additional bypass beyond the original live-register finding: Atlas `root_kind=abs_path` previously returned arbitrary absolute paths without calling the central allowlist validator.
- Absolute Atlas paths now pass through `SecurityConfig.validate_path`; path denials propagate to the existing HTTP 403 handler.
- The central validator retains its two-stage boundary: lexical containment before resolution, then canonical containment after symlink resolution.
- `RLENS_FS_TOKEN_SECRET` remains only a navigation-token signing secret and cannot activate sensitive browsing.
- Non-loopback bindings do not receive the broad capability even when bearer authentication is configured.
- Explicit Hub or merges roots remain authoritative by design. An operator can still configure a broad Hub; this is an explicit configuration decision, not an implicit `system` capability.

### Regression risk

- Unauthenticated loopback use can still inspect the configured Hub and merges roots, preserving the low-friction local workflow.
- Authenticated loopback use retains Home and full-root operation.
- The standalone Atlas CLI remains an explicit local filesystem operation; the new restriction applies to the service/API boundary.
- The `system` omission is ordinary conditional behavior, so it cannot make Hub/Merges root enumeration fail.

### Tests and validation

- Focused policy and real API boundary suite: `19 passed`.
- Broad service/API/Atlas regression suite: `168 passed, 1 skipped`.
- Explicit proofs cover a denied symlink escape, an allowed internal symlink, early `..` rejection, unauthenticated `/api/fs/roots`, and unauthenticated Atlas Home denial.
- Ruff CI ratchet scope passed on every changed Python file.
- Changed Python files passed `py_compile`.
- `git diff --check` passed.
- The existing `test_create_atlas_system_root` performs a real scan of the operator Home directory and is unsuitable as a bounded local check; GitHub `pytest-full` remains the authoritative full-suite gate.

### Independent review

- Codex CLI `0.142.2`, model `gpt-5.5`, reasoning effort `xhigh`, reviewed an isolated immutable packet without tools or repository access.
- Reviewed implementation head: `a2bcb176b0f12865562f74c2cc3a627a622df80e`.
- Reviewed implementation diff SHA256: `c199feadc6d2dff693d659389bdfe7f7ea0353c7bccaecddcad3bb822071ba26`.
- Final verdict: **PASS** with no critical, high, medium or low finding.
- A low compatibility observation from an earlier review iteration about unusual Home-resolution failures remains conservatively tracked as Bureau event `33`; it was not repeated as a finding in the final review.
- The current platform code-quality comment was resolved by documenting why failure of the optional `system` root must not hide explicit Hub/Merges roots.
- Claude CLI was unavailable for review because the authenticated subscription session quota returned HTTP 429 before any review tokens were used; it is not counted as review evidence.

### Integration

- Documentation distinguishes explicit Hub/Merges roots, the broad `system` capability, service API rules and standalone CLI behavior.
- Existing service mapping tests explicitly enable and bypass auth only within their mapping-only fixture.
- No runtime restart, deployment, snapshot refresh or merge authorization is performed by this patch.

## Remaining observations

- The local repo-wide Ruff invocation can scan `.git` metadata when a remote ref name ends in `.py`, because `ruff-ci.toml` replaces the default exclusions. This is unrelated to the product change and is tracked separately.
- Credential-redacting access logging remains a separate Bureau candidate; this patch does not change the access-log decision from PR #948.

## Non-claims

This self-review does not establish complete local-host isolation, correctness of arbitrary operator-selected Hub/Merges roots, absence of all filesystem side channels, full-suite success, runtime deployment correctness, review completeness, regression absence or merge readiness by itself.
