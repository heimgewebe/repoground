# RepoBrief Answer Grounding Verifier Core v1 Proof

Status: review_ready
Initiative: `REPOBRIEF-FRONTDOOR-GROUNDING-V1`
Task: `RBGV-V1-T002`

## Result

This slice adds a minimal deterministic read-only grounding verifier:

- `merger/lenskit/core/answer_grounding.py`
- `merger/lenskit/tests/test_answer_grounding_verifier.py`

The verifier reads an Answer Grounding declaration plus explicitly supplied existing bundle
artifacts and emits an `answer-grounding-verdict.v1` shaped result.

## What is checked

- declared citation IDs against a supplied `citation_map_jsonl` file;
- canonical ranges from citation-map entries, when present;
- declared `used_ranges` via the existing `resolve_range_ref` path;
- content/hash drift reported as `fail` with `content_hash_mismatch`;
- missing citations reported as `fail` with `citation_not_found`;
- invalid citation-map JSONL reported as `degraded` when no fail condition is present;
- required artifacts as fail when undeclared;
- recommended artifacts as warn when undeclared;
- mandatory non-claims.

## Read-only boundary

The verifier performs no Git, shell, refresh, snapshot creation, patch, PR, test or merge
operation. It only reads explicitly supplied paths and delegates range extraction to the
existing range resolver.

## Validation

```bash
git diff --check
python -m pytest merger/lenskit/tests/test_answer_grounding_verifier.py -q
python -m pytest merger/lenskit/tests/test_answer_grounding_contracts.py -q
python -m pytest merger/lenskit/tests/test_range_resolver.py merger/lenskit/tests/test_citation_map_schema.py -q
python -m ruff check merger/lenskit/core/answer_grounding.py merger/lenskit/tests/test_answer_grounding_verifier.py
```

## Does not establish

This proof does not establish semantic answer correctness, actual model reading, complete
context use, runtime correctness, test sufficiency, review completeness, merge readiness,
security correctness or regression absence.
