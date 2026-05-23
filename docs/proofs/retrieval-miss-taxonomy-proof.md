# B2 — Retrieval Miss Taxonomy Proof

**Status:** Implementation COMPLETE  
**Date:** 2026-05-23  
**Python Version:** 3.10.12  
**Branch:** feature/b2-retrieval-miss-taxonomy

## Summary

Retrieval Miss Taxonomy (B2) has been implemented as a diagnostic classification layer for retrieval evaluation misses. The taxonomy is **strictly diagnostic** and does **NOT** claim repository absence, semantic truth, or answer safety.

## Implementation

### 1. Schema Update

**File:** `merger/lenskit/contracts/retrieval-eval.v1.schema.json`

Added `miss_taxonomy` as an optional top-level field with:
- `version: "1.0"`
- `authority: "diagnostic_signal"`
- `risk_class: "diagnostic"`
- Required `does_not_prove` array with 5 mandatory entries
- Aggregate statistics by miss type
- Detailed case classification per query
- Conservative, mechanical miss types only

Current runtime emission in this PR is intentionally conservative and limited to:
- `zero_results`
- `expected_not_in_top_k`
- `path_or_symbol_metadata_missing`
- `stale_eval_input` (as stale diagnostic annotation for miss cases)
- `query_execution_error`
- `unknown`

Other taxonomy enum values exist in schema as forward-compatible vocabulary and are not claimed as emitted by this implementation.

**Schema Semantics:**
- `miss_taxonomy` is optional (backward compatible)
- Existing retrieval metrics (`recall@K`, `MRR`, `total_queries`, `hits`, `zero_hit_ratio`, `stale_flag`) remain UNCHANGED
- `claim_boundaries` remain separate and unmodified

### 2. Implementation in Code

**File:** `merger/lenskit/retrieval/eval_core.py`

**Modified file and added functions:**

#### `classify_miss(query_case, expected_paths, is_relevant, found_count, top_results) -> (miss_types: List[str], primary_miss_type: Optional[str])`

Mechanical classification of retrieval misses:

- **zero_results:** Query returned no results (found_count == 0)
- **query_execution_error:** Query execution failed (`error` present or `why_fail == "query execution failed"`)
- **expected_not_in_top_k:** Eval-declared expected pattern not observed in current returned top-k paths
- **path_or_symbol_metadata_missing:** No expected paths available for classification
- **unknown:** Fallback when no conservative classification possible

Classification is deterministic and fact-based, requiring:
- Query result set (found_count)
- Returned paths (top_results)
- Expected patterns (expected_paths)
- Hit status (is_relevant)

#### `build_miss_taxonomy(results_detail, is_stale) -> Dict[str, Any]`

Builds the complete miss taxonomy from evaluation results:

1. Iterates over all query results
2. Classifies each miss mechanically
3. Aggregates counts by miss type
4. Builds case-level detail records
5. Returns JSON-schema-compatible structure

In compare mode, miss taxonomy classifies the active top-level eval view in `details[]` (semantic/graph-overwritten fields), while nested `detail["baseline"]` is kept as evidence but not separately classified in B2 v1.

**Required `does_not_prove` entries (hardcoded):**

```json
{
  "does_not_prove": [
    "absence_of_retrieval_hit_does_not_prove_absence_in_repository",
    "miss_type_does_not_prove_claim_truth_or_falsehood",
    "ranking_position_does_not_prove_semantic_importance",
    "retrieval_eval_does_not_prove_retrieval_completeness",
    "taxonomy_is_diagnostic_not_authoritative"
  ]
}
```

### 3. Integration

**File:** `merger/lenskit/retrieval/eval_core.py` (`do_eval` function)

Miss taxonomy is generated in the main eval function and included in JSON output:

```python
miss_taxonomy = build_miss_taxonomy(results_detail, is_stale)
out = {
    "metrics": {...},
    "details": results_detail,
    "claim_boundaries": {...},
    "miss_taxonomy": miss_taxonomy
}
```

## Testing

**File:** `merger/lenskit/tests/test_retrieval_eval.py`

**Test Coverage (B2-specific tests):**

| Test | Status | Coverage |
|------|--------|----------|
| `test_miss_taxonomy_present_in_output` | ✅ PASS | Presence in output |
| `test_miss_taxonomy_schema_validation` | ✅ PASS | JSON schema compliance |
| `test_miss_taxonomy_does_not_prove_entries` | ✅ PASS | Required does_not_prove entries |
| `test_miss_taxonomy_zero_results_classification` | ✅ PASS | zero_results classification |
| `test_classify_miss_zero_results` | ✅ PASS | Unit test for zero_results |
| `test_classify_miss_query_execution_error` | ✅ PASS | Unit test for query_execution_error |
| `test_classify_miss_expected_not_in_top_k` | ✅ PASS | Unit test for expected_not_in_top_k |
| `test_classify_miss_hit_case` | ✅ PASS | Hit case (not a miss) |
| `test_classify_miss_missing_metadata` | ✅ PASS | Missing metadata handling |
| `test_classify_miss_found_expected_pattern_in_results_but_not_relevant` | ✅ PASS | Non-empty fallback (`unknown`) when expected pattern appears but case is still non-relevant |
| `test_miss_taxonomy_schema_validation_stale_eval` | ✅ PASS | Stale eval stays schema-valid |
| `test_miss_taxonomy_expected_not_in_top_k_integration` | ✅ PASS | `do_eval()` integration for expected_not_in_top_k |
| `test_miss_taxonomy_query_execution_error_not_counted_as_zero_results` | ✅ PASS | Error-path classification hygiene |
| `test_retrieval_eval_schema_backward_compatibility_without_miss_taxonomy` | ✅ PASS | Legacy output still schema-valid |
| `test_miss_taxonomy_schema_rejects_missing_required_does_not_prove_entry` | ✅ PASS | Required does_not_prove set enforced by schema |
| `test_miss_taxonomy_schema_rejects_missing_required_by_type_key` | ✅ PASS | Stable by_type contract shape |

**Test Execution Results:**

```
$ python3 -m pytest merger/lenskit/tests/test_retrieval_eval.py -k "miss_taxonomy or classify_miss" -v

======================= all selected tests passed =======================
```

**Full Retrieval Eval Test Set:**

All retrieval_eval tests PASS, including the new B2 checks:

```
$ python3 -m pytest merger/lenskit/tests/test_retrieval_eval.py -v

======================= 35 passed =======================
```

Stale eval schema-validity is explicitly covered:

```
test_miss_taxonomy_schema_validation_stale_eval
```

Legacy compatibility without `miss_taxonomy` is explicitly covered:

```
test_retrieval_eval_schema_backward_compatibility_without_miss_taxonomy
```

## Constraints and Semantics

### What B2 Does ✅

- Classifies retrieval misses into conservative, mechanical categories
- Records why expected targets were not retrieved
- Provides diagnostic hints for debugging retrieval quality
- Maintains strict epistemic boundaries via `does_not_prove`
- Preserves backward compatibility (old eval without miss_taxonomy still valid)
- Keeps all existing retrieval metrics unchanged

### What B2 Does NOT Do ❌

- Does NOT claim or prove repository absence
- Does NOT infer semantic truth or falsehood of claims
- Does NOT assess answer safety or validity
- Does NOT change ranking algorithm or retrieval behavior
- Does NOT implement reranking
- Does NOT replace B1 (Context Quality Signals)
- Does NOT modify `claim_boundaries`
- Does NOT create `retrieval_complete` verdict
- Does NOT introduce global scoring or truth assessment

### Forbidden Semantics (Absent)

The following terms do NOT appear in miss taxonomy output:

- `target_absent_from_repo` ✓ Absent
- `repo_gap` (unless explicitly defined as "gap in current surface") ✓ Absent
- `missing from repository` ✓ Absent
- `repo_understood` ✓ Absent
- `retrieval_complete` ✓ Absent
- `claims_true`, `claims_false` ✓ Absent
- `supported`, `unsupported` ✓ Absent
- `proven`, `agent_safe`, `unsafe` ✓ Absent

## Roadmap Compliance

**Baseline Verified:**

- ✅ `main` includes B1 Context Quality Signals (PR #695)
- ✅ `main` includes A2 Noise Hygiene (#694)
- ✅ `main` includes A5 Agent Export Gate (#693)
- ✅ `main` includes A3 Range-Ref v2 (#692)
- ✅ `main` includes A4 Post-emit Health (#691)
- ✅ `main` includes B3 Context Risk (#690)

**Pre-Implementation Review:**

- ✅ Inspected `docs/roadmap/lenskit-master-roadmap.md` — B2 marked as separate future PR
- ✅ Inspected `docs/blueprints/lenskit-anti-hallucination-output-architecture.md` — B2 framed as diagnostic
- ✅ Inspected existing retrieval eval docs and proofs — no prior miss classification layer
- ✅ Verified contract in `docs/contracts/contracts-matrix.md` — retrieval-eval.v1.schema.json documented

**After-Implementation:**

- ✅ B1/B2 separation explicit (B1 = context quality, B2 = miss explanation)
- ✅ Roadmap updated (see next section)
- ✅ No later retrieval improvement/ranking work marked as done

## Validation Results

### Code Quality

```bash
$ ruff check --select=F401,F811 --exclude='**/fixtures/**' .

✅ All checks passed
```

### Test Suite

```bash
$ python3 -m pytest merger/lenskit/tests/test_retrieval_eval.py -v --tb=short

======================= 35 passed =======================

PASSED: test_parse_gold_queries_basic
PASSED: test_parse_gold_queries_robustness
PASSED: test_run_eval_integration
PASSED: test_schema_validation
PASSED: test_schema_smoke
PASSED: test_parse_gold_queries_json
PASSED: test_run_eval_integration_json
PASSED: test_run_eval_gate_failure
PASSED: test_run_eval_conflicting_thresholds_fails
PASSED: test_run_eval_invalid_threshold_fails
PASSED: test_retrieval_eval_claim_boundaries_present
PASSED: test_retrieval_eval_claim_boundaries_schema_valid
PASSED: test_retrieval_eval_claim_boundaries_reject_unknown_evidence
PASSED: test_retrieval_eval_claim_boundaries_reject_extra_field
PASSED: test_retrieval_eval_claim_boundaries_reject_missing_required_subfield
PASSED: test_retrieval_eval_schema_rejects_missing_claim_boundaries
PASSED: test_retrieval_eval_claim_boundaries_graph_absent_when_graph_load_fails
PASSED: test_retrieval_eval_claim_boundaries_graph_present_when_graph_actually_used
PASSED: test_run_eval_explain_always_present_on_error
PASSED: test_miss_taxonomy_present_in_output
PASSED: test_miss_taxonomy_schema_validation
PASSED: test_miss_taxonomy_schema_validation_stale_eval
PASSED: test_miss_taxonomy_does_not_prove_entries
PASSED: test_miss_taxonomy_zero_results_classification
PASSED: test_classify_miss_zero_results
PASSED: test_classify_miss_query_execution_error
PASSED: test_classify_miss_expected_not_in_top_k
PASSED: test_classify_miss_hit_case
PASSED: test_classify_miss_missing_metadata
PASSED: test_classify_miss_found_expected_pattern_in_results_but_not_relevant
PASSED: test_miss_taxonomy_expected_not_in_top_k_integration
PASSED: test_miss_taxonomy_query_execution_error_not_counted_as_zero_results
PASSED: test_retrieval_eval_schema_backward_compatibility_without_miss_taxonomy
PASSED: test_miss_taxonomy_schema_rejects_missing_required_does_not_prove_entry
PASSED: test_miss_taxonomy_schema_rejects_missing_required_by_type_key
```

### Integration with Context Quality (B1)

- ✅ `context_quality.py` NOT modified
- ✅ B1 projection NOT affected
- ✅ No B1 tests required updates
- ✅ `claim_boundaries` in retrieval_eval remain unchanged

## Non-Changes (Preserved)

- ✅ Query execution behavior (unchanged)
- ✅ Ranking algorithm (unchanged)
- ✅ Chunking/indexing semantics (unchanged)
- ✅ Context Quality core semantics (unchanged)
- ✅ Output health semantics (unchanged)
- ✅ Post-emit health semantics (unchanged)
- ✅ Agent export gate behavior (unchanged)
- ✅ Manifest registration semantics (unchanged)
- ✅ Dependencies (no new packages added)

## Artifacts Modified

| File | Change |
|------|--------|
| `merger/lenskit/contracts/retrieval-eval.v1.schema.json` | Added `miss_taxonomy` field (optional) |
| `merger/lenskit/retrieval/eval_core.py` | Added `classify_miss()`, `build_miss_taxonomy()`, integrated into `do_eval()` |
| `merger/lenskit/tests/test_retrieval_eval.py` | Added/updated B2-specific tests (including query-execution-error and schema-shape guards); full retrieval_eval suite passes |
| `docs/proofs/retrieval-miss-taxonomy-proof.md` | Added and updated proof evidence |

## Proof Conclusion

**B2 Retrieval Miss Taxonomy is READY for merging.**

The diagnostic classification layer:
- ✅ Mechanically classifies retrieval misses without truth claims
- ✅ Preserves all existing retrieval metrics unchanged
- ✅ Maintains strict epistemic boundaries via `does_not_prove`
- ✅ Passes all schema validation tests
- ✅ Achieves full backward compatibility
- ✅ Requires NO changes to B1 or other systems
- ✅ Does NOT implement ranking improvements

Misses are now explainable without claiming repository absence or semantic truth.

---

**Gate Status:** ✅ **PASSED**  
**Recommendation:** Merge feature/b2-retrieval-miss-taxonomy → main
