# ADR 009: Atlas FTS Search Index

## Status
Accepted

## Context
Phase 4 of the Atlas Blaupause ("Suchschicht") requires that file inventories
be searchable system-wide via the registry and an index, rather than by
linearly re-reading and re-parsing every `inventory.jsonl` from the live
filesystem on each query (the prior best-effort transitional state in
`merger/lenskit/atlas/search.py`). ADR-005 already commits Atlas to "registry
in SQLite, large artifacts as files", and SQLite FTS5 is established in the repo
for Lenskit chunks (`chunks_fts`). The design note
`docs/architecture/atlas-fts-integration.md` enumerated four architectural
decisions that had to be made before implementation. This ADR records those
decisions.

## Decision

### 1. Index cut — global
A single global index lives at `<atlas_base>/indexes/fts.sqlite` (per ADR-008).
Every row references its origin snapshot via `machine_id`, `root_id`, and
`snapshot_id`, so cross-machine and cross-root queries are native. We do not
generate isolated per-snapshot FTS files; the isolation cost outweighs the
benefit at the current scale, and a global index keeps "latest per root"
resolution cheap.

### 2. Write path — derive (post-snapshot), with full rebuild
The index is updated as a **derivation step** after a snapshot is written and
marked `complete` (ADR-003 pipeline stage 4). Indexing is **best-effort**: a
failure to index never invalidates an otherwise-complete snapshot, because
search transparently falls back to a linear inventory scan when the index is
missing or does not cover a candidate snapshot. A full rebuild from the
registry is available via `atlas index rebuild` as the canonical
fallback/repair path.

### 3. Deletion / tombstone model — hard delete keyed by snapshot_id
Re-indexing a snapshot first hard-deletes its existing rows, making the
operation idempotent. There are no soft tombstones: a file that disappears in a
newer snapshot simply does not appear in that snapshot's rows. Validity against
the registry is guaranteed by `atlas index rebuild` (which clears and
re-derives from the set of `complete` snapshots) and by the search layer, which
only queries snapshot ids it has resolved from the registry.

### 4. Default query semantics — latest-only, with explicit historical opt-in
`atlas search` resolves, by default, to the newest indexed snapshot per
`(machine_id, root_id)` — mirroring the prior "latest per root" behavior.
Callers opt into historical search across all snapshots via `--all-snapshots`,
or pin a specific point in time via `--snapshot-id`.

### Content search — FTS-narrow + live-confirm hybrid
For content-mode snapshots (`content_ref` present) the file text is indexed in
the FTS `content` column. A `--content-query` first uses an FTS `MATCH` (tokens
AND-joined) to **narrow** the candidate set, then reads the live file to
**confirm** the exact contiguous-substring match and to build the snippet. This
preserves the prior content-search semantics (case-insensitive substring, first
matching line, 200-char snippet) while avoiding a read of every text file.
Snapshots scanned without content enrichment have no indexed content; for those,
content queries fall back to scanning the (already metadata-narrowed) candidate
set against the live filesystem. Content search therefore remains explicitly
best-effort with respect to live-filesystem reproducibility, consistent with the
Blaupause.

## Consequences
- Metadata/path/name/size/date searches are served from indexed SQLite columns
  instead of re-parsing JSONL, which is the scalability win Phase 4 demands.
- The index is a pure derivation artifact: it can be deleted and rebuilt at any
  time without data loss, and its absence degrades gracefully to the linear
  scan.
- `atlas search` gains `--all-snapshots` (historical) and `--no-index` (force
  linear) flags; `atlas scan` gains `--no-index` to skip derivation.
- A new `atlas index` command group (`rebuild`, `stats`) manages the index.
