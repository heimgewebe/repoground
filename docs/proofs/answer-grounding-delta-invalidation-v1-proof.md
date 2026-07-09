# RepoBrief Answer Grounding Delta Invalidation v1 Proof

Status: review_ready
Initiative: `REPOBRIEF-FRONTDOOR-GROUNDING-V1`
Task: `RBGV-V1-T008`

## Result

This slice adds a read-only delta/freshness invalidation helper:

- `merger/lenskit/core/answer_grounding_delta.py`
- tests in `merger/lenskit/tests/test_answer_grounding_delta.py`

The helper checks an old Answer Grounding declaration against a newer explicit bundle manifest and optional citation map.

## Status model

Old citations/ranges are classified as:

- `valid`
- `drifted`
- `missing`
- `not_comparable`

## Read-only boundary

The helper reads explicitly supplied existing files only. It does not create snapshots, refresh bundles, fetch Git state, apply patches, run shells, create PRs, or normalize freshness into success.

## Freshness behavior

The old declaration's `snapshot_ref.freshness_status` is carried through as `old_snapshot_freshness_status`. The newer snapshot's freshness status is read from the existing manifest status surface and remains visible as reported.

## Validation

```bash
git diff --check
python -m pytest merger/lenskit/tests/test_answer_grounding_delta.py -q
python -m pytest merger/lenskit/tests/test_answer_grounding_verifier.py -q
python -m pytest merger/lenskit/tests/test_range_resolver.py -q
python -m ruff check merger/lenskit/core/answer_grounding_delta.py merger/lenskit/tests/test_answer_grounding_delta.py
```

## Does not establish

This proof does not establish semantic answer correctness, future citation stability across all commits,
new snapshot freshness, runtime correctness outside tested paths, full test sufficiency, review completeness,
merge readiness, security correctness or regression absence.
