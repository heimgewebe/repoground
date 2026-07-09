# RepoBrief MCP Read-only Frontdoor v1 Proof

Status: review_ready
Initiative: `REPOBRIEF-FRONTDOOR-GROUNDING-V1`
Task: `RBGV-V1-T007`

## Result

This slice adds code-level MCP-shaped read-only frontdoor handlers:

- `ask_context`
- `grounding_verify`

They live in `merger.lenskit.core.repobrief_mcp_tools` alongside the existing explicit `snapshot_create` write handler.

## Semantics

`ask_context` exposes the same context-pack semantics as `repobrief ask` / `repobrief.ask_context_pack.v1`.

`grounding_verify` exposes the same declaration/verdict semantics as the Answer Grounding verifier / `repobrief.answer_grounding_verdict.v1`.

## Read-only boundary

The read-only frontdoor handlers report `writes: []` and forbid:

- Git push/pull/fetch;
- PR creation;
- patch application;
- shell execution;
- auto-review/auto-fix/auto-merge;
- secret reads;
- `snapshot_create` side effects.

They do not call `snapshot_create` and do not write bundle files during read-only smoke tests.

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

## Does not establish

This proof does not establish MCP protocol-server availability, transport/authentication correctness,
runtime deployment, answer correctness, actual reading, repository understanding, review completeness,
merge readiness, security correctness, full test sufficiency or regression absence.
