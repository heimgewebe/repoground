# Self-review — RepoBrief Ask Gold Query Evaluation v1

Review target: `RBGV-V1-T006` branch head before PR creation

Files reviewed:

- `merger/lenskit/core/repobrief_ask_eval.py`
- `merger/lenskit/core/repobrief_ask.py`
- `merger/lenskit/cli/cmd_repobrief.py`
- `merger/lenskit/tests/test_repobrief_ask_eval.py`
- `docs/retrieval/repobrief_ask_goldset.v1.example.json`
- `docs/proofs/repobrief-ask-gold-query-eval-v1-proof.md`
- `docs/proofs/repobrief-ask-gold-query-eval-v1.self-review.md`

## Result

No blocking issue found in this evaluation slice.

## Critical checks

| Check | Result |
| --- | --- |
| Gold queries specify expected paths/citations | Pass |
| Evaluation reports citation coverage | Pass |
| Evaluation reports Required Reading coverage | Pass |
| Evaluation reports recall/MRR | Pass |
| Evaluation reports miss taxonomy | Pass |
| Promotion gate requires baseline/no regression/advantage | Pass |
| Non-claims include no retrieval sufficiency/default-promotion safety | Pass |
| CLI emits evaluation report | Pass |

## Review notes

The evaluator is deliberately small and deterministic. It uses `repobrief ask` context packs as the evaluated artifact. It does not run an LLM and does not judge final answer quality.

The promotion gate is conservative: without baseline metrics, otherwise passing results remain a warning for promotion. With baseline metrics, eligibility requires no regression and positive aggregate measurement advantage.

## Limitations

- The goldset shape is documented by example and tests, not yet a separate schema.
- Expected range matching is currently path/citation focused; more precise range matching can come later.
- Metrics are only as strong as the provided goldset and baseline.

## Validation

```bash
git diff --check
python -m pytest merger/lenskit/tests/test_repobrief_ask_eval.py -q
python -m pytest merger/lenskit/tests/test_repobrief_ask_cli.py -q
python -m pytest merger/lenskit/tests/test_repobrief_resolved_evidence_query.py -q
python -m ruff check merger/lenskit/core/repobrief_ask_eval.py merger/lenskit/core/repobrief_ask.py merger/lenskit/cli/cmd_repobrief.py merger/lenskit/tests/test_repobrief_ask_eval.py
```

## Non-claims

This self-review does not establish answer correctness, repository understanding, review completeness,
retrieval quality sufficiency, default-promotion safety, runtime correctness, full test sufficiency,
merge readiness, security correctness or absence of regressions.
