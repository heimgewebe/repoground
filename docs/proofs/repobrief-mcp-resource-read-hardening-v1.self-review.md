# Self-review — RepoBrief MCP Resource Read Hardening v1

Status: complete
Head: local branch `fix/mcp-resource-read-hardening-v1`
Scope:

- `merger/lenskit/core/repobrief_mcp_resources.py`
- `merger/lenskit/tests/test_repobrief_mcp_resources.py`
- `docs/proofs/repobrief-mcp-resource-read-hardening-v1-proof.md`
- `docs/tasks/index.json`
- `docs/tasks/board.md`

## Review result

No blocking issue found in this hardening slice.

## Checklist

| Check | Result |
| --- | --- |
| Non-manifest `bundle_root` files are not exposed as manifest resources | Pass |
| Fake manifest files with wrong `kind` are not exposed | Pass |
| Real file-valued `*.bundle.manifest.json` remains accepted | Pass |
| Absolute path escapes are blocked before content read | Pass |
| Relative path escapes are blocked before content read | Pass |
| Symlink escapes are blocked before content read | Pass |
| Oversized artifact content is blocked before hashing/content read | Pass |
| Byte/SHA drift returns `integrity_mismatch` without `content_text` | Pass |
| `artifact/bundle_manifest` returns an `artifact_ref` shape | Pass |
| Read-only/non-claim semantics remain explicit | Pass |

## Notes

The `MAX_RESOURCE_BYTES` cap is intentionally set to `16 MiB`: high enough for the current Lenskit canonical bundle observed locally, but still bounded for MCP-shaped reads.

## Does not establish

This self-review does not establish MCP server availability, transport/authentication correctness, runtime deployment, answer correctness, repository understanding, review completeness, complete security correctness, full test sufficiency, regression absence or merge readiness.
