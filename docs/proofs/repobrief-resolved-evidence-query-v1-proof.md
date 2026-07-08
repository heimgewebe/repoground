# RepoBrief resolved evidence query v1 proof

Status: implemented by the RPU-V1-T001 slice.

## Scope

The slice makes `repobrief query` a read-only, resolved evidence surface over an existing Brief Bundle manifest. It also enriches `query_existing_index(..., resolve_evidence=True)` so each resolved hit carries directly usable evidence fields:

- text excerpt and truncation flag,
- source/artifact path,
- source and artifact line ranges,
- range ref and range verification status,
- citation id and citation verification status,
- snapshot availability and freshness state.

The CLI defaults to resolved evidence and compact source projection. A raw bounded index result remains available through `--raw-index-result` for compatibility and debugging.

## Boundary

The query path reads only existing bundle artifacts. It does not create snapshots, refresh stale bundles, mutate Git, open PRs, apply patches, write brief artifacts, run tests, or inspect secrets.

## Validation

Targeted validation:

```bash
python3 -m pytest -q \
  merger/lenskit/tests/test_repobrief_resolved_evidence_query.py \
  merger/lenskit/tests/test_repobrief_source_citation_projection.py \
  merger/lenskit/tests/test_repobrief_access_boundary.py
```

Expected result: all tests pass.

## Non-claims

This proof does not establish semantic completeness, runtime correctness, test sufficiency, review completeness, agent quality improvement, stale-bundle validity, or merge readiness.
