# RepoGround Incremental Retrieval Snapshot v1

## Scope

`repoground retrieval-snapshot` is an explicit local write surface:

```bash
repoground retrieval-snapshot build --source . --storage ../.repoground-retrieval
repoground retrieval-snapshot full-verify --source . --storage ../.repoground-retrieval
repoground retrieval-snapshot status --storage ../.repoground-retrieval
repoground retrieval-snapshot watch --source . --storage ../.repoground-retrieval
```

`build` publishes a staged immutable generation and then atomically replaces
`current.json`. `full-verify` is also explicitly write-side: it refreshes when
needed and compares the committed rows to a from-scratch chunk build. `status`
only reads `current.json`, the committed `snapshot.json`, and optional
`watcher-status.json`; it never invokes build, recovery, verification or query
fallback.

The implementation is `IncrementalRetrievalSnapshot`; no additional snapshot
architecture or service-runtime gate is introduced. Source and storage roots
must not overlap, so generated generations can never be indexed as source input.
Every build takes an exclusive filesystem lock at `<storage>/.build.lock`; a
second writer waits for the first instead of racing the staging tree or
`current.json`. The lock is opened with `O_NOFOLLOW` where the platform provides
it, and the regression suite proves that a symlink cannot redirect the lock
write outside the storage root. Readers never take the writer lock and continue
to follow the last committed immutable generation.

## Optional watcher

`watch` is a separately started foreground process, is not installed/enabled by
default, and uses only the Python standard library. It polls file metadata and
lets the snapshot builder retain content-hash correctness. It queues an initial
explicit build plus subsequent changes, debounces them, bounds the queue,
coalesces events, and retries failures with exponential backoff capped by
`--max-backoff-seconds`. Startup removes abandoned staging directories; the last
published generation remains readable after a failed build. On every state
transition it atomically replaces `<storage>/watcher-status.json`, exposing
`running`, `backing_off`, `stopped`, or `crashed`, the last successful generation,
queue/failure counters, recovery count and last error.

## Local measurement

The checked-in [measurement report](repoground-incremental-retrieval-snapshot-v1.measurement.json)
was produced on this repository by:

```bash
python -m merger.repoground.cli.main retrieval-snapshot measure \
  --source . --storage /tmp/repoground-incremental-unused \
  --repo-id incremental-watch-v1 \
  --include-extension .py --include-extension .md --include-extension .json \
  --report docs/proofs/repoground-incremental-retrieval-snapshot-v1.measurement.json
```

It runs in a disposable copy, appends one harmless marker to a copied Python
file, and records full build, incremental change and no-op. The report binds the
source commit, complete input-tree SHA-256, before/after input fingerprints and
configuration fingerprint. It records wall time, CPU time, freshness latency,
written/read process IO from `/proc/self/io` when available, and output-tree byte
delta as an explicit portable approximation. Absolute source paths are not
persisted.

| Run | Wall time | Written bytes | Output-tree delta |
|---|---:|---:|---:|
| Full build | 0.431 s | 29,839,360 | 29,617,771 |
| One-file change | 0.353 s | 29,835,264 | 29,613,662 |
| No-op | 0.036 s | 0 | 0 |

The one-file change reuses the stored chunk rows for every unchanged file and
reduces wall time by about 18 percent in this local run. It does **not** yet make
artifact publication incrementally sparse: the immutable new generation still
writes a complete SQLite index and chunk artifact, so its write volume is almost
identical to the full build. The strong result is the no-op path, which writes
nothing. These are local observations, not a performance guarantee or evidence
that every repository benefits.

## Verification

- `python -m pytest merger/repoground/tests/test_incremental_retrieval_snapshot.py -q` (15 tests, including overlap, concurrent-writer and lock-symlink boundaries)
- `ruff check merger/repoground/retrieval/incremental_snapshot.py merger/repoground/cli/cmd_incremental_snapshot.py merger/repoground/tests/test_incremental_retrieval_snapshot.py`

