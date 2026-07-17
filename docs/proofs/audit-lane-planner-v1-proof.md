# Audit lane planner v1 proof

## Scope

This proof covers only deterministic planning. It does not prove that an external agent
review is correct, complete, safe or useful.

## Implemented surface

- `merger/lenskit/retrieval/audit_lane.py`
- `merger/lenskit/contracts/audit-lane-plan.v1.schema.json`
- `merger/lenskit/tests/test_audit_lane.py`
- `docs/architecture/audit-lane-adoption-v1.md`

## Invariants

1. The planner performs no filesystem, network, subprocess, agent or repository write.
2. Changed paths must be relative normalized POSIX repository paths.
3. Path evidence has weight two; query hints have weight one.
4. Ties follow the immutable catalog order.
5. Output contains between one and eight lanes.
6. No-match input receives one general integrity lane rather than a false absence claim.
7. The contract records diagnostic authority and explicit forbidden inferences.

## Local verification before publication

Executed against the isolated file set:

```text
python -m py_compile merger/lenskit/retrieval/audit_lane.py
pytest -q merger/lenskit/tests/test_audit_lane.py
```

Result: `15 passed`.

The GitHub PR remains responsible for repository-wide CI and integration validation.
