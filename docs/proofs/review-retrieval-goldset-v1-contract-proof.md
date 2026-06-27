# Review Retrieval Goldset v1 Contract Proof

## Scope

This slice formalizes the already committed review-retrieval goldset as a
versioned diagnostic input. It preserves the current top-level list and does not
change `eval_core`, query routing, result ranking, expected targets, or default
runtime behavior.

## Contract

`merger/lenskit/contracts/review-retrieval-goldset.v1.schema.json` controls:

- a non-empty query string;
- one of the 15 established review categories;
- one or more unique expected path or symbolic patterns;
- the existing retrieval filter keys only;
- `recall_at_10` as a ratio between `0` and `1`;
- no undeclared fields at query, filter, or acceptance-criteria level.

The top-level array requires at least 20 cases. This matches the current file and
avoids silently creating a second input shape that the existing evaluator does
not consume.

## Deterministic evidence

`merger/lenskit/tests/test_review_retrieval_goldset.py` validates the complete
committed `docs/retrieval/review_queries.v1.json` against Draft-07 and preserves
the existing repository checks for categories, unique query text, real path
targets, and symbolic targets. Negative fixtures prove rejection of:

- undeclared query fields;
- an uncontrolled `impact` category;
- unknown filters;
- a `recall_at_10` threshold outside the ratio range.

## Does not establish

- Expected patterns are true, complete, relevant, or sufficient.
- A schema-valid query is representative of real review traffic.
- The current category set is complete for future use cases.
- A passing retrieval run proves repository understanding.
- Recall or MRR proves semantic correctness or review completeness.
- Tests are sufficient or regressions are absent.
- Runtime behavior is correct.
- Any retrieval mode is ready for default promotion.

## Compatibility boundary

Adding query IDs, task intents, facet expectations, a top-level metadata envelope,
or new categories requires an explicit contract evolution and matching evaluator
support. Those changes are not smuggled into this compatibility slice.
