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

## Commit-bound full-snapshot audit

`docs/proofs/review-intent-router-v1-audit.json` was produced from clean tracked
commit `be23706b7dadc4bf24f142ac1d2fb24423c3a4c8` and binds the measurement to the
exact goldset, canonical dump, chunk index, and SQLite index hashes.

For the versioned 20-query review goldset at `k=10`:

- Recall improved from `10.0` to `100.0` (`+90.0` percentage points);
- MRR improved from `0.1` to `0.37666666666666665`;
- expected-target hits improved from `2/60` to `30/60`;
- zero-hit ratio fell from `0.25` to `0.0`;
- no category regressed in Recall or MRR;
- all six audit gates passed.

These values describe that exact snapshot and exclusion set. They are not a
universal retrieval-quality claim and do not promote the mode to the default.

## Does not establish

- A returned artifact is relevant, correct, sufficient, or safe.
- Role coverage is review completeness.
- A missing lane hit is repository absence.
- Fixture improvement generalizes to unmeasured queries.
- The mode is ready for default promotion.
- The indexed snapshot equals the current working tree.

## Remaining promotion gate

The commit-bound audit now supplies the aggregate and per-category measurement
for this opt-in slice. Default promotion remains a separate decision because it
also requires explicit product-policy review, broader unmeasured query evidence,
and a decision about CLI, service, bundle, manifest, and consumer integration.
Until such a follow-up is approved, `default_promoted` remains `false`.
