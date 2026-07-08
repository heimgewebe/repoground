# Guard Relation Persistence Decision v1 proof

Task: `TASK-GUARD-RELATION-PERSISTENCE-DECISION-001` / Bureau `RPU-V1-T009`.

## Decision

Persistent Guard Relation Cards remain **blocked**.

This is an affirmative decision, not missing implementation. The current evidence does not justify promotion from diagnostic/target-proof material to persisted cards.

Machine-readable decision:

```text
docs/proofs/guard-relation-persistence-decision.v1.json
```

## Current consumer decision

No concrete current consumer requires persistent Guard Relation Cards.

Reviewed possible consumers:

| Consumer | Decision | Reason |
|---|---|---|
| Retrieval v2 relation-aware ranking | possible future consumer | Mentioned as possible future scope, but no current implementation or acceptance criterion requires persisted Guard Relation Cards. |
| RepoBrief context and delta compilers | not required | Current consumers use existing bundle Relation Cards as bounded navigation hints and do not require persistent Guard Relation Cards. |
| Bureau task verification | not required | Bureau can consume diagnostic reports and proof documents; it does not need persisted Guard Relation Cards as source of truth. |

## Required thresholds before persistence

Persistence may be reconsidered only if all of these are true:

| Threshold | Required |
|---|---:|
| Concrete consumer named | yes |
| Precision | `>= 0.95` |
| Resolved-positive recall | `>= 0.95` |
| False-positive rate on resolved negative cases | `<= 0.05` |
| Unresolved cases per relation type | `0` |
| Negative semantics preserved | yes |

## Current evidence

Source evidence:

```text
docs/retrieval/guard_relation_goldset.v1.json
scripts/proofs/guard_relation_goldset_eval.py
docs/proofs/guard-relation-goldset-proof.md
```

Live evaluator result for both `tests_by_name` and `validates_schema`:

| Metric | Current |
|---|---:|
| Total cases | 4 |
| True positives | 2 |
| False positives | 1 |
| Unresolved | 1 |
| Precision | `0.666667` |
| Resolved-positive recall | `1.0` |
| False-positive rate on resolved negative cases | `1.0` |

Threshold failures:

```text
no_concrete_consumer
precision_below_threshold
false_positive_rate_above_threshold
unresolved_cases_present
overread_risk_as_test_sufficiency_or_runtime_correctness
```

## Current allowed use

Guard Relation evidence may remain:

```text
diagnostic_goldset
target_proof
manual_review_navigation
future_threshold_evaluation
```

## Current blocked use

This decision blocks:

```text
persistent_guard_relation_cards
bundle_artifact_emission_for_guard_relations
default_retrieval_ranking_signal
review_or_merge_gate
test_sufficiency_claim
```

## Negative semantics

Guard Relation evidence must not be read as:

```text
test_sufficiency
runtime_correctness
regression_absence
review_impact
schema_runtime_equivalence
coverage_completeness
guard_effectiveness
causality
```

## Non-claims

This decision does not establish:

```text
test_sufficiency
runtime_correctness
regression_absence
schema_runtime_equivalence
review_completeness
need_for_persistent_guard_relation_cards
retrieval_quality_improvement
merge_readiness
```
