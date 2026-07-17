# Audit finding adapter v1 proof

## Scope

This proof covers deterministic admission, revision freshness and citation resolution. It
does not prove that a verifier is correct, that a cited range supports a claim or that a
review is complete.

## Implemented surface

- `merger/lenskit/retrieval/audit_finding.py`
- `merger/lenskit/contracts/audit-finding-set.v1.schema.json`
- `merger/lenskit/tests/test_audit_finding.py`
- `merger/lenskit/tests/test_audit_finding_contract.py`
- `docs/architecture/audit-finding-adapter-v1.md`

## Invariants

1. Candidate identity is deterministic across whitespace and citation order.
2. Candidates must reference a lane selected by `audit_lane_plan.v1`.
3. Every candidate has at least one syntactically valid citation id.
4. Duplicate semantic candidates and duplicate verifier decisions fail closed.
5. Revision mismatch takes precedence over verifier output and yields `stale`.
6. Unresolvable citations take precedence over verifier output and yield `unresolved`.
7. Blocked verification records remain visible but are marked unapplied.
8. Output ordering is stable by `finding_id`.
9. State-count ordering and applied-verification consistency are contract-bound.
10. The adapter performs no filesystem, network, subprocess, agent or repository write.
11. Authority and forbidden inferences remain explicit and schema-bound.

## Verification

The focused verification command is:

```text
pytest -q \
  merger/lenskit/tests/test_audit_lane.py \
  merger/lenskit/tests/test_audit_finding.py \
  merger/lenskit/tests/test_audit_finding_contract.py
```

Repository-wide GitHub CI is authoritative for the published change. The PR must not be
merged until tests, lint, contract validation, security checks and self-review are green.
