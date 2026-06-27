# Review-Intent Router v1 Target Proof

Status: implementation target proof; opt-in only

## Task

`TASK-RETRIEVAL-REVIEW-INTENT-001` implements the first bounded candidate from
Slice 16 of `docs/blueprints/lenskit-agent-front-door-hardening.md`: a
deterministic Review-Intent Router for questions that ask for several artifact
roles at once.

A normal lexical query is a single search expression. Review questions often ask
for an implementation, its tests, its contract, and its documentation in one
sentence. Requiring every role word to occur in one chunk suppresses the
cross-file evidence set the reviewer asked for. The new planner therefore creates
separate, bounded search lanes and combines them deterministically.

## Implemented surface

- `review_router.plan_review_query()` extracts explicit anchor terms and requested
  artifact roles without embeddings, LLM calls, or generic stemming.
- `review_query.execute_review_query()` executes the plan as an opt-in library
  surface.
- The established legacy router runs first as the `legacy` compatibility lane.
  Existing good top hits therefore retain priority before role-specific lanes add
  further unique paths.
- Role lanes use bounded FTS5 path filters for tests, contracts, CLI files, and
  documentation. Source/general lookup remains unqualified.
- Strict variants run before relaxed variants inside each lane.
- Fusion is `round_robin_unique_path`; duplicate chunks from the same repository
  path cannot consume multiple final positions.
- Exact path exclusions are applied before ordering and limiting in every lane.
- Review-intent execution can be selected by `eval_core.do_eval(...,
  review_intent=True)` and by `run_review_retrieval_baseline(...,
  review_intent=True)`.

## Compatibility boundary

The default `execute_query()` path still uses the established router. The new
mode is not wired into the CLI, bundle production, service API, or default
ranking. Internal prepared-query parameters in `query_core.execute_query()` are
an execution seam for the bounded planner; callers that do not provide them
retain the old behavior.

The review mode rejects simultaneous semantic or graph comparison. This avoids
an undeclared mixture of ranking systems in the first slice.

## Contracts

The existing strict contracts now describe fields that the retrieval surfaces
already emit or need for the opt-in mode:

- `query-result.v1.schema.json` permits exact `applied_exclusions` and the
  `path_exclusions` evidence basis.
- `retrieval-eval.v1.schema.json` permits machine-readable
  `measurement_conditions`, including the review plan version, fusion method,
  changed-ranking flag, and `default_promoted=false`.

These additions do not upgrade diagnostic output to canonical repository truth.

## Deterministic evidence

`merger/lenskit/tests/test_review_router.py` proves deterministic role ordering,
explicit term variants, bounded path filters, the legacy compatibility lane, and
empty-query behavior.

`scripts/proofs/review_intent_router_audit.py` reproduces the legacy-versus-review
comparison on one explicit index, excludes the goldset and proof machinery by exact
repository path, and fails closed on aggregate non-improvement or any per-category
Recall/MRR regression. `test_review_intent_router_audit.py` proves both the passing
and category-regression paths.

`merger/lenskit/tests/test_review_query.py` builds a synthetic SQLite/FTS5 index
containing implementation, test, contract, documentation, duplicate source
chunks, and the goldset itself. It proves:

- repeat runs return the same path order;
- paths are unique after fusion;
- all requested roles can be represented;
- the goldset exclusion is applied per lane before limiting;
- a legacy top hit remains the review top hit;
- raw query and eval results validate against their JSON schemas;
- the legacy public path remains unchanged;
- the fixture improves from zero expected-target hits to all four expected
  targets without claiming default promotion.

Focused verification while preparing the slice:

- 118 router/query/eval/review tests passed;
- 188 broader retrieval, graph, schema-range, and review tests passed;
- 293 focused retrieval, audit, and planning-control tests passed together;
- Ruff passed for all changed Python files.

## Manifest- and commit-bound full-snapshot audit

`docs/proofs/review-intent-router-v1-audit.json` was regenerated from clean tracked
commit `f1d34debaae6bbce0ce74803b2747ee41bfab931`. The audit now requires the bundle
manifest and verifies the canonical dump, chunk index, SQLite index, byte sizes,
SHA-256 values, clean generator state, and generator commit against the audited
repository HEAD.

For the versioned 20-query review goldset at `k=10`:

- query Recall improved from `10.0` to `100.0` (`+90.0` percentage points);
- MRR improved from `0.1` to `0.37666666666666665`;
- expected-target hits improved from `2/60` to `30/60`;
- expected-target recall improved from `3.3333333333333335%` to `50.0%`;
- zero-hit ratio fell from `0.25` to `0.0`;
- no category regressed in query Recall, MRR, or expected-target recall;
- all nine audit gates passed;
- all 20 queries executed the review pipeline, with zero fallbacks and zero errors.

The 100% query Recall means every query returned at least one expected path. It
does not mean all requested artifacts were found; expected-target recall is 50%.
These values describe that exact manifest-bound snapshot and exclusion set. They
are not a universal retrieval-quality claim and do not promote the mode to the
default.

## Does not establish

- A returned artifact is relevant, correct, sufficient, or safe.
- Role coverage is review completeness.
- A missing lane hit is repository absence.
- Fixture improvement generalizes to unmeasured queries.
- The mode is ready for default promotion.
- The indexed snapshot equals the current working tree.

## Remaining promotion gate

The manifest- and commit-bound audit now supplies aggregate and per-category query and expected-target measurements
for this opt-in slice. Default promotion remains a separate decision because it
also requires explicit product-policy review, broader unmeasured query evidence,
and a decision about CLI, service, bundle, manifest, and consumer integration.
Until such a follow-up is approved, `default_promoted` remains `false`.
