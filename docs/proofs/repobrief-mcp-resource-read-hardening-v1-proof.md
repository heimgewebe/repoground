# RepoBrief MCP Resource Read Hardening v1 Proof

Status: complete
Task: `TASK-REPOBRIEF-MCP-RESOURCE-READ-HARDENING-001`

## Result

This slice hardens the code-level RepoBrief MCP resource adapter after the read-only resources closeout.

Changed files:

- `merger/lenskit/core/repobrief_mcp_resources.py`
- `merger/lenskit/tests/test_repobrief_mcp_resources.py`
- `docs/tasks/index.json`
- `docs/tasks/board.md`

## Boundary fixes

The adapter now applies additional read-side guards before returning resource content:

- a file-valued `bundle_root` is accepted only when it is a bounded `*.bundle.manifest.json` with RepoLens bundle-manifest shape;
- arbitrary non-manifest files and fake manifest-shaped files are not exposed as manifest resources;
- artifact content is capped by `MAX_RESOURCE_BYTES` (`16 MiB`) by reading at most `MAX_RESOURCE_BYTES + 1` bytes;
- artifact `bytes` and `sha256` metadata are required and checked against the same bounded byte buffer that may be returned;
- missing or malformed integrity metadata returns `integrity_unavailable` without returning `content_text`;
- byte or hash drift returns `integrity_mismatch` without returning `content_text`;
- file-valued invalid bundle roots return `blocked` with an explicit reason instead of looking like a missing snapshot;
- relative path escapes and symlink escapes remain blocked before content read;
- `artifact/bundle_manifest` now returns a consistent `artifact_ref` shape.

## Validation

```bash
python3 -m pytest -q merger/lenskit/tests/test_repobrief_mcp_resources.py
python3 -m pytest -q \
  merger/lenskit/tests/test_repobrief_mcp_resources.py \
  merger/lenskit/tests/test_repobrief_mcp_boundary_doc.py \
  merger/lenskit/tests/test_repobrief_mcp_frontdoor.py \
  merger/lenskit/tests/test_repobrief_mcp_snapshot_create.py
ruff check \
  merger/lenskit/core/repobrief_mcp_resources.py \
  merger/lenskit/tests/test_repobrief_mcp_resources.py \
  merger/lenskit/tests/test_repobrief_mcp_boundary_doc.py
git diff --check
python3 -m json.tool docs/tasks/index.json >/dev/null
python3 -m scripts.docmeta.check_planning_registration \
  --baseline docs/tasks/planning-registration-baseline.json \
  --ratchet \
  --format json
```

## Does not establish

This hardening slice does not establish MCP protocol server availability, transport or authentication correctness, runtime deployment, artifact truth, repository understanding, review completeness, complete security correctness, full test sufficiency, regression absence or merge readiness.
