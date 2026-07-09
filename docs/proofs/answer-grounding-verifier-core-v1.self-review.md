# Self-review — RepoBrief Answer Grounding Verifier Core v1

Review target: `RBGV-V1-T002` branch head before PR creation

Files reviewed:

- `merger/lenskit/core/answer_grounding.py`
- `merger/lenskit/tests/test_answer_grounding_verifier.py`
- `docs/proofs/answer-grounding-verifier-core-v1-proof.md`
- `docs/proofs/answer-grounding-verifier-core-v1.self-review.md`

## Result

No blocking issue found in this minimal verifier-core slice.

## Critical checks

| Check | Result |
| --- | --- |
| Existing-artifact read-only boundary | Pass |
| Known citation ID resolution | Pass |
| Declared range resolution through existing resolver | Pass |
| Hash/text drift fails | Pass |
| Missing citation fails | Pass |
| Degraded dependency path visible | Pass |
| Required/recommended artifact distinction | Pass |
| Mandatory non-claims checked | Pass |

## Review notes

The verifier intentionally accepts explicit file paths instead of discovering or creating
snapshots. This keeps `RBGV-V1-T002` narrow and prevents accidental refresh or repo mutation.
The implementation does not validate the declaration schema itself; the previous contract
slice owns schema shape, while this slice focuses on deterministic grounding mechanics.

## Limitations

- No CLI command yet; that belongs to later frontdoor tasks.
- No MCP exposure yet.
- Strong-claim markers are not semantically evaluated.
- Citation-map entries without range information only prove ID presence, not span content.

## Validation

```bash
git diff --check
python -m pytest merger/lenskit/tests/test_answer_grounding_verifier.py -q
python -m pytest merger/lenskit/tests/test_answer_grounding_contracts.py -q
python -m pytest merger/lenskit/tests/test_range_resolver.py merger/lenskit/tests/test_citation_map_schema.py -q
python -m ruff check merger/lenskit/core/answer_grounding.py merger/lenskit/tests/test_answer_grounding_verifier.py
```

## Non-claims

This self-review does not establish semantic answer correctness, actual reading, runtime
correctness, full test sufficiency, review completeness, merge readiness, security
correctness or absence of regressions.
