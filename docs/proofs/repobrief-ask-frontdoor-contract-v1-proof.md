# RepoBrief Ask Frontdoor Contract v1 Proof

Status: review_ready
Initiative: `REPOBRIEF-FRONTDOOR-GROUNDING-V1`
Task: `RBGV-V1-T004`

## Result

This slice defines the read-only Ask Frontdoor contract surfaces:

- `merger/lenskit/contracts/repobrief-ask-request.v1.schema.json`
- `merger/lenskit/contracts/repobrief-ask-context-pack.v1.schema.json`
- `docs/contracts/repobrief-ask-frontdoor-v1.md`

## What is covered

- request fields: query, task profile, token budget, snapshot/freshness policy and output mode;
- context-pack fields: snapshot reference, freshness, availability, required reading, retrieval hits,
  resolved ranges and answer scaffold;
- explicit forbidden operations: implicit refresh, Git mutation, snapshot creation on read, patch
  application, pull-request mutation, shell execution and merge authorization;
- answer scaffold fields for citation obligations, caveats and non-claims.

## Validation

```bash
git diff --check
python -m pytest merger/lenskit/tests/test_repobrief_ask_frontdoor_contracts.py -q
python -m pytest merger/lenskit/tests/test_answer_grounding_contracts.py -q
python -m pytest merger/lenskit/tests/test_contract_version_guards.py -q
python -m ruff check merger/lenskit/tests/test_repobrief_ask_frontdoor_contracts.py
```

## Does not establish

This proof does not establish a CLI implementation, runtime context-pack assembly, actual reading,
answer correctness, claim truth, complete context use, test sufficiency, merge readiness, security
correctness or regression absence.
