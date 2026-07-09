# Self-review — RepoBrief MCP Read-only Frontdoor v1

Review target: `RBGV-V1-T007` branch head before PR creation

Files reviewed:

- `merger/lenskit/core/repobrief_mcp_tools.py`
- `merger/lenskit/tests/test_repobrief_mcp_frontdoor.py`
- `merger/lenskit/tests/test_repobrief_mcp_boundary_doc.py`
- `docs/architecture/repobrief-mcp-boundary.md`
- `docs/proofs/repobrief-mcp-readonly-frontdoor-v1-proof.md`
- `docs/proofs/repobrief-mcp-readonly-frontdoor-v1.self-review.md`

## Result

No blocking issue found in this read-only MCP frontdoor slice.

## Critical checks

| Check | Result |
| --- | --- |
| `ask_context` shares ask context-pack semantics | Pass |
| `grounding_verify` shares answer-grounding verdict semantics | Pass |
| Read-only boundary reports `writes: []` | Pass |
| No implicit `snapshot_create` side effect | Pass |
| Forbidden operations include Git, shell, patch, PR, auto-merge, secret read | Pass |
| Smoke tests cover ask context and grounding verification shapes | Pass |
| Existing explicit `snapshot_create` boundary remains tested | Pass |
| Documentation preserves no MCP-server availability claim | Pass |

## Review notes

The handlers are code-level MCP-shaped functions, not a protocol server. They intentionally reuse the existing CLI/core semantics rather than introducing separate MCP-only shapes.

The existing `snapshot_create` handler remains an explicit write exception. The new frontdoor handlers are read-only and their boundary explicitly forbids `snapshot_create_side_effect`.

## Limitations

- No transport/server implementation is added.
- No authentication/authorization behavior is implemented.
- No network binding is introduced.
- These tools still depend on existing snapshot artifacts and do not make stale snapshots fresh.

## Validation

```bash
git diff --check
python -m pytest merger/lenskit/tests/test_repobrief_mcp_frontdoor.py -q
python -m pytest merger/lenskit/tests/test_repobrief_mcp_boundary_doc.py -q
python -m pytest merger/lenskit/tests/test_repobrief_mcp_snapshot_create.py -q
python -m pytest merger/lenskit/tests/test_repobrief_ask_cli.py -q
python -m pytest merger/lenskit/tests/test_answer_grounding_verifier.py -q
python -m ruff check merger/lenskit/core/repobrief_mcp_tools.py merger/lenskit/tests/test_repobrief_mcp_frontdoor.py merger/lenskit/tests/test_repobrief_mcp_boundary_doc.py
```

## Non-claims

This self-review does not establish MCP server availability, transport/authentication correctness,
runtime deployment, answer correctness, actual reading, repository understanding, review completeness,
merge readiness, security correctness, full test sufficiency or absence of regressions.
