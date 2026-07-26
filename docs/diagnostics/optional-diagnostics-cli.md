# Optional RepoGround diagnostics CLI

The `repoground diagnostics` command exposes bounded diagnostic capabilities that are deliberately not part of normal indexing, querying, service, MCP, merge or publication flows.

## Why this surface exists

Several mature diagnostic modules had unit tests and proof documents but no product entrypoint. Keeping them indefinitely on the module-reachability exception list hid that gap. Deleting them based only on missing static callers would have been unsafe.

The explicit CLI gives each module a real consumer while preserving its authority boundary:

- every operation is opt-in;
- CLI-loaded JSON control inputs are bounded to 8 MiB and symbolic links are rejected;
- results are emitted as deterministic JSON;
- diagnostic outputs do not become repository truth, merge authority or review completeness evidence;
- normal RepoGround paths do not invoke these operations.

## Commands

### Revalidate answer grounding

```text
repoground diagnostics answer-delta \
  --old-declaration answer-grounding.json \
  --new-bundle-manifest bundle.manifest.json \
  --new-citation-map citation_map.jsonl
```

### Project a history lens

```text
repoground diagnostics history-lens \
  --records history-records.json \
  --profile summary
```

### Build and revalidate citation-bound memory

```text
repoground diagnostics memory-build \
  --claim-text "The remembered claim" \
  --citations citations.json \
  --snapshot-stem snapshot-20260726 \
  --snapshot-hash <64-hex-sha256> \
  --freshness-status fresh

repoground diagnostics memory-check \
  --memory-record memory.json \
  --current-citations citations.json \
  --current-snapshot-hash <64-hex-sha256> \
  --current-freshness-status fresh
```

### Plan audit lanes and bind candidate findings

```text
repoground diagnostics audit-plan \
  --changed-path src/auth/session.py \
  --review-query "authority boundary"

repoground diagnostics audit-findings \
  --plan audit-plan.json \
  --candidates candidates.json \
  --reviewed-revision <40-hex-commit> \
  --current-revision <40-hex-commit> \
  --citation-ids citation-ids.json
```

### Explain retrieval-evaluation misses

```text
repoground diagnostics eval-report \
  --eval-results retrieval-eval.json \
  --index chunk_index.jsonl \
  --canonical canonical.md \
  --citation citation_map.jsonl
```

## Deliberate limits

This CLI does not execute review agents, edit repositories, create issues, modify retrieval rankings, refresh snapshots, approve findings, grant merge permission or establish completeness. Inputs and revision identities remain the caller's responsibility; live GitHub, CI and working-tree state must be checked separately.
