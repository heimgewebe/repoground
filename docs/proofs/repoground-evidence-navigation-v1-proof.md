# RepoGround Evidence Navigation v1 — Proof

Scope: Bureau #672 and #481 follow-up. This slice adds a read-only navigation
surface; it neither changes persisted, versioned identifiers nor reintroduces
public compatibility aliases.

## Delivered surface

- `repoground evidence-query --bundle-manifest <manifest> --q <query>` emits
  `repoground.compact_evidence_query/v1`.
- Every hit contains either one exact `live_path_line` from a citation's
  available `live_repo_address`, or an explicit deterministic
  `non_resolution_reason`. It never substitutes a snapshot/canonical line for
  a missing live address.
- The projection strips excerpts and diagnostics but retains citation/range
  state, source freshness and fallback information. It emits an explicit
  `compaction_pass`; the CLI fails if its full resolved result is not at least
  60 percent smaller.
- Ask's only zero-hit retry remains deterministic: content tokens now retain a
  snake_case identifier and its parts, form a quoted OR expression, and use
  the existing FTS5 BM25 result ordering.
- The Reading Pack contains `REPOSITORY_GUIDE`, including the navigation order,
  live-address boundary and compact command.

## Reproducible local benchmark

`scripts/benchmarks/repoground_vs_grep_read.py` consumes the committed
20-question `docs/retrieval/review_queries.v1.json` and an existing local index:

```bash
python3 scripts/benchmarks/repoground_vs_grep_read.py \
  --index /absolute/path/to/bundle.index.sqlite \
  --repo-root "$PWD" \
  --out /tmp/repoground-vs-grep-read.json
```

It uses only local `rg` plus bounded file reads through RepoGround's existing
review-intent FTS5/BM25 path. The v2 report hashes the index, fixed question
set and local source tree. For every one of the same 20–30 questions and the
same `k` limit, it records runtime, logical tool calls, spawned process calls,
bounded source reads, response bytes, a documented bytes/4 token proxy,
source/index freshness and false-confidence status. Aggregates contain the
same measures and the total compact-response reduction.

False confidence is recorded only when a condition returned a result and is
therefore presented as useful, while one or more expected targets are absent
or the checked source is stale/unavailable. RepoGround compact responses keep
chunk identity, path/line range, content hash/range reference, freshness and
fallback state.

The decision is fail-closed and has three outcomes:

- `pass` only when at least one named category has fewer missing gold targets,
  fresh evidence, zero false-confidence cases and passing compaction;
- `inconclusive` when measurement succeeds but no category meets that safe
  benefit contract;
- `fail` when compaction, freshness or relative quality regresses.

The committed local report `repoground-vs-grep-read.v2.json` is
`inconclusive`. On 20 fixed questions RepoGround missed 37 expected targets
versus 60 for `grep/read`, but both conditions had 20 false-confidence cases.
RepoGround used 566.081 ms versus 156.484 ms, emitted 292,150 raw bytes, and
its 98,966-byte compact form was still larger than the 26,274-byte baseline.
No category is recommended and no default activation follows from this slice.
The benchmark does not claim repository understanding, answer correctness or
quality beyond the measured cases.
