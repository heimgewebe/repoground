# RepoBrief Agent Memory Citations v1 Proof

Status: complete
Bureau task: `RPU-V1-T015`

## Result

This slice defines a deterministic pattern for durable agent memory that stores a remembered claim only together with RepoBrief citation evidence and snapshot freshness identity.

Added surfaces:

- `merger/lenskit/core/repobrief_memory.py`
- `merger/lenskit/tests/test_repobrief_memory.py`

## Contract

A memory record has:

- `claim_text`: the remembered claim text.
- `evidence.snapshot.stem`: the RepoBrief snapshot stem used when the memory was stored.
- `evidence.snapshot.hash`: the recorded snapshot hash.
- `evidence.snapshot.freshness_status`: the freshness status at storage time.
- `evidence.citations[]`: citation ids plus hash-bearing source ranges.
- `recall_policy.requires_revalidation=true`.

## Recall check

`check_memory_recall()` returns `usable` only when all of these hold:

1. Current snapshot hash matches the recorded snapshot hash.
2. Current freshness status is `fresh`.
3. Every recorded citation id is present in current evidence.
4. Every recorded citation range content hash still matches.
5. Every recorded citation range identity still matches, including path, byte range, optional line/source fields and optional `repo_id`.

Missing, stale, changed, conflicting or unverifiable evidence returns `unusable` and `presentation_policy=do_not_present_as_source_truth`. Projection imports fail closed when unresolved or malformed projection items are present.

## Boundary

The memory record is not source truth. It is a recall handle that must be revalidated against current RepoBrief evidence before reuse.

Does not establish:

- claim truth
- repository completeness
- runtime behavior
- test sufficiency
- review completeness
- freshness against remote beyond the supplied freshness evidence
- persistence-store behavior
- cross-process memory lifecycle behavior
