# Self-review — RepoBrief Answer Grounding Contract v1

Review target: `RBGV-V1-T001` branch head before PR creation

Files reviewed:

- `merger/lenskit/contracts/answer-grounding-declaration.v1.schema.json`
- `merger/lenskit/contracts/answer-grounding-verdict.v1.schema.json`
- `merger/lenskit/tests/test_answer_grounding_contracts.py`
- `docs/contracts/answer-grounding-v1.md`
- `docs/contracts/contracts-matrix.md`
- `docs/proofs/answer-grounding-contract-v1-proof.md`
- `docs/proofs/answer-grounding-contract-v1.self-review.md`

## Result

No blocking issue found in this contract-only slice.

## Critical checks

| Check | Result |
| --- | --- |
| Defines answer declaration contract | Pass |
| Defines grounding verdict contract | Pass |
| Keeps verdict technical rather than semantic | Pass |
| Rejects claim-support/truth statuses | Pass |
| Requires mandatory non-claims | Pass |
| Provides pass/warn/fail/degraded examples | Pass |
| Avoids verifier implementation claims | Pass |
| Avoids mutation, Git, shell, patch, PR or merge authority | Pass |

## Review notes

The slice intentionally does not implement citation/range resolution. That belongs to
`RBGV-V1-T002`. The contract uses `used_citations` and `used_ranges` because it models a
grounding declaration, not the older `answer-compliance` artifact. This is acceptable because
the new tests pin the boundary and keep semantic truth out of the status vocabulary.

## Remaining limitations

- The schemas are additive and not yet wired into a producer, CLI or MCP path.
- Strong-claim markers are recorded but not semantically evaluated.
- The verdict can describe drift/missing evidence, but no runtime verifier exists yet.

## Validation

```bash
git diff --check
python -m pytest merger/lenskit/tests/test_answer_grounding_contracts.py -q
python -m pytest merger/lenskit/tests/test_contract_inference_boundaries.py merger/lenskit/tests/test_contract_version_guards.py -q
python -m pytest merger/lenskit/tests/test_anti_hallucination_lint.py -q
python -m ruff check merger/lenskit/tests/test_answer_grounding_contracts.py
```

## Non-claims

This self-review does not establish implementation correctness, runtime behavior, full test
sufficiency, review completeness, semantic answer correctness, merge readiness, security
correctness or absence of regressions.
