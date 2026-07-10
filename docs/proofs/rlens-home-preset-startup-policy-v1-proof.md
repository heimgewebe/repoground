# rLens Home Preset Startup Policy v1 Proof

## Scope

Source: Bureau live-register event `33`.

This slice makes the authenticated Home preset startup behavior explicit. It does not change the loopback-plus-auth authorization prerequisite introduced by PR #949.

## Decision

The authenticated filesystem root (`/`) is the core broad capability. The `system` alias for the service user's Home directory is optional convenience state.

At service initialization:

1. Hub and an explicit merges directory are registered normally.
2. In loopback-plus-auth mode, filesystem-root registration is mandatory.
3. Home is resolved once and registered as the optional `system` preset.
4. If Home resolution or registration fails, startup continues in logged root-only mode.
5. If filesystem-root initialization fails, startup raises an explicit error and sensitive access remains disabled.

The successful startup Home path is stored as `SecurityConfig.home_preset_root`. Runtime root discovery, direct `system` resolution and Webmaschine export use this stored path rather than recomputing `Path.home()`.

## Observable behavior

| Condition | Broad root | `system` discovery | Direct `system` request | Startup |
| --- | --- | --- | --- | --- |
| loopback + auth + Home available | enabled | present | succeeds | succeeds |
| loopback + auth + Home unavailable | enabled | omitted | `503 Service Unavailable` | succeeds with warning |
| loopback + auth + root grant failure | disabled | omitted | unavailable | fails closed with explicit `RuntimeError` |
| no auth or non-loopback | disabled | omitted | authorization denied | succeeds with Hub/Merges only |

## Security boundaries

- `home_preset_root` may be activated only after the same canonical path is present in `allowlist_roots`.
- A previously cached Home preset is cleared whenever sensitive access is disabled or the service is reinitialized without authorization.
- Home failure cannot leave a stale alias active.
- Root-only degradation does not widen authorization: it occurs only after loopback-plus-auth was already established and root itself was successfully allowlisted.
- Signed filesystem navigation secrets remain distinct from Bearer request authentication.

## Validation

Focused policy validation:

```bash
python3 -m pytest -q tests/test_security_root_policy.py
```

Result: `24 passed`.

Adjacent service and Atlas validation:

```bash
python3 -m pytest -q \
  tests/test_security_root_policy.py \
  merger/lenskit/tests/test_service_hardening.py \
  merger/lenskit/tests/test_service_artifact_security.py \
  merger/lenskit/tests/test_atlas_system_flow.py \
  merger/lenskit/tests/test_atlas_system.py::test_fs_roots_includes_system \
  merger/lenskit/tests/test_atlas_system.py::test_export_webmaschine_includes_roots \
  merger/lenskit/tests/test_service_startup_reconciliation.py
```

Result: `51 passed`, including the final HTTP `503` behavior and root-only Webmaschine export assertion.

Additional checks:

```bash
ruff check merger/lenskit/adapters/security.py \
  merger/lenskit/adapters/filesystem.py \
  merger/lenskit/service/app.py
ruff check --config ruff-ci.toml tests/test_security_root_policy.py
git diff --check
```

All passed.

## Non-claims

This proof does not establish cross-platform equivalence for every filesystem, full-suite sufficiency, runtime correctness outside the tested paths, absence of further filesystem-policy defects, deployment status, or merge readiness. GitHub CI and final PR review remain separate gates.
