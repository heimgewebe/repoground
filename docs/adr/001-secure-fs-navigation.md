# ADR 001: Secure Filesystem Navigation (Token-Based & Opt-In)

## Status
Accepted

## Context
The `rLens` service requires a mechanism to browse the filesystem (via Folder Picker) and scan directory structures (via Atlas).
Users expressed a need for **maximal functional comfort**, specifically the ability to browse the entire system starting from the root (`/`), rather than being restricted to the Hub directory.

However, standard implementation of absolute path browsing poses significant security risks and triggers static analysis warnings (e.g., CodeQL `py/path-injection`) because user-supplied strings are used to construct filesystem paths.

## Decision
We implement a "Secure Capability" architecture that balances functionality with strict governance and scanner compliance.

### 1. Loopback-Scoped Root Access
Browsing the system root (`/`) via API is enabled by default only when the service is bound to a loopback interface (`localhost` / `127.0.0.1`) and bearer authentication is configured (via the `token` parameter or `RLENS_TOKEN`). `RLENS_FS_TOKEN_SECRET` only signs filesystem navigation tokens; it does not activate bearer authentication and cannot authorize root browsing.

If the service is bound to any non-loopback interface, root browsing is automatically refused.

This ensures:
- Full operator capability in local deployments
- No accidental exposure of system root over the network

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
*   **Positive**: CodeQL "path injection" warnings are resolved by design. Filesystem access is limited to authorized roots (optionally including system root on loopback + auth).
*   **Negative**: "Quick and dirty" API calls using manual path strings are no longer possible; clients must obtain a valid token first (e.g., via `/api/fs/roots`).
*   **Maintenance**: Filesystem navigation tokens require `RLENS_FS_TOKEN_SECRET` (or `RLENS_TOKEN` fallback) to be managed securely. This signing secret is not bearer authorization.

## References
*   `merger/repoLens/service/fs_resolver.py`
*   `merger/repoLens/service/security.py`
