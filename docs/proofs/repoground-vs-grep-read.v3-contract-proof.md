# RepoGround vs grep/read v3 — measurement-contract proof

Scope: current benchmark measurement semantics only. This proof does **not**
claim a new full-repository performance result.

## Current contract

`scripts/benchmarks/repoground_vs_grep_read.py` emits
`repoground_vs_grep_read_benchmark` version `v3`.

- The canonical CLI default remains `docs/retrieval/review_queries.v1.json`.
- `review_queries.v2.json` is opt-in and separates locator targets
  (`expected_paths`) from source evidence (`expected_evidence`).
- Legacy `expected_patterns` remains all-path for backward-compatible scoring.
- The grep/read response now contains the bounded source content actually read,
  so its `response_bytes` and bytes/4 token proxy charge that delivered text.
- Oracle reads used only to score expected evidence are not counted as condition
  tool calls or payload; the report exposes that limitation.

## Deterministic current fixture measurement

The committed benchmark regression fixture contains exactly this source file:

```text
def widget():
    return 'widget'
```

Its UTF-8 source payload is **34 bytes**. With ripgrep disabled, the current
`python_utf8_substring` fallback returns one path and one bounded read. The
canonical compact-JSON measurement of that grep/read result is **211 response
bytes**, yielding a bytes/4 token proxy of **53**. The response includes the
34-byte source content rather than only a `bytes_read` counter.

These values are deterministic for the committed fixture and current response
shape; the regression tests verify the source content itself, the explicit
locator/evidence split, the canonical v1 default, root-level legacy path
handling, and that every v2 evidence anchor occurs in at least one intended
expected file.

## Full-repository boundary

The repository does not commit a `bundle.index.sqlite`. A new full-repository
v3 comparison therefore requires a fresh local RepoGround bundle/index plus the
matching source tree. Until that run is produced and hash-bound, the historical
`repoground-vs-grep-read.v2.json` remains evidence only for the old v2 harness.
Its payload totals are not current v3 measurements and must not be used to
claim a v3 preference.

Current v3 product-level outcome: **unmeasured / no recommendation**.
