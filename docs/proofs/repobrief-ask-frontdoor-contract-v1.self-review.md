# Self-review — RepoBrief Ask Frontdoor Contract v1

Review target: `RBGV-V1-T004` branch head before PR creation

Files reviewed:

- `merger/lenskit/contracts/repobrief-ask-request.v1.schema.json`
- `merger/lenskit/contracts/repobrief-ask-context-pack.v1.schema.json`
- `merger/lenskit/tests/test_repobrief_ask_frontdoor_contracts.py`
- `docs/contracts/repobrief-ask-frontdoor-v1.md`
- `docs/contracts/contracts-matrix.md`
- `docs/proofs/repobrief-ask-frontdoor-contract-v1-proof.md`
- `docs/proofs/repobrief-ask-frontdoor-contract-v1.self-review.md`

## Result

No blocking issue found in this contract-only slice.

## Critical checks

| Check | Result |
| --- | --- |
| Ask request includes query/task_profile/token_budget/snapshot policy/output mode | Pass |
| Context pack includes snapshot/freshness/availability/required reading/hits/ranges | Pass |
| Read-only no-refresh/no-mutation boundary explicit | Pass |
| Answer scaffold surfaces citation obligations and caveats | Pass |
| Non-claims mandatory | Pass |
| No runtime implementation claim | Pass |

## Limitations

- This is contract-only; no `repobrief ask` CLI yet.
- It does not assemble a context pack from live artifacts.
- It does not prove that a downstream agent actually reads or understands the context.

## Validation

```bash
git diff --check
python -m pytest merger/lenskit/tests/test_repobrief_ask_frontdoor_contracts.py -q
python -m pytest merger/lenskit/tests/test_answer_grounding_contracts.py -q
python -m pytest merger/lenskit/tests/test_contract_version_guards.py -q
python -m ruff check merger/lenskit/tests/test_repobrief_ask_frontdoor_contracts.py
```
