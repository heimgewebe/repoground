# RepoBrief Answer Grounding Contract v1 Proof

Status: review_ready
Initiative: `REPOBRIEF-FRONTDOOR-GROUNDING-V1`
Task: `RBGV-V1-T001`

## Result

This slice defines the first RepoBrief Answer Grounding contracts:

- `merger/lenskit/contracts/answer-grounding-declaration.v1.schema.json`
- `merger/lenskit/contracts/answer-grounding-verdict.v1.schema.json`
- `docs/contracts/answer-grounding-v1.md`

The contracts establish a machine-readable boundary for answers that declare citation/range
evidence and for later deterministic grounding-verification results.

## What this slice adds

- Answer declaration shape: answer identity, snapshot reference, task profile, question and
  answer hashes, used citation IDs, used ranges, optional strong-claim markers, freshness
  caveats and mandatory non-claims.
- Grounding verdict shape: checked declaration reference, snapshot reference, citation
  checks, range checks, required-reading checks, diagnostics, freshness/availability caveats
  and mandatory non-claims.
- Closed v1 status vocabulary: `pass`, `warn`, `fail`, `degraded`, `not_applicable`.
- Rejection tests for truth/support statuses such as `supported`, `unsupported`, `true` and
  `false`.
- Documentation examples for pass, warn, fail and degraded outcomes.

## Critical boundary

A grounding `pass` means only that the checked declaration satisfies the technical grounding
contract in the checked scope. It does not establish answer truth, semantic correctness,
complete context use, repository understanding, runtime behavior, test sufficiency, merge
readiness or security correctness.

## Validation

Focused validation run:

```bash
git diff --check
python -m pytest merger/lenskit/tests/test_answer_grounding_contracts.py -q
python -m pytest merger/lenskit/tests/test_contract_inference_boundaries.py merger/lenskit/tests/test_contract_version_guards.py -q
python -m pytest merger/lenskit/tests/test_anti_hallucination_lint.py -q
python -m ruff check merger/lenskit/tests/test_answer_grounding_contracts.py
```

## Does not establish

This proof does not establish:

- verifier implementation;
- actual citation resolution at runtime;
- semantic answer correctness;
- review completeness;
- test sufficiency;
- runtime correctness;
- merge readiness;
- security correctness;
- regression absence.
