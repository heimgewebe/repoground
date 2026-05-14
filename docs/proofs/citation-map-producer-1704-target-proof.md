# Citation Producer Target Proof (1704)

- Date: 2026-05-14
- Dump stem: `lenskit-max-260514-1704_merge`
- Bundle manifest: `/home/alex/repos/merges/lenskit-max-260514-1704_merge.bundle.manifest.json`

## Repo and Runtime Proof

- HEAD short: `b7461e74`
- HEAD commit: `b7461e74 devcontainer: enforce strict UID/GID guard for lifecycle hooks`
- PR #660 merge commit present locally: `41071279 Merge pull request #660 from heimgewebe/fix/rlens-worktree-exclude-diagnosis`
- Runtime guard symbol present in `merger/lenskit/core/merge.py`:
  - `def _is_runtime_worktree_path(rel_path: str) -> bool`
- Functional guard checks:
  - `.claude/worktrees/foo/x.py` => `True`
  - `.claude/settings.local.json` => `False`

## Manifest Integrity

- Manifest artifacts: `8`
- Existence check: `8/8 OK`
- Byte-size check: `8/8 OK`
- SHA-256 check: `8/8 OK`
- Result: `PASS`

## Output Health

- File: `/home/alex/repos/merges/lenskit-max-260514-1704_merge.output_health.json`
- verdict: `pass`
- errors: `[]`
- warnings: `[]`
- chunk_count: `607`
- sqlite_row_count: `607`
- sqlite_fts_row_count: `607`
- fts_content_non_empty: `true`
- fts_empty_row_count: `0`
- range_ref_resolution_status: `ok`

## Structured Worktree Contamination Check

Structured path inspection performed against:

- Manifest `artifacts[].path`
- Sidecar and JSON artifacts (`path`, `file_path`, nested structured range fields)
- Dump index artifact paths
- Chunk index fields:
  - `path`
  - `file_path`
  - `canonical_range.file_path`
  - `content_range_ref.file_path`
  - `source_range.file_path`

Result:

- Structured path hits with prefix `.claude/worktrees`: `0`
- Hard contamination verdict: `PASS`

Important distinction:

- Raw text occurrences of `.claude/worktrees` in code/tests/docs/proof text are expected and not contamination evidence.
- Only structured path-field contamination is a failure condition.

## Chunk Index and Range Proof

- File: `/home/alex/repos/merges/lenskit-max-260514-1704_merge.chunk_index.jsonl`
- JSONL lines: `607`
- Invalid JSON lines: `0`
- Missing `chunk_id`: `0`
- `canonical_range` present: `607/607`
- `content_range_ref` present: `607/607`
- `source_range` present: `607/607`
- `canonical_range.file_path == lenskit-max-260514-1704_merge.md`: `607/607`
- `sha256(md_bytes[start_byte:end_byte]) == canonical_range.content_sha256`: `607/607`
- Line plausibility against canonical-md byte domain: `607/607`

## SQLite and FTS Proof

- File: `/home/alex/repos/merges/lenskit-max-260514-1704_merge.chunk_index.index.sqlite`
- `chunks` rows: `607`
- `chunks_fts` rows: `607`
- Empty FTS content rows: `0`
- FTS content length min/avg/max: `9 / 5100.99 / 8192`
- Consistency with output_health: `PASS`

## Citation Producer Proof

Command:

```bash
python3 -m merger.lenskit.cli.main citation produce --json \
  /home/alex/repos/merges/lenskit-max-260514-1704_merge.bundle.manifest.json \
  --output /home/alex/repos/merges/lenskit-max-260514-1704_merge.citation_map.jsonl
```

Result:

- status: `ok`
- error_kind: `ok`
- chunk_count: `607`
- valid_chunk_count: `607`
- citation_map_row_count: `607`
- citation_id_duplicate_count: `0`
- errors: `[]`
- warnings: `[]`

## Citation-Map Schema Validation

- Citation map file: `/home/alex/repos/merges/lenskit-max-260514-1704_merge.citation_map.jsonl`
- Schema: `merger/lenskit/contracts/citation-map.v1.schema.json`
- Rows validated: `607`
- Schema errors: `0`
- Result: `PASS`

## Final Decision

All stop criteria are satisfied:

- Manifest hash/bytes: `PASS`
- output_health verdict pass: `PASS`
- Chunk/SQLite/FTS 607/607/607 consistency: `PASS`
- Structured `.claude/worktrees` paths: `0`
- Citation producer status ok: `PASS`
- Citation-map schema-valid rows: `607`
- Citation-ID duplicates: `0`

Overall verdict: `PASS`.