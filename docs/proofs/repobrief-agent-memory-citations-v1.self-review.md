# RepoBrief Agent Memory Citations v1 Self-Review

PR: #944
Reviewed implementation head SHA: `53db3d3182fa09213c7881d85e94b3f50f1dcbd6`
Reviewed implementation diff SHA256: `76bb4d0a3077eb5d34de91fc13fad25723209415a8115f8155f9a0c72324f000`
Diff hash basis: `git diff origin/main...53db3d3182fa09213c7881d85e94b3f50f1dcbd6 -- . ':(exclude)docs/proofs/repobrief-agent-memory-citations-v1.self-review.md'`
Base: `origin/main` / `f0f4e460a923a479f861af3ac1a3552bca3570a5`

## Evidence boundary

This file is a review-evidence artifact. Its own evidence-only commit is not included in the implementation diff hash above, to avoid a self-referential hash loop. A final merge gate must still verify the live PR head, CI status and current PR diff.

## Scope reviewed

- `merger/lenskit/core/repobrief_memory.py`
- `merger/lenskit/tests/test_repobrief_memory.py`
- `docs/proofs/repobrief-agent-memory-citations-v1-proof.md`
- `docs/tasks/index.json`
- `docs/tasks/board.md`

## Review result

Status: pass with explicit boundaries.

The reviewed implementation satisfies the requested RPU-V1-T015 pattern and the follow-up hardening findings:

1. Memory record shape binds claim text, citation ids/ranges, snapshot stem/hash and freshness status.
2. Recall blocks changed, stale, missing, conflicting or unverifiable evidence before source-backed presentation.
3. Recall compares citation range identity, not only range content hash.
4. Recall validates memory record kind, version and non-empty claim text.
5. Recall handles malformed recorded citation ranges fail-closed instead of raising.
6. Projection import fails closed on unresolved or malformed projection items.
7. Projection import preserves `repo_id` and includes it in range identity when present.
8. Generic `sha256` is accepted as a range hash only with `hash_basis=range_content`.
9. Memory remains explicitly non-authoritative and never becomes source truth without verified citations.

## Findings checked

- Range identity rejects missing file paths, invalid byte spans, bool bytes and missing content hashes.
- Artifact-axis byte aliases are accepted when primary byte aliases are `None`.
- Projection import preserves resolved citation identity and blocks unresolved citations.
- Direct projection helper rejects unresolved projection items.
- Changed citation hashes, changed snapshot hashes, missing citations and missing freshness all produce `unusable` recall results.
- Same-hash range moves across file path, byte range or `repo_id` produce `unusable` recall results.
- Projection top-level `repo_id` mismatches produce `unusable` recall results, while matching top-level `repo_id` remains usable.
- Mapping-key and inner `citation_id` conflicts produce `unusable` recall results.
- Malformed records with missing recorded `source_range` produce `unusable` instead of a `KeyError`.
- The implementation does not add persistence, CLI, MCP, scheduler, background refresh or repository mutation.

## Verification used

- `python3 -m pytest merger/lenskit/tests/test_repobrief_memory.py -q` → 20 passed
- `python3 -m pytest merger/lenskit/tests/test_repobrief_memory.py merger/lenskit/tests/test_repobrief_source_citation_projection.py merger/lenskit/tests/test_repobrief_resolved_evidence_query.py -q` → 49 passed
- `python3 -m ruff check merger/lenskit/core/repobrief_memory.py merger/lenskit/tests/test_repobrief_memory.py` → passed
- `python3 -m compileall -q merger/lenskit/core/repobrief_memory.py` → passed
- `git diff --check` → passed
- `git diff --cached --check` before commit → passed

## Non-claims

This self-review does not establish claim truth, answer correctness, full repository understanding, review completeness, full-suite success, CI success, runtime behavior, persistence safety, or merge readiness by itself.
