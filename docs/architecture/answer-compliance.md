# Answer Compliance Contract

## Status

PR 2 — Answer Compliance Contract v1.

## Purpose

Machine-readable declaration of what an answer says it used.

## Relationship to Required Reading Protocol

Required Reading Protocol defines what should be available/read for a task profile.
Answer Compliance declares what an answer says it used, did not use, or could not verify.

## Relationship to Agent Reading Pack Checklist

| Agent Reading Pack checklist field | answer-compliance.v1 field |
| --- | --- |
| task_profile | task_profile |
| required_artifacts_checked | declared_artifacts |
| sidecars_used | declared_artifacts |
| canonical_ranges_or_citations_used | declared_citations / declared_ranges |
| sidecars_not_used_and_why | unread_required_artifacts / unread_recommended_artifacts / epistemic_gaps |
| epistemic_gaps | epistemic_gaps |
| does_not_establish | does_not_establish |

## Non-Truth Boundary

This contract does not prove:
- actual_reading_proven
- answer_correct
- repo_understood
- all_relevant_context_used
- claims_true
- test_sufficiency
- regression_absence
- runtime_behavior
- forensic_ready

## Example

Range declarations accept a minimal v1-like line range or a minimal v2-like artifact/source range shape. Full range resolution is intentionally deferred to the later Agent Consumption Trace validator.

```json
{
  "kind": "lenskit.answer_compliance",
  "version": "1.0",
  "task_profile": "pr_review",
  "declared_artifacts": [
    "agent_reading_pack",
    "canonical_md",
    "citation_map_jsonl"
  ],
  "declared_citations": [
    {
      "citation_id": "c-example",
      "purpose": "support a specific claim"
    }
  ],
  "declared_ranges": [
    {
      "artifact": "canonical_md",
      "range_ref": {
        "file_path": "lenskit-max-example_merge.md",
        "start_line": 1,
        "end_line": 3
      },
      "purpose": "verify cited canonical content"
    }
  ],
  "unread_required_artifacts": [],
  "unread_recommended_artifacts": [
    "bundle_surface_validation"
  ],
  "epistemic_gaps": [
    {
      "kind": "test_not_run",
      "detail": "No local pytest run was executed for this answer."
    }
  ],
  "does_not_establish": [
    "actual_reading_proven",
    "answer_correct",
    "repo_understood",
    "all_relevant_context_used",
    "claims_true",
    "test_sufficiency",
    "regression_absence",
    "runtime_behavior",
    "forensic_ready"
  ]
}
```

## Boundary to Agent Consumption Trace

The Agent Consumption Trace validator compares Required Reading Protocol
expectations against Answer Compliance declarations.
The comparison remains declaration-based. It does not prove actual reading,
correct use of an artifact, answer correctness, completeness or repository
understanding.
