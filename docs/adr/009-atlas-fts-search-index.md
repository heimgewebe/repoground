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

### Content search — metadata index + live-confirm (no FTS content filter)
For content-mode snapshots (`content_ref` present) the file text is indexed in
the FTS `content` column as a **prepared structure** for potential future use.
It is **not** used as a hard pre-filter for content queries.

**Why FTS content is not used as a narrowing gate:** The FTS `content` column
captures the file text at indexing time. If a live file changes after indexing
(writes, edits, replacements), the indexed content is stale while the live file
reflects new content. Using FTS content as a pre-filter would exclude such files
from reaching the live-confirmation step (`_content_match`), producing silent
false negatives — the live file contains the query string but the index does
not, so the file is never confirmed and disappears from results.

**Actual search path:** For all content queries, `_try_index_search` uses only
the metadata-indexed SQLite columns (`ext`, `size_bytes`, `mtime_epoch`, scope)
to narrow the candidate set. Every resulting file then goes through
`_content_match`, which reads the current live file and performs the exact
case-insensitive substring check. The live confirmation is always the source of
truth. Content search therefore remains explicitly best-effort with respect to
live-filesystem reproducibility (consistent with the Blaupause), while never
producing false negatives from index staleness.

Snapshots scanned without content enrichment (`content_ref` absent) receive
the same treatment: all metadata-filtered candidates are live-scanned.

`fts_content_candidates` remains in `index.py` as a primitive that could
accelerate content narrowing in a future write-once / immutable-snapshot
scenario where content staleness cannot occur. It is presently unused by the
search path.

## Consequences
- Metadata/size/date/scope filtering is served from indexed SQLite columns
  instead of re-parsing JSONL each query, which is the scalability win Phase 4
  demands. Glob/name/path exactness (and the `query` substring) remain a Python
  post-filter over the SQL-narrowed candidate rows — they are NOT delegated to
  FTS — so their semantics are byte-for-byte identical to the linear path.
- Content queries always reach `_content_match` for every metadata-filtered
  candidate, so live file mutations after indexing are transparently reflected
  in results. The FTS `content` column is a prepared structure, not a gate.
- The index is a pure derivation artifact: it can be deleted and rebuilt at any
  time without data loss, and its absence degrades gracefully to the linear
  scan.
- `atlas search` gains `--all-snapshots` (historical) and `--no-index` (force
  linear) flags; `atlas scan` gains `--no-index` to skip derivation.
- A new `atlas index` command group (`rebuild`, `stats`) manages the index.
