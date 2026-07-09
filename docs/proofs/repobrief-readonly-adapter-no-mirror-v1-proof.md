# RepoBrief Read-only Adapter without Mirror Authority v1 Proof

Status: review_ready  
Task: `TASK-REPOBRIEF-READONLY-ADAPTER-NO-MIRROR-001`  
Design: `docs/architecture/repobrief-readonly-adapter-no-mirror.md`

## Result

This slice adds the bounded design for a broad RepoBrief read-only adapter without repository mirror authority.

It defines which existing RepoBrief surfaces may be exposed to consumers and which operations remain forbidden.

## Evidence basis

The design is aligned with existing RepoBrief boundary documents:

- `docs/architecture/repobrief-agent-workbench-boundary.md`
- `docs/architecture/repobrief-mcp-boundary.md`
- `docs/architecture/repobrief.md`
- `docs/roadmap/lenskit-agent-operationalization-roadmap.md`

## What this slice adds

- allowed read surfaces;
- forbidden mirror/mutation operations;
- minimal future adapter method list;
- authority, canonicality, freshness and availability metadata requirements;
- fail-closed missing/stale/invalid evidence behavior;
- separation from MCP protocol authority;
- separation from Patch Evaluation Sidecar mutation authority;
- explicit non-goals and non-claims.

## Critical boundaries

The adapter must not:

- clone, fetch, pull, push or checkout Git;
- inspect live worktrees as a fallback;
- silently create or refresh snapshots;
- create PRs, branches or patches;
- run shells, tests, linters, builds or sandboxes;
- read secrets;
- produce review verdicts;
- claim repo understanding, correctness, test sufficiency or merge readiness.

## Validation

This is a docs-only architecture slice.

Expected validation before merge:

```bash
git diff --check
```

No local checkout was available in this connector session.

## Task closeout posture

This design is a review-ready closeout candidate for the design portion of `TASK-REPOBRIEF-READONLY-ADAPTER-NO-MIRROR-001`.

It does not close an implementation task. A later implementation slice should add code-level contracts, tests and consumer wiring.

## Non-claims

This proof does not establish:

- adapter implementation;
- MCP deployment;
- runtime correctness;
- test sufficiency;
- review completeness;
- retrieval quality;
- repo understanding;
- merge readiness;
- security correctness;
- absence of regressions.
