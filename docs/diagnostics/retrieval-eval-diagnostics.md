# Retrieval Evaluation Diagnostics

## Purpose

**What it does:** Classifies retrieval evaluation misses into diagnostic categories to explain why queries did not find expected targets.

**What it does NOT do:**
- ❌ Fix ranking scores or rerank results
- ❌ Modify retrieval metrics (recall, MRR, etc.)
- ❌ Change the gold set or query definitions
- ❌ Propose improvements to the index, BM25, or chunking
- ❌ Claim that a "fix" has been applied

## Diagnostic Categories

When a retrieval evaluation miss occurs, the calibrator determines the primary root cause:

| Category | Meaning |
|----------|---------|
| **target_in_top_k** | Expected target found in top-k results (not a miss). |
| **target_exists_not_in_top_k** | Target exists in the index but was not observed in top-k. Without overfetch, absolute outside-top-k rank is unknown. **Problem type:** Ranking/relevance. |
| **target_missing_from_index** | Target path/identifier not in the chunk index at all. **Problem type:** Index/ingestion. |
| **target_missing_from_canonical** | Target path not in canonical_md artifact. **Problem type:** Artifact gap or stale reference. |
| **target_missing_from_citation_map** | Target not reachable via citation_map_jsonl. **Problem type:** Citation gap. |
| **stale_expected_target** | Expected target has staleness indicators (e.g., `/tmp/`, obsolete naming). **Problem type:** Gold set stale. |
| **query_target_ambiguous** | Query or target definition is ambiguous or malformed. **Problem type:** Input quality. |
| **diagnostic_inconclusive** | Miss could not be conclusively classified (e.g., all artifacts unavailable). **Problem type:** Instrumentation gap. |

## How It Works

### 1. Input: Query Miss

A miss occurs when:
- A query was executed
- An expected target was in the gold set
- The target was **not** found in the top-k results

Example:
```json
{
  "metrics": {
    "total_queries": 1
  },
  "details": [
    {
      "query": "merge",
      "expected": ["merge.py", "iter_report_blocks"],
      "is_relevant": false,
      "found_count": 1,
      "top_results": ["merger/lenskit/core/chunker.py"]
    }
  ]
}
```

### 2. Diagnostic Check

The calibrator asks five questions in sequence:

```
┌─ Has staleness or ambiguity signals?
│  └─ Stale → "stale_expected_target"
│  └─ Ambiguous → "query_target_ambiguous"
│  └─ None → next
│
├─ Is target in the index?
│  └─ No → "target_missing_from_index"
│  └─ Yes → next
│
├─ Is target in canonical_md?
│  └─ No → "target_missing_from_canonical"
│  └─ Yes → next
│
├─ Is target in citation_map?
│  └─ No → "target_missing_from_citation_map"
│  └─ Yes → next
│
├─ Is target in index but not observed in top-k?
│  └─ Yes → "target_exists_not_in_top_k" (not observed in top-k)
│  └─ No → next

└─ Else → "diagnostic_inconclusive"
```

### 3. Output: Diagnostic Report

```json
{
  "authority": "diagnostic_signal",
  "risk_class": "diagnostic",
  "metadata": {
    "version": "1.0",
    "timestamp": "2026-05-26T12:00:00Z",
    "total_misses": 47,
    "diagnostic_breakdowns": {
      "target_in_top_k": 0,
      "target_exists_not_in_top_k": 12,
      "target_missing_from_index": 5,
      "target_missing_from_canonical": 2,
      "target_missing_from_citation_map": 0,
      "stale_expected_target": 3,
      "query_target_ambiguous": 1,
      "diagnostic_inconclusive": 24
    },
    "index_stats": {
      "total_chunks": 1250,
      "total_paths": 412,
      "canonical_md_exists": true,
      "citation_map_exists": true
    }
  },
  "diagnostics": [
    {
      "query_id": "q5",
      "query_text": "how to configure auth",
      "expected_target": "src/auth/setup.py",
      "primary_diagnosis": "target_exists_not_in_top_k",
      "diagnosis_details": {
        "target_found_in_index": true,
        "target_found_in_canonical": true,
        "target_found_in_citation_map": true,
        "rank_in_results": null,
        "top_k": 10,
        "query_had_zero_hits": false,
        "canonical_path_check": "exact_match",
        "possible_path_variants": [],
        "staleness_indicator": "none",
        "secondary_diagnoses": ["low_query_specificity"],
        "confidence": "high",
        "instrumentation_notes": null
      }
    }
  ]
}
```

Optional overfetch diagnostics example (explicitly separate from default top-k-only diagnostics):

```json
{
  "query_id": "q5",
  "expected_target": "src/auth/setup.py",
  "primary_diagnosis": "target_exists_not_in_top_k",
  "diagnosis_details": {
    "rank_in_results": 45,
    "top_k": 10,
    "instrumentation_notes": "rank_in_results available from overfetch diagnostics run (k=100)"
  }
}
```

## Decision Framework: What Each Diagnosis Means

### target_exists_not_in_top_k

**Interpretation:**  
The target exists in the index and canonical artifacts but was not observed in the top-k results. This is a **ranking/top-k observation problem**, not an indexing or artifact problem.

Without an additional overfetch diagnostics run (for example top-50/top-100), this signal does not claim an absolute outside-top-k rank.

**Next steps for remediation:**
- Inspect the query embedding or BM25 scoring
- Check if the target matches the query semantically
- Consider if query vocabulary differs from target content
- Analyze if filter criteria are too restrictive

**NOT a fix target:** Index, chunking, canonicalization, citation mapping

---

### target_missing_from_index

**Interpretation:**  
The expected target path does not exist in the chunk index. The content was not ingested or was filtered out.

**Next steps:**
- Check if the path was in the source repository during indexing
- Verify path_filter or include_paths_by_repo settings
- Check if the file was skipped due to file size or format
- Verify if the chunking step has a bug

**NOT a fix target:** Query, ranking, reranking

---

### target_missing_from_canonical

**Interpretation:**  
The target is in the index but not in canonical_md. This indicates an artifact consistency gap.

**Next steps:**
- Verify that canonical_md is up-to-date with the index
- Check if canonical_md was created before the index
- Inspect citation_map_jsonl for the target's cross-references
- May indicate a CI/build ordering issue

**NOT a fix target:** Ranking, query

---

### target_missing_from_citation_map

**Interpretation:**  
The target is in the index and canonical but not reachable via the citation map.

**Next steps:**
- Check citation_map generation logic
- Verify if citation_validate passes
- Inspect if the target has citation_id conflicts

**NOT a fix target:** Ranking, query

---

### stale_expected_target

**Interpretation:**  
The expected target has staleness indicators (e.g., path in `/tmp/`, old date formats, deprecated naming). The gold set may refer to historical snapshots.

**Next steps:**
- Review the gold set for outdated expected paths
- Check if the query is still relevant
- Verify if the target was renamed or moved
- Consider if the query should target a newer path instead

**NOT a fix target:** Ranking, index

---

### query_target_ambiguous

**Interpretation:**  
The query or target definition is malformed or ambiguous.

**Next steps:**
- Review the query definition in the gold set
- Check if the expected_target is well-formed (non-empty, valid path)
- Verify if there are special characters or encoding issues

**NOT a fix target:** Ranking, index

---

### diagnostic_inconclusive

**Interpretation:**  
The miss could not be conclusively classified. This typically occurs when:
- Artifacts are unavailable (canonical_md, citation_map, index)
- Multiple conflicting signals exist
- Instrumentation is incomplete

**Next steps:**
- Ensure all required artifacts (index, canonical_md, citation_map) are available
- Check diagnostic logs for instrumentation gaps
- Re-run diagnostics after artifact repair

---

## Integration

### Standalone Usage

```python
from pathlib import Path
from merger.lenskit.retrieval.eval_diagnostics import RetrievalEvalDiagnosticsCalibrator

# Initialize with artifact paths
calibrator = RetrievalEvalDiagnosticsCalibrator(
    index_path=Path("data/chunks.jsonl"),
    canonical_path=Path("data/canonical.md"),
    citation_path=Path("data/citation_map.jsonl"),
)

# Define misses
misses = [
    {
        "query_id": "q1",
        "query_text": "find auth setup",
        "expected_target": "src/auth/setup.py",
        "found_in_results": False,
        "rank_in_results": None,
        "top_k": 10,
        "query_had_zero_hits": False,
    },
]

# Generate report
report = calibrator.generate_report(misses)

# Save to file
calibrator.save_report(report, Path("diagnostics_report.json"))
```

### Integration with eval_core

```python
from merger.lenskit.retrieval.eval_diagnostics_integration import (
    integrate_diagnostics_with_eval_results,
)

# Run existing evaluation
eval_results = do_eval(
    index_path=Path("data/index.sqlite"),
    queries_path=Path("queries.md"),
    k=10,
)

# Attach diagnostics
combined = integrate_diagnostics_with_eval_results(
    eval_results,
    index_path=Path("data/chunks.jsonl"),
    canonical_path=Path("data/canonical.md"),
    citation_path=Path("data/citation_map.jsonl"),
    output_path=Path("combined_results.json"),
)

# combined["eval_results"] = original metrics (unchanged)
# combined["diagnostics_report"] = diagnostic classifications
```

The integration consumes retrieval eval objects from `details`, not `results`.

## Schema Compliance

The diagnostics output conforms to `retrieval-eval-diagnostics.v1.schema.json`:

```bash
# Validate a generated report
python3 -c "
import json
import jsonschema
from pathlib import Path

report = json.loads(Path('diagnostics_report.json').read_text())
schema = json.loads(Path('merger/lenskit/contracts/retrieval-eval-diagnostics.v1.schema.json').read_text())

jsonschema.validate(instance=report, schema=schema)
print('✓ Report valid')
"
```

## Testing

Run the diagnostic test suite:

```bash
python -m pytest merger/lenskit/tests/test_retrieval_eval_diagnostics.py -v
```

Key test scenarios:
- ✓ target_in_top_k (hit, not a miss)
- ✓ target_exists_not_in_top_k (ranking problem)
- ✓ target_missing_from_index (indexing problem)
- ✓ target_missing_from_canonical (artifact gap)
- ✓ stale_expected_target (gold set stale)
- ✓ query_target_ambiguous (input quality)
- ✓ schema compliance
- ✓ deterministic sorting
- ✓ artifact availability graceful degradation

## Limitations & Caveats

1. **Requires artifacts:** If index, canonical_md, or citation_map are unavailable, diagnostics default to `diagnostic_inconclusive`.

2. **Partial path matching:** The calibrator uses substring matching for path comparisons. Exact matching may require additional metadata.

3. **Secondary diagnoses are informational:** Only `primary_diagnosis` represents the root cause. Secondary diagnoses provide context but are not definitive.

4. **No semantic analysis:** The calibrator does not evaluate query/target semantic similarity. Ranking problems require separate semantic evaluation.

5. **Gold set assumed correct:** Diagnostics do not validate the gold set itself. Stale or incorrect expected targets are flagged as "stale" or "ambiguous" but not audited.

## Authority & Risk Classification

Per the schema:
- **authority:** `diagnostic_signal` (diagnostic only, not authoritative)
- **risk_class:** `diagnostic` (informational, not a decision gate)

Diagnostics do **not**:
- Prove absence of content in the repository
- Prove semantic relevance or ranking correctness
- Justify fixing ranking, reranking, or synonym tables
- Supersede manual review or authority decision-making

They **do**:
- Separate indexing from ranking problems
- Guide the next investigation step
- Enable targeted root-cause analysis
- Reduce false diagnoses

## Future Enhancements

Potential additions (not in v1.0):
- Semantic similarity scoring for ranking analysis
- Path variance detection (file renames, refactoring)
- Citation cycle detection
- Gold set completeness audit
- Query vocabulary/embedding analysis
