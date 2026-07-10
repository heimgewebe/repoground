# rLens Home Preset Startup Policy v1 Self-Review

PR: pending
Reviewed implementation head: `1f7e79c99a04c04a13a6f9868a5b18742da42a3e`
Base: `292b9a7d22630e31dc2203be294f20700f39a629`
Reviewed implementation diff SHA-256: `0db2df960fb955326cb66183b56ec20e8171dec59336efeef090c11e63f2ab19`
Reviewed implementation diff bytes: `24746`
Source: Bureau live-register event `33`.

## Verdict

**PASS**, conditional on an unchanged live PR diff and green GitHub CI.

## Reviewed files

- `README.md`
- `docs/adr/001-secure-fs-navigation.md`
- `docs/proofs/rlens-home-preset-startup-policy-v1-proof.md`
- `docs/service-api.md`
- `merger/lenskit/adapters/filesystem.py`
- `merger/lenskit/adapters/security.py`
- `merger/lenskit/service/app.py`
- `tests/test_security_root_policy.py`

Coverage: every implementation-diff file reviewed.

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
- A failed reinitialization revokes the previous hub, Home and root grants before leaving only the new explicit Hub root.
- `RLENS_FS_TOKEN_SECRET` remains unrelated to Bearer request authorization.

## Regression and integration risk

- Hub/Merges behavior and unauthenticated/non-loopback policy are unchanged.
- `system` remains a compatibility alias when Home is available.
- The new `503` distinguishes a configured but temporarily unavailable preset from an unknown root (`400`) and unauthorized sensitive access (`403`).
- Webmaschine export omits unavailable Home instead of inventing or recomputing it.
- Atlas explicit absolute-root operation remains available in authenticated root-only mode.

## Validation

- Focused and adjacent policy/service/Atlas suite: `51 passed`.
- Production-file Ruff default rules: passed.
- Existing repo-wide Ruff ratchet on the legacy root-policy test: passed.
- Python byte-compilation: passed.
- Planning registration ratchet: zero findings and zero control errors.
- `git diff --check`: passed.

The existing `test_create_atlas_system_root` performs a real scan of the operator Home directory and is intentionally not used as a bounded local proof. GitHub `pytest-full` remains the authoritative full-suite gate.

## Independent review

Gemini through Antigravity CLI reviewed only the immutable diff packet, without repository or tool access. Verdict: **PASS**, no findings.

A separate Codex attempt ended at the quota boundary before producing any review and is not counted as evidence.

## Residual limits

- Local tests exercise POSIX root semantics; GitHub CI supplies the broader suite.
- The review does not establish deployment state, every platform-specific Home lookup behavior, absence of unrelated defects, or merge authorization by itself.
