# Retrieval v2 Promotion Gate Proof

Status: done  
Task: `TASK-RETRIEVAL-V2-PROMOTION-GATE-001`

## Result

This slice adds a diagnostic promotion gate for retrieval-v2 style surfaces. It compares existing measurement reports and does not execute retrieval, change ranking, promote defaults, emit bundles or claim review readiness.

Implemented surfaces:

- `merger/lenskit/retrieval/retrieval_promotion_gate.py`
- `scripts/proofs/retrieval_promotion_gate.py`
- `merger/lenskit/tests/test_retrieval_promotion_gate.py`

## Gate checks

The gate compares legacy FTS and opt-in review-intent reports, plus optional graph and range/citation health reports.

It checks:

- global `recall@10` non-regression
- global `MRR` non-regression
- expected-target recall non-regression
- per-category recall/MRR non-regression
- miss count non-regression
- fallback count is zero
- supplied graph report is not stale/mismatched
- supplied range/citation report has no malformed-hit failure

## Decision boundary

Even when all diagnostic gates pass, `promote_default` remains `false`. Default promotion requires a later explicit decision.

## Validation

```text
python3 -m pytest -q merger/lenskit/tests/test_retrieval_promotion_gate.py
# 4 passed

python3 -m py_compile merger/lenskit/retrieval/retrieval_promotion_gate.py scripts/proofs/retrieval_promotion_gate.py merger/lenskit/tests/test_retrieval_promotion_gate.py
# passed

python3 -m ruff check merger/lenskit/retrieval/retrieval_promotion_gate.py scripts/proofs/retrieval_promotion_gate.py merger/lenskit/tests/test_retrieval_promotion_gate.py
# passed
```

## Non-claims

This slice does not establish retrieval correctness, review completeness, answer correctness, runtime behavior or readiness for default promotion beyond the measured diagnostic gate.
