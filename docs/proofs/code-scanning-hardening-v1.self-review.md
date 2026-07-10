# Lenskit Code-Scanning Hardening v1 Self-Review

PR: #952
Base: `0cbd961bb0159f4c00773180b3fa53459a33d8b4`
Reviewed implementation head: `1991887446044cc7263f6b29a7bfd6ddd138d413`
Reviewed packet: complete changed-line diff with eight context lines per hunk
Reviewed packet SHA-256: `8a80de7097164d9c79828fdb6db4d969c3df6f38fdfbe40bd9d418ce1d75e278`
Reviewed packet bytes: `93205`

## Verdict

**PASS**, conditional on an unchanged implementation diff, green GitHub CI, and a clean PR CodeQL analysis.

## Initial live finding surface

- 38 open GitHub alert identities;
- 34 path-injection identities;
- 2 stack-trace-exposure identities;
- 2 missing-workflow-permissions identities;
- latest `main` Python SARIF: 28 active findings, consisting of 26 path flows and 2 exception-disclosure flows.

The alert-identity count and current SARIF finding count are deliberately separated. Historical alert identities are not represented as current code flows automatically.

## Reviewed files

Every implementation, contract, documentation, and regression-test file in the reviewed packet was covered. The principal runtime files were:

- `.github/workflows/ai-context-guard.yml`
- `merger/lenskit/adapters/security.py`
- `merger/lenskit/architecture/graph_index.py`
- `merger/lenskit/cli/policy_loader.py`
- `merger/lenskit/core/federation.py`
- `merger/lenskit/core/merge.py`
- `merger/lenskit/core/path_security.py`
- `merger/lenskit/retrieval/federation_query.py`
- `merger/lenskit/retrieval/query_core.py`
- `merger/lenskit/service/app.py`
- `merger/lenskit/service/runner.py`

## Correctness

- API paths are resolved beneath established roots and rejected on absolute, parent, dot, empty, backslash, colon, NUL, unnormalized, or symlink-escape syntax.
- API query artifacts, graph indexes, policies, federation indexes, and prescan repositories use the same root-bounded resolution contract.
- Federation index bundle paths are constrained beneath the federation directory in API mode.
- Explicit local CLI operation retains the ability to select existing external bundle directories or SQLite index files.
- Federation index creation uses exclusive file creation and cannot follow an existing dangling output symlink.
- The canonical federation-index path supplies the base for relative persisted bundle paths.

## Security

- The new resolver performs both lexical validation and a post-canonicalization `relative_to` check.
- Symlink escapes are tested for API repository and federation-index inputs.
- Query SQLite access is requested read-only; fingerprint reads use `mode=ro&immutable=1`.
- Raw exception messages, database details, model-loader failures, and local secret paths are absent from query and federation HTTP responses and runtime bundle-error diagnostics.
- Technical details remain in internal logs; this slice does not claim log redaction.
- Workflow token authority is explicitly reduced to `contents: read`.
- `lgtm[py/path-injection]` annotations are placed only on individual sinks after a concrete validation or explicit local-operator authority boundary. They are not used on unguarded service inputs.

## Compatibility and integration

- Existing local federation CLI behavior remains available through `allow_external_bundle_paths=True`.
- The service explicitly passes `False`, so the broader CLI authority is not inherited by the API.
- The new `bundle_path_rejected` state is registered in the CLI trace schema, documentation, API tests, and agent-session failure behavior.
- Existing successful Federation, query, graph, service, Atlas, prescan, and semantic-search flows remain covered.

## Validation

- Focused and adjacent local suite: **312 passed**.
- Repository Ruff ratchet: passed.
- Python byte compilation for changed runtime files: passed.
- Planning registration ratchet: zero findings and zero control errors.
- JSON contract parsing: passed.
- `git diff --check`: passed.

## Review findings and triage

- GitHub Code Quality reported one low-severity dead assignment after semantic encoding fallback. The assignment was removed; 64 adjacent query/semantic/API tests passed.
- No security or compatibility finding remained after the correction.

## Independent review

Gemini through Antigravity CLI reviewed the corrected immutable packet without repository or tool access.

Verdict: **PASS**, no findings.

The review specifically covered API traversal and symlink escapes, Federation API/CLI trust separation, CodeQL annotation placement, error disclosure, SQLite read-only semantics, and workflow token permissions.

## Residual limits

- Local tests do not reproduce GitHub's CodeQL database. PR and post-merge SARIF are separate mandatory evidence.
- Filesystem state can change between validation and use; the design reduces and tests this risk but cannot claim elimination of every OS-level race.
- Staleness fingerprint reads remain best-effort; a fingerprint read failure does not itself reject an otherwise queryable index.
- Green static analysis does not establish absence of unrelated vulnerabilities, runtime correctness, deployment state, or merge readiness by itself.
