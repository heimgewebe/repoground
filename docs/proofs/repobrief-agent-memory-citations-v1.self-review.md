# RepoBrief Agent Memory Citations v1 Self-Review

PR: #944
Reviewed implementation head SHA: `cae7ca0ad20a8129ae573f1d8b21e8e8889e23a6`
Reviewed implementation diff SHA256: `f5632f21a7e698202d652ac75a86aea1bbadb25f3402bd483e2f7d0d2867d426`
Reviewed implementation diff bytes: `51736`
Diff hash basis: `git diff origin/main...cae7ca0ad20a8129ae573f1d8b21e8e8889e23a6 -- . ':(exclude)docs/proofs/repobrief-agent-memory-citations-v1.self-review.md'`
Base: `origin/main` / `f0f4e460a923a479f861af3ac1a3552bca3570a5`

## Evidence boundary

This file is a review-evidence artifact. Its own evidence-only commit is excluded from the implementation diff hash to avoid a self-referential hash loop. The implementation diff was exported independently, measured as 51,736 bytes and matched the SHA-256 above. Temporary measurement/export workflows were removed and are absent from the reviewed implementation file set.

A final merge gate must still verify the live PR head, mergeability, current CI results, comments and current PR diff.

## Scope reviewed

- `merger/lenskit/core/repobrief_memory.py`
- `merger/lenskit/tests/test_repobrief_memory.py`
- `merger/lenskit/tests/test_repobrief_memory_duplicate_ids.py`
- `docs/proofs/repobrief-agent-memory-citations-v1-proof.md`
- `docs/tasks/index.json`
- `docs/tasks/board.md`

## Review result

Status: pass with explicit boundaries.

The reviewed implementation satisfies the requested RPU-V1-T015 pattern and closes the duplicate-citation conflict found during review:

1. Memory records bind claim text, citation ids/ranges, snapshot stem/hash and freshness status.
2. Recall blocks changed, stale, missing, conflicting or unverifiable evidence before source-backed presentation.
3. Recall compares citation range identity, not only the range content hash.
4. Memory record kind, version and non-empty claim text are validated.
5. Malformed recorded citation ranges fail closed instead of raising.
6. Projection import fails closed on unresolved or malformed projection items.
7. Projection `repo_id` is preserved and included in range identity when present.
8. Generic `sha256` is accepted as a range hash only with `hash_basis=range_content`.
9. Duplicate citation ids are rejected when constructing a memory record.
10. Duplicate citation ids in current recall evidence make the result unusable.
11. Duplicate citation ids already present in a stored record make the result unusable.
12. Mapping-key and inner-`citation_id` conflicts remain fail closed.
13. Memory remains explicitly non-authoritative and never becomes source truth without verified citations.

## Findings checked

- Range identity rejects missing file paths, invalid byte spans, bool byte values and missing content hashes.
- Artifact-axis byte aliases are accepted when primary byte aliases are `None`.
- Changed citation hashes, changed snapshot hashes, missing citations and missing freshness produce `unusable` recall results.
- Same-hash moves across file path, byte range or `repo_id` produce `unusable` recall results.
- Projection top-level `repo_id` mismatches are blocked while matching ids remain usable.
- Repeated ids cannot be silently collapsed to the first observed evidence record.
- Conflict checks set the affected citation status to `conflict` and preserve the fail-closed presentation policy.
- The implementation does not add persistence, CLI, MCP, scheduler, background refresh or repository mutation.

## Verification used

- Isolated regression reproduction for the duplicate-id hardening: `4 passed`.
- Existing focused baseline before hardening: RepoBrief memory tests `20 passed`; memory plus citation projection/query tests `49 passed`.
- Ruff and compile checks passed on the prior reviewed implementation and are rerun by GitHub CI on the final PR head.
- The exported reviewed implementation diff matches SHA-256 `f5632f21a7e698202d652ac75a86aea1bbadb25f3402bd483e2f7d0d2867d426`.
- Final merge readiness remains conditional on all GitHub checks succeeding on the live evidence head.

## Non-claims

This self-review does not establish claim truth, answer correctness, full repository understanding, review completeness, runtime behavior, persistence safety, test sufficiency, regression absence or merge readiness by itself.
