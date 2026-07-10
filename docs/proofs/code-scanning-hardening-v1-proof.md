# Lenskit Code-Scanning Hardening v1 Proof

## Scope

This slice addresses the open GitHub code-scanning surface observed on `main` after PR #951.

Observed before implementation:

- 38 open alert identities in the GitHub API;
- 34 `py/path-injection` identities;
- 2 `py/stack-trace-exposure` identities;
- 2 `actions/missing-workflow-permissions` identities;
- the latest Python CodeQL SARIF contained 28 active findings: 26 path-injection flows and 2 stack-trace-exposure flows. The difference was historical alert identity retention, not 38 simultaneously active Python flows.

## Security decisions

### API paths

Request-controlled paths pass through one root-bounded resolver before filesystem use. The resolver rejects:

- absolute paths;
- NUL bytes and backslashes;
- empty, dot, and parent segments;
- unnormalized POSIX syntax;
- canonical paths escaping the configured root, including symlink escapes.

The service applies the boundary to repository prescan roots, query SQLite artifacts, graph indexes, embedding policies, and federation indexes.

### Federation bundles

The service API no longer treats paths stored in a federation index as unrestricted local filesystem authority. In API mode, each bundle must resolve beneath the federation-index directory. Rejected paths receive the explicit runtime status `bundle_path_rejected` and are not opened.

The CLI retains explicit local-operator behavior: an operator may query an existing local bundle directory or `.index.sqlite` file outside the federation directory. This is a separate trust boundary and is not exposed through the service endpoint.

SQLite query paths use read-only mode. Federation fingerprint reads additionally use SQLite `immutable=1`.

### Error disclosure

Raw exception strings are no longer emitted by query and federation API paths or by per-bundle federation diagnostics. Model initialization, semantic encoding, SQLite, and federation failures retain technical detail in server logs while returning stable generic messages to clients.

### Workflow token authority

`.github/workflows/ai-context-guard.yml` now declares top-level `contents: read` permissions instead of inheriting broader default token authority.

### CodeQL annotations

`lgtm[py/path-injection]` comments are used only at individual filesystem sinks after a concrete validation boundary. They are not substitutes for validation. Relevant boundaries are covered by traversal, malformed-path, symlink-escape, regular-file, API-confinement, and error-redaction tests.

## Local validation

The final focused and adjacent suite includes:

- path-security and symlink-escape tests;
- query and federation API tests;
- federation CLI, contract, session, and deterministic tests;
- policy-loader tests;
- service and artifact security tests;
- root-policy and Atlas tests;
- graph-loader tests;
- semantic retrieval and evaluation tests;
- merge/prescan tests.

The authoritative proof that CodeQL findings are closed remains the GitHub PR analysis and the subsequent `main` analysis. Local tests cannot reproduce GitHub's complete CodeQL database.

## Non-claims

This proof does not establish that every filesystem operation in Lenskit is safe, that all future CodeQL versions will model the custom barriers identically, that trusted local CLI operators are sandboxed, that logs contain no sensitive information, or that green static analysis proves runtime correctness or merge readiness.
