# Audit-lane planner and evidence contract hardening proof

## Scope

This proof covers BUREAU-LENSKIT-AUDIT-LANES-005. It does not establish that selected
lanes are useful, that verifier decisions are correct or that review is complete.

## Implemented surface

- `merger/lenskit/retrieval/audit_lane.py`
- `merger/lenskit/retrieval/audit_finding.py`
- `merger/lenskit/contracts/audit-lane-plan.v1.schema.json`
- `merger/lenskit/contracts/audit-finding-set.v1.schema.json`
- `merger/lenskit/contracts/audit-finding-set.v2.schema.json`
- `merger/lenskit/contracts/audit-verification-record.v1.schema.json`
- focused planner, adapter and contract tests

## Proven invariants

1. Noncanonical, duplicate, escaping and over-budget path inputs fail closed.
2. Phrase aliases do not cross path boundaries.
3. Unicode, case, bounded plural and selected German aliases route deterministically.
4. Path evidence outweighs query-only prompt input three to one.
5. Routing diagnostics expose token counts, candidate-lane count and fallback use.
6. Required semantic-boundary arrays reject arbitrary replacement strings.
7. Finding IDs include a versioned domain separator and avoid duplicate normalization.
8. Verification records are versioned, revision-bound, size-bounded and neutral.
9. Stale revisions and missing citations override but preserve supplied records with an
   explicit blocked disposition.
10. The implementation adds no filesystem read, network, subprocess, agent or repository
    mutation surface.

## Focused verification

```text
python -m py_compile \
  merger/lenskit/retrieval/audit_lane.py \
  merger/lenskit/retrieval/audit_finding.py

ruff check \
  merger/lenskit/retrieval/audit_lane.py \
  merger/lenskit/retrieval/audit_finding.py \
  merger/lenskit/tests/test_audit_lane.py \
  merger/lenskit/tests/test_audit_finding.py \
  merger/lenskit/tests/test_audit_finding_contract.py

pytest -q \
  merger/lenskit/tests/test_audit_lane.py \
  merger/lenskit/tests/test_audit_finding.py \
  merger/lenskit/tests/test_audit_finding_contract.py
```

Local isolated result after self-review hardening: `78 passed`; Ruff and syntax checks passed.
Repository-wide GitHub CI remains authoritative.
