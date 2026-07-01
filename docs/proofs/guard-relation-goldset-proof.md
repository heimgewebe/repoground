# Guard Relation Goldset Proof

Status: done  
Task: `TASK-GUARD-RELATION-GOLDSET-001`

## Result

This slice adds a diagnostic goldset and evaluator for `tests_by_name` and `validates_schema`. It does not add persistent cards, a producer, a bundle artifact, ranking integration or review-impact semantics.

## Goldset and evaluator

The goldset is `docs/retrieval/guard_relation_goldset.v1.json`. The evaluator is `scripts/proofs/guard_relation_goldset_eval.py`.

It reports total cases, true positives, false positives, false negatives, true negatives, unresolved cases, precision, resolved-positive recall and false-positive rate over resolved negative controls.

The current diagnostic goldset has, for each relation type: 4 total cases, 2 true positives, 1 false-positive negative-control case, 1 unresolved case and precision `0.666667`.

## Decision

Persistent Guard Relation Cards remain blocked. There is no established consumer requiring persistence; negative controls show relation-specific false-positive risk; unresolved candidates remain present; and the relation would be easy to overread as test sufficiency or runtime correctness.

## Validation

```text
pytest -q merger/lenskit/tests/test_grg_goldset.py
# 3 passed
```

## Non-claims

This slice does not establish test sufficiency, runtime correctness, regression absence, schema runtime equivalence, review completeness or need for persistent Guard Relation Cards.
