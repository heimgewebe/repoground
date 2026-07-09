# RepoBrief Ask Gold Query Evaluation v1 Proof

Status: review_ready
Initiative: `REPOBRIEF-FRONTDOOR-GROUNDING-V1`
Task: `RBGV-V1-T006`

## Result

This slice adds a minimal Ask Frontdoor gold-query evaluator:

- `merger/lenskit/core/repobrief_ask_eval.py`
- `repobrief ask-eval` CLI dispatch
- `docs/retrieval/repobrief_ask_goldset.v1.example.json`
- tests in `merger/lenskit/tests/test_repobrief_ask_eval.py`

## What is measured

- expected path recall;
- citation coverage;
- Required Reading coverage;
- MRR@k;
- budget truncation rate;
- miss taxonomy counts.

## Promotion gate

The evaluation emits a promotion gate that requires:

- no central-query metric regression against a supplied baseline;
- documented measurement advantage over that baseline.

If no baseline is supplied, otherwise passing results remain `warn` for promotion purposes.

## Validation

```bash
git diff --check
python -m pytest merger/lenskit/tests/test_repobrief_ask_eval.py -q
python -m pytest merger/lenskit/tests/test_repobrief_ask_cli.py -q
python -m pytest merger/lenskit/tests/test_repobrief_resolved_evidence_query.py -q
python -m ruff check merger/lenskit/core/repobrief_ask_eval.py merger/lenskit/core/repobrief_ask.py merger/lenskit/cli/cmd_repobrief.py merger/lenskit/tests/test_repobrief_ask_eval.py
```

## Does not establish

This proof does not establish answer correctness, repository understanding, review completeness,
retrieval quality sufficiency, default-promotion safety, runtime correctness outside the tested paths,
full test sufficiency, merge readiness, security correctness or regression absence.
