# RepoBrief MCP Read-only Resources v1 Proof

Status: review_ready
Task: `RPU-V1-T020`

## Result

This slice adds concrete code-level RepoBrief MCP resource reads:

- `merger/lenskit/core/repobrief_mcp_resources.py`
- `merger/lenskit/tests/test_repobrief_mcp_resources.py`

Implemented resource templates:

- `repobrief://snapshot/{stem}/manifest`
- `repobrief://snapshot/{stem}/canonical`
- `repobrief://snapshot/{stem}/reading-pack`
- `repobrief://snapshot/{stem}/health`
- `repobrief://snapshot/{stem}/availability`
- `repobrief://snapshot/{stem}/artifact/{role}`

## Boundary

The adapter is read-only. It lists and reads existing bundle artifacts only. It does not create snapshots, refresh bundles, touch Git, run shells, inspect secrets, open PRs, apply patches, run reviews, run fixes or authorize merges.

Every resource read returns snapshot context for health, freshness and availability, or explains why that context is unavailable.

## Validation

```bash
git diff --check
python -m pytest merger/lenskit/tests/test_repobrief_mcp_resources.py -q
python -m pytest merger/lenskit/tests/test_repobrief_mcp_boundary_doc.py -q
python -m pytest merger/lenskit/tests/test_repobrief_mcp_frontdoor.py -q
python -m pytest merger/lenskit/tests/test_repobrief_mcp_snapshot_create.py -q
python -m ruff check merger/lenskit/core/repobrief_mcp_resources.py merger/lenskit/tests/test_repobrief_mcp_resources.py merger/lenskit/tests/test_repobrief_mcp_boundary_doc.py
```

## Does not establish

This proof does not establish MCP server availability, transport security, authentication correctness, runtime deployment, answer correctness, repository understanding, review completeness, merge readiness, security correctness, full test sufficiency or regression absence.
