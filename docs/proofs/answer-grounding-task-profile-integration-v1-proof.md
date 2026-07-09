# RepoBrief Answer Grounding Task-Profile Integration v1 Proof

Status: review_ready
Initiative: `REPOBRIEF-FRONTDOOR-GROUNDING-V1`
Task: `RBGV-V1-T003`

## Result

This slice connects the Answer Grounding verifier to the existing Required Reading task-profile matrix.

Added/changed:

- `verify_answer_grounding_for_task_profile(...)`
- required/recommended evidence roles derived from `default_required_reading_protocol()`
- declaration `availability_caveats` carried into verdicts
- tests for required fail, recommended warn, caveat propagation, and unknown profile behavior

## Behavior

- The task profile determines required and recommended evidence roles.
- Missing required evidence yields failing required-reading checks.
- Missing recommended evidence yields warning required-reading checks.
- Freshness caveats are mirrored from declaration to verdict.
- Availability caveats are mirrored from declaration to verdict.
- Verdicts keep mandatory non-claims, including that grounding does not prove actual reading or repository understanding.

## Validation

```bash
git diff --check
python -m pytest merger/lenskit/tests/test_answer_grounding_verifier.py -q
python -m pytest merger/lenskit/tests/test_answer_grounding_contracts.py -q
python -m pytest merger/lenskit/tests/test_required_reading_protocol.py -q
python -m ruff check merger/lenskit/core/answer_grounding.py merger/lenskit/tests/test_answer_grounding_verifier.py
```

## Does not establish

This proof does not establish actual reading, semantic answer correctness, complete context use,
runtime correctness outside the tested paths, test sufficiency, review completeness, merge readiness,
security correctness or regression absence.
