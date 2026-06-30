# Query Range-Ref Audit Proof

Status: done  
Task: `TASK-QUERY-RANGE-REF-AUDIT-001`  
Scope: audit only; no query runtime, schema, ranking, service, or bundle mutation.

## 1. Purpose

This audit answers a narrow operational question from the Agent Operationalization roadmap:

> Which retrieval query results already carry resolvable range references, and what is still missing before a stronger proof-carrying query surface is justified?

The audit is deliberately conservative. A query hit with a range pointer is easier to cite; it is not automatically true, sufficient, complete, or semantically important.

## 2. Current implemented surfaces

### Query output

`execute_query()` already emits optional per-hit range surfaces:

- `range_ref`: parsed from stored chunk metadata field `content_range_ref`.
- `derived_range_ref`: built at query time when explicit metadata is absent but source-file, byte range, line range, and content hash are available.

The top-level query result also carries `claim_boundaries`. Its `evidence_basis` includes `result_ranges` only when at least one result has `range_ref` or `derived_range_ref`.

### Query Result contract

`query-result.v1.schema.json` already accepts both `range_ref` and `derived_range_ref` on result items. Both may be v1 or v2 range refs. The schema does not require every result item to have one.

### Context bundle

`build_context_bundle()` propagates explicit and derived range refs into context hits and exposes epistemic status:

- explicit `range_ref` -> `provenance_type=explicit`, `resolver_status=resolved_explicit`
- `derived_range_ref` -> `provenance_type=derived`, `resolver_status=resolved_derived`
- no ref -> `provenance_type=derived`, `resolver_status=unresolved`

This is the right shape for agent-facing uncertainty: the context bundle distinguishes a real explicit pointer from a fallback and from an unresolved hit.

### Resolver

`resolve_range_ref()` accepts explicit bundle-backed references and source-file fallback references, with path and hash checks. Existing tests cover v1/v2 range refs, malformed refs, path traversal rejection, source-file fallback, and backwards compatibility.

## 3. What is already good enough

- Stored explicit `content_range_ref` can roundtrip into query `range_ref` and then through `resolve_range_ref()`.
- Dynamic fallback can produce `derived_range_ref` when source-file metadata is available.
- Old indexes without range metadata degrade safely: query execution completes without inventing a false range ref.
- Query output boundaries already avoid claiming repository completeness or semantic importance.
- Context bundles preserve the epistemic difference between explicit, derived, and unresolved hits.

## 4. Gaps found

### Gap A — no all-hit range guarantee

`query-result.v1` allows result items without `range_ref` and without `derived_range_ref`. This is intentional for backwards compatibility and degraded indexes, but it means consumers cannot assume every query result is citation-ready.

Consequence: a future proof-carrying query mode must report per-hit range coverage, not just presence of any range in the result set.

### Gap B — `result_ranges` means at least one hit, not all hits

`claim_boundaries.evidence_basis` currently adds `result_ranges` if any returned hit has a range ref. That is useful, but weaker than a coverage metric. It does not mean every hit is range-backed.

Consequence: consumers must inspect each hit or a future summary field; top-level `result_ranges` is not enough for answer safety.

### Gap C — derived source refs are not canonical citations

`derived_range_ref` can be resolvable and useful, but it is a fallback to source-file provenance. It is not the same authority class as an explicit `canonical_md` range.

Consequence: agent-facing citation policy should prefer explicit `canonical_md` `range_ref` and treat `derived_range_ref` as fallback context, not as canonical evidence.

### Gap D — citation-map bridge is indirect

Citation-map compatibility exists through chunk identity and canonical ranges, but raw query hits do not currently expose `citation_id`. A consumer that wants stable citation IDs must bridge from hit `chunk_id` / range metadata to `citation_map_jsonl`.

Consequence: a minimal adapter is justified before any stronger agent-answer surface: `query_result -> citation candidates` should be explicit and diagnostic.

## 5. Decision

Do not create a new proof-carrying query contract yet.

Instead, the next implementation slice should be a minimal diagnostic adapter:

`query-range-coverage report`

It should compute, for a query result or query execution:

- total hits
- hits with explicit `range_ref`
- hits with explicit `canonical_md` range refs
- hits with `derived_range_ref`
- unresolved hits
- optional `citation_id` candidates when `citation_map_jsonl` is available
- per-hit status: `canonical_explicit`, `explicit_noncanonical`, `derived_source`, `unresolved`, `malformed`

This report remains diagnostic. It must not score answer correctness, claim truth, retrieval completeness, test sufficiency, or repository understanding.

## 6. Validation run

Local focused validation:

```text
pytest -q merger/lenskit/tests/test_query_schema_range_ref.py
# 7 passed

pytest -q merger/lenskit/tests/test_range_ref_backwards_compat.py merger/lenskit/tests/test_range_resolver.py
# 20 passed
```

This proves the audited contract/resolver basis remains green. It does not prove that every real bundle or old index has full range coverage.

## 7. Non-claims

This audit does not establish:

- answer correctness
- claim truth
- full repository coverage
- retrieval completeness
- semantic importance of ranked hits
- live working-tree state
- that every query result is citation-ready
- that `derived_range_ref` is equivalent to a canonical citation
