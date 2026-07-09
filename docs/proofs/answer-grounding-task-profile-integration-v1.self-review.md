# Self-review — RepoBrief Answer Grounding Task-Profile Integration v1

Review target: `RBGV-V1-T003` branch head before PR creation

Files reviewed:

- `merger/lenskit/core/answer_grounding.py`
- `merger/lenskit/contracts/answer-grounding-declaration.v1.schema.json`
- `merger/lenskit/tests/test_answer_grounding_verifier.py`
- `docs/proofs/answer-grounding-task-profile-integration-v1-proof.md`
- `docs/proofs/answer-grounding-task-profile-integration-v1.self-review.md`

## Result

No blocking issue found in this integration slice.

## Critical checks

| Check | Result |
| --- | --- |
| Task profiles determine required/recommended evidence | Pass |
| Missing required evidence fails | Pass |
| Missing recommended evidence warns | Pass |
| Freshness caveats carried into verdict | Pass |
| Availability caveats carried into verdict | Pass |
| Non-claims still visible | Pass |
| Unknown profile does not become a false pass | Pass |
| No Git/shell/refresh/patch/PR/merge authority added | Pass |

## Review notes

The integration uses declared evidence roles rather than the bundle's physical artifact list. That is deliberate: this verifier checks the answer declaration, not whether the bundle generator emitted every possible artifact. The physical artifact existence and range resolution remain checked through the existing explicit artifact inputs.

The unknown-profile path appends a `not_applicable` diagnostic and avoids turning an unknown profile into a meaningful grounding pass.

## Limitations

- No CLI command yet.
- No MCP/frontdoor exposure yet.
- Strong-claim markers are still not semantically evaluated.
- A declaration can still lie about whether the model actually read evidence; the verdict keeps that as a non-claim.

## Validation

```bash
git diff --check
python -m pytest merger/lenskit/tests/test_answer_grounding_verifier.py -q
python -m pytest merger/lenskit/tests/test_answer_grounding_contracts.py -q
python -m pytest merger/lenskit/tests/test_required_reading_protocol.py -q
python -m ruff check merger/lenskit/core/answer_grounding.py merger/lenskit/tests/test_answer_grounding_verifier.py
```

## Non-claims

This self-review does not establish actual reading, semantic answer correctness, complete context use,
runtime correctness, full test sufficiency, review completeness, merge readiness, security correctness
or absence of regressions.
