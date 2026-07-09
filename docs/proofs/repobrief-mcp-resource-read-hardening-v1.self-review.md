# Self-review — RepoBrief MCP Resource Read Hardening v1

Status: complete
Head: local branch `fix/mcp-resource-atomic-read-v1`
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
| Oversized artifact content is blocked by bounded byte read before hashing/content decode | Pass |
| Byte/SHA drift is checked against the same bounded byte buffer that may be returned | Pass |
| Missing or malformed integrity metadata returns `integrity_unavailable` without `content_text` | Pass |
| Invalid file-valued bundle roots return explicit `blocked` status | Pass |
| `artifact/bundle_manifest` returns an `artifact_ref` shape | Pass |
| Read-only/non-claim semantics remain explicit | Pass |

## Notes

The `MAX_RESOURCE_BYTES` cap remains `16 MiB`: high enough for the current Lenskit canonical bundle observed locally, but now enforced by a bounded byte read rather than a separate `stat()`/`read_text()` sequence.

## Does not establish

This self-review does not establish MCP server availability, transport/authentication correctness, runtime deployment, answer correctness, repository understanding, review completeness, complete security correctness, full test sufficiency, regression absence or merge readiness.
