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
20-question `docs/retrieval/review_queries.v2.json` by default and an existing
local index:

```bash
python3 scripts/benchmarks/repoground_vs_grep_read.py \
  --index /absolute/path/to/bundle.index.sqlite \
  --repo-root "$PWD" \
  --out /tmp/repoground-vs-grep-read.json
```

The current harness emits report contract v5. The default v2 question contract
separates `expected_paths` from `expected_evidence`; the historical v1 contract
remains explicitly runnable with
`--questions docs/retrieval/review_queries.v1.json` and retains its all-path
`expected_patterns` meaning. Each v5 report records the selected question
contract plus a repository-relative question path when that input is inside the
measured repository; external absolute question paths are not persisted.

The grep/read condition includes the bounded source content it actually reads in
its measured response payload, so current `response_bytes` and token-proxy values
are intentionally not comparable to older harness versions that used different
payload accounting.

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

## Historical v2 measurement

The committed `repoground-vs-grep-read.v2.json` is a **historical measurement
from the v2 harness**. It remains immutable evidence for that earlier harness,
not a current performance claim. Its recorded numbers were: 20 fixed questions;
RepoGround missed 37 expected targets versus 60 for `grep/read`; both conditions
had 20 false-confidence cases; RepoGround used 551.335 ms versus 166.691 ms,
emitted 292,150 raw bytes, and its 98,966-byte compact form was larger than the
then-recorded 26,690-byte baseline.

Those payload totals must not be compared with current v5 runs. v3 changed
visible-payload accounting, v4 corrected comparator fairness, and v5 promotes
the explicit locator/evidence question contract. Their historical contracts are
preserved in `repoground-vs-grep-read.v3-contract-proof.md` and
`repoground-vs-grep-read.v4-contract-proof.md`; current hash-bound default and
legacy readbacks are documented in `repoground-vs-grep-read.v5-contract-proof.md`.

The historical v2 measurement recommends no category and caused no default
activation. The current benchmark still does not claim repository understanding,
answer correctness or quality beyond the measured cases.
