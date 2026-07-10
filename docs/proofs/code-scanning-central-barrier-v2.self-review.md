# Lenskit Code-Scanning Central Barrier v2 Self-Review

PR: pending
Base: `2f75253bc77c4329d1aa0f2b71466197bae350f6`
Reviewed implementation head: `0ccb856d21533df1500a0e0a859c71815c622ef9`
Reviewed packet: complete diff with 12 context lines
Reviewed packet SHA-256: `8b20bfbb5a930eb7a7ae913b30097729acdcdcabbe8cf43a0a2eeceef40e6fb6`
Reviewed packet bytes: `21753`

## Verdict

**PASS**, conditional on an unchanged implementation diff, green GitHub CI, and a successful unfiltered raw-SARIF gate.

## Trigger and process correction

PR #952 passed pull-request CodeQL, but the post-merge `main` analysis reported six path-injection results. All six were confined to the older central allowlist implementation and one redundant caller check.

This follow-up fixes both the runtime structure and the proof process. Pull requests now fail when raw analyzer SARIF contains any result, rather than relying only on GitHub's pull-request presentation.

## Correctness and security

- Request-controlled full paths no longer reach `Path.resolve()` inside `SecurityConfig.validate_path`.
- The validator first selects the narrowest lexical allowlist root and derives a relative path without filesystem access.
- Exact-root requests return the already canonical registered object.
- Descendant requests pass through `resolve_secure_path`, which validates segments and performs post-canonicalization containment.
- A symlink escape from a narrow Hub does not fall back to a broader overlapping root.
- `validate_directory` centralizes the existing-directory contract for Hub and source roots.
- `_find_repos` no longer repeats an unreachable existence check after directory validation.
- Nonexistent descendants remain resolvable for callers that do not require a directory, preserving the previous general path contract.

## Raw SARIF gate

- Missing directory: fail closed.
- Missing SARIF files: fail closed.
- Invalid JSON: fail closed.
- Any SARIF result: fail with rule, path, and line.
- Empty result arrays: pass.

The gate was run against the actual six-result `main` SARIF from PR #952 and correctly exited 1 while listing all six findings.

## Validation

- focused and adjacent suite: `329 passed`;
- central path and least-authority tests: passed;
- raw-SARIF parser tests: passed;
- repository Ruff ratchet: passed;
- changed Python modules byte-compiled: passed;
- planning-registration ratchet: zero findings and zero control errors;
- `git diff --check`: passed.

## Independent review

Gemini through Antigravity CLI reviewed only the immutable diff packet without repository or tool access.

Verdict: **PASS**, no findings.

## Residual limits

- On a case-insensitive filesystem, differently cased textual paths may fail safe if the platform path library does not normalize casing identically. This can reject a valid path but does not authorize an invalid one.
- The raw SARIF gate must be proven in GitHub Actions; local tests cannot establish the exact action output layout.
- The review does not establish absence of unrelated vulnerabilities, elimination of every filesystem race, test sufficiency, deployment state, or merge readiness by itself.
