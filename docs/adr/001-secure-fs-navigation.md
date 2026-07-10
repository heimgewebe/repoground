# ADR 001: Secure Filesystem Navigation (Token-Based & Opt-In)

## Status
Accepted

## Context
The `rLens` service requires a mechanism to browse the filesystem (via Folder Picker) and scan directory structures (via Atlas).
Users expressed a need for **maximal functional comfort**, specifically the ability to browse the entire system starting from the root (`/`), rather than being restricted to the Hub directory.

However, standard implementation of absolute path browsing poses significant security risks and triggers static analysis warnings (e.g., CodeQL `py/path-injection`) because user-supplied strings are used to construct filesystem paths.

## Decision
We implement a "Secure Capability" architecture that balances functionality with strict governance and scanner compliance.

### 1. Loopback- and Auth-Scoped Sensitive Access
Browsing the service user's home directory (`system`) or the filesystem root (`/`) via API is enabled only when the service is bound to a loopback interface (`localhost` / `127.0.0.1`) **and** bearer authentication is configured (via the `token` parameter or `RLENS_TOKEN`). Loopback alone is not an authorization boundary because other local processes or users can connect to the service. `RLENS_FS_TOKEN_SECRET` only signs filesystem navigation tokens; it does not activate bearer authentication and cannot authorize sensitive filesystem browsing.

Without that combined condition, only the explicitly configured Hub and merges directory are allowlisted. Those operator-selected roots remain authoritative even if they are broad; they do not implicitly mint the separate `system` preset. Non-loopback bindings never receive the `system` or `/` capability, even when bearer authentication is present.

Within authenticated loopback mode, filesystem root (`/`) is the core broad capability and the `system` Home preset is optional convenience state. The service resolves Home once during startup and stores that canonical path. If Home resolution or allowlist registration fails, startup continues in a logged **root-only** mode: `/` remains authorized, `system` is omitted from root discovery, and stale direct `system` requests return `503`. If the core filesystem-root grant itself cannot be initialized, startup fails closed with an explicit error. Later requests never recompute Home, avoiding runtime drift from the startup authorization decision.

This ensures:
- Full operator capability in authenticated local deployments
- No unauthenticated exposure of the service user's home directory to other local clients
- No accidental exposure of sensitive filesystem roots over the network

### 2. Token-Based Navigation (The "Hard Cut")
To satisfy security scanners and prevent path traversal, the API no longer accepts raw path strings for navigation.
*   **Protocol**: The server issues opaque, HMAC-signed tokens representing paths.
*   **Client**: The client sends these tokens back to list directories or select targets.
*   **Verification**: The server verifies the signature and expiration (TTL) of the token, then re-validates the encoded path against the current security allowlist.

Legacy parameters (e.g., `?path=/abs/path`) have been removed.

### 3. TrustedPath Type Boundary
We introduced a `TrustedPath` dataclass in the backend.
*   `resolve_fs_path` returns a `TrustedPath` instance after validation.
*   Filesystem operations (`_list_dir`) expect a `TrustedPath`.
This creates a visible type boundary between "untrusted user input" and "safe filesystem operations", aiding both code review and static analysis.

## Consequences
*   **Positive**: CodeQL "path injection" warnings are resolved by design. Filesystem access is limited to authorized roots; broad `/` access requires loopback plus configured Bearer authentication, and `system` additionally requires a successfully resolved startup Home.
*   **Resilience**: An unusual or unavailable service-account Home degrades only the `system` convenience preset; authenticated root browsing and ordinary Hub/Merges operation remain available. Core root-grant failure remains fail-closed.
*   **Negative**: "Quick and dirty" API calls using manual path strings are no longer possible; clients must obtain a valid token first (e.g., via `/api/fs/roots`).
*   **Maintenance**: Filesystem navigation tokens require `RLENS_FS_TOKEN_SECRET` (or `RLENS_TOKEN` fallback) to be managed securely. This signing secret is not bearer authorization.

## References
*   `merger/lenskit/adapters/filesystem.py`
*   `merger/lenskit/adapters/security.py`
*   `merger/lenskit/service/app.py`
*   `merger/lenskit/service/auth.py`
