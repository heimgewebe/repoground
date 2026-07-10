# rLens Home Preset Startup Policy v1 Self-Review

PR: #951
Reviewed code head: `217e192e9ee6fe4a0c100fa9957864bd3723ccd5`
Base: `292b9a7d22630e31dc2203be294f20700f39a629`
Reviewed code packet: unified diff with 40 context lines, excluding review-evidence files
Reviewed packet SHA-256: `da4213a8c0d78e5bf10af2a301e01a8c2d1a033b4885bbb610ccee7791c36e99`
Reviewed packet bytes: `51646`
Source: Bureau live-register event `33`.

## Verdict

**PASS**, conditional on an unchanged live PR code diff and green GitHub CI.

## Reviewed files

- `README.md`
- `docs/adr/001-secure-fs-navigation.md`
- `docs/proofs/rlens-home-preset-startup-policy-v1-proof.md`
- `docs/service-api.md`
- `merger/lenskit/adapters/filesystem.py`
- `merger/lenskit/adapters/security.py`
- `merger/lenskit/service/app.py`
- `tests/test_security_root_policy.py`

Coverage: every code/proof file in the reviewed packet.

## Correctness

- The service resolves Home once during authenticated loopback startup and stores the canonical path in `home_preset_root`.
- Root discovery, direct `system` resolution and Webmaschine export consume the same stored value; they do not recompute `Path.home()`.
- A missing Home preset is observable: discovery omits it, stale direct requests return `503`, and startup logs root-only degradation.
- Successful normal startup retains the prior Home-plus-root behavior.

## Security

- Root-only mode is not an authorization expansion. The filesystem root was already granted only after the existing loopback-plus-Bearer gate; omitting the Home alias removes convenience state from that already broader capability.
- `home_preset_root` cannot be activated until the same canonical path is in the central allowlist.
- Home resolution or registration failure clears the candidate before capability activation, preventing a stale or unregistered alias.
- Core root-registration failure raises explicitly while sensitive access stays disabled.
- `init_service` clears roots and calls `set_sensitive_fs_access(False)` before any new root registration. A failed reinitialization therefore revokes the previous hub, Home and root grants before leaving only the new explicit Hub root.
- `RLENS_FS_TOKEN_SECRET` remains unrelated to Bearer request authorization.

## Regression and integration risk

- Hub/Merges behavior and unauthenticated/non-loopback policy are unchanged.
- `system` remains a compatibility alias when Home is available.
- The new `503` distinguishes a configured but unavailable preset from an unknown root (`400`) and unauthorized sensitive access (`403`).
- Webmaschine export omits unavailable Home instead of inventing or recomputing it.
- Atlas explicit absolute-root operation remains available in authenticated root-only mode.
- I/O or runtime failure while validating the optional cached Home preserves explicit Hub/Merges roots.

## Findings and triage

1. GitHub Code Quality reported an empty optional exception handler. Addressed by an explanatory comment and explicit return of existing roots.
2. Independent review found that cached-Home I/O errors could escape after exception narrowing. Addressed by restoring `(SecurityViolationError, OSError, RuntimeError)` and adding a regression test.
3. A later standard-context review claimed stale sensitive state after failed reinitialization. This was a false positive caused by the three-line diff context omitting the existing reset immediately above the hunk. The actual code and dedicated failed-reinitialization test prove revocation. The review was repeated with 40 context lines and returned PASS.
4. A Codex attempt stopped at its usage limit before producing output and is not counted as evidence.

## Validation

- Focused and adjacent policy/service/Atlas suite: `52 passed`.
- Focused root-policy suite: `25 passed`.
- Production-file Ruff default rules: passed.
- Existing repo-wide Ruff ratchet on the legacy root-policy test: passed.
- Python byte-compilation: passed.
- Planning registration ratchet: zero findings and zero control errors.
- `git diff --check`: passed.

The existing `test_create_atlas_system_root` performs a real scan of the operator Home directory and is intentionally not used as a bounded local proof. GitHub `pytest-full` remains the authoritative full-suite gate.

## Independent review

Gemini through Antigravity CLI reviewed the immutable 40-context-line packet without repository or tool access. Verdict: **PASS**, no findings.

## Residual limits

- Local tests exercise POSIX root semantics; GitHub CI supplies the broader suite.
- The review does not establish deployment state, every platform-specific Home lookup behavior, absence of unrelated defects, or merge authorization by itself.
