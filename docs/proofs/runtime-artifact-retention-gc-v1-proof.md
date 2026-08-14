# Runtime Artifact Manual GC v1 — T018 proof

This proof records the implementation boundary for Bureau task `REPOGROUND-AGENT-UTILITY-V1-T018`. It supersedes only the historical statement that no manual GC path existed; the lookup contract from `runtime-artifact-retention.v1` remains unchanged.

## Policy and budgets

`runtime-artifact-manual-gc.v1` is opt-in. It has no scheduler and `automatic_delete=false`. The conservative profile uses:

| Artifact type | Max age | Max count | Max bytes |
|---|---:|---:|---:|
| `query_trace` | 90 days | 25,000 | 512 MiB |
| `context_bundle` | 90 days | 10,000 | 2 GiB |
| `agent_query_session` | 180 days | 25,000 | 512 MiB |

Crossing a budget creates only a dry-run candidate. Stored artifact metadata remains `retention_policy=unbounded_currently`, `ttl_enabled=false`, `gc_enabled=false`; lookup never expires or removes an artifact.

## Plan-before-effect

`runtime_artifact_gc_plan.py` builds deterministic plans from one exact store SHA-256. Each candidate records its ID, type, created time, estimated bytes, entry hash and all applicable budget reasons. `plan_sha256` binds the entire plan. Apply rejects a changed plan or changed store preimage.

## Reference protection

Protection evidence must declare `reference_state=complete`. Unknown global or external-reference state blocks fail-closed. Pins and nonterminal external references are protected. Active `agent_query_session` artifacts protect themselves plus referenced `query_trace_id` and `context_bundle_id`; missing or malformed session references also block. A newly protected candidate between plan and apply is skipped rather than deleted.

## Race, filesystem and recovery safety

`RuntimeArtifactGCStore` and normal `QueryArtifactStore` writes share `.query_artifacts.lock`. Normal writers reload the store from disk under that lock, so a stale process cannot resurrect a GC-removed entry. Rooted filesystem primitives use no-follow descriptor-bound reads/writes. Storage, transaction, receipt and store entries are owner/type checked.

Before the store effect, Apply writes a transaction record containing pre/post hashes and the intended receipt body. After the effect it re-reads the store, verifies the post hash and checks protected IDs. If the effect completed but its final receipt is missing, the next exact replay reconstructs the receipt idempotently. Other normal store writes remain blocked while an unfinished transaction lacks its receipt.

## Acceptance mapping

- `policy-profiles`: explicit age/count/byte budgets; automatic deletion remains disabled.
- `plan-before-effect`: deterministic dry-run, candidate reasons, expected release and exact plan/store binding.
- `reference-protection`: active sessions, their artifact graph, pins and nonterminal external evidence are protected; unknown state blocks.
- `safe-gc`: inter-process lock, no-follow rooted filesystem operations, ownership checks, transaction/receipt ledger and idempotent recovery.
- `retention-readback`: receipt reports deleted objects/bytes; store post-hash and protected-artifact readability are rechecked.

## Regression evidence

Dedicated tests live in `merger/repoground/tests/test_runtime_artifact_gc.py`; legacy retention tests remain in `test_runtime_artifact_retention.py`. Merge-grade evidence is provided by the PR-bound CI and exact-head test receipts.
