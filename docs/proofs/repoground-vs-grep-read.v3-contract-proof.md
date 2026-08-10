# RepoGround vs grep/read v3 — historical measurement-contract proof

Status: **superseded by v4**. This document freezes the exact v3 measurement
contract and must not be reinterpreted through the current v4 helper behavior.
It does **not** establish a current product preference.

## Historical v3 contract

Before the v4 comparator correction,
`scripts/benchmarks/repoground_vs_grep_read.py` emitted
`repoground_vs_grep_read_benchmark` version `v3`.

- The canonical CLI default was `docs/retrieval/review_queries.v1.json`.
- `review_queries.v2.json` was opt-in and separated locator targets
  (`expected_paths`) from source evidence (`expected_evidence`).
- Legacy `expected_patterns` remained all-path for backward-compatible scoring.
- Evidence was scored only from content exposed by the compared condition:
  RepoGround exposed the selected indexed chunk content; grep/read exposed only
  the bounded source bytes returned in its reads.
- Evidence could satisfy a case only when that visible payload belonged to a
  returned path matching one of the case's `expected_paths`; an unrelated hit
  could not supply evidence for a different expected path.
- The grep/read response contained the bounded source content actually read, so
  its `response_bytes` and bytes/4 token proxy charged that delivered text.
- No full-file scoring oracle was used. Text outside a selected RepoGround chunk,
  outside grep/read's bounded payload, or on an unrelated returned path could
  satisfy `expected_evidence`.

## Frozen deterministic v3 fixture measurement

The v3 regression fixture contained exactly this source file:

```text
def widget():
    return 'widget'
```

Its UTF-8 source payload is **34 bytes**. With ripgrep disabled, the v3
`python_utf8_substring` fallback returned one path and one bounded read. The
canonical compact-JSON measurement of that **v3 response shape** is **211
response bytes**, yielding a bytes/4 token proxy of **53**. The response includes
the 34-byte source content rather than only a `bytes_read` counter.

The 211-byte value is deliberately frozen as historical evidence. The current
v4 response shape contains additional ranking and leakage-control metadata and
is therefore expected to have a different byte count. The v3 proof regression
test reconstructs this frozen response shape directly instead of calling the
current comparator and thereby silently rewriting history.

## Full-repository boundary

A fresh full-repository v3 run was produced on 2026-08-10, but the subsequent v4
review exposed two material comparator contaminants: query-order truncation in
the grep/read baseline and eligibility of self-measurement artifacts. The v3
full-repository totals therefore remain diagnostic evidence for that exact old
harness only and must not be used for a current product-preference claim.

Current product decisions must use the v4 contract and a fresh hash-bound v4
run. Historical v3 product-level outcome: **no valid recommendation**.
