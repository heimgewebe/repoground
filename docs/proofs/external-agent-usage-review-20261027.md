# External agent usage review — 2026-10-27

Status: informal external usage note, hands-on, not a formal `self-review`/
`external-review` contract pair. No new artifact role, schema or contract is
introduced by this document.

Scope: an external agent session (Claude Code, no prior RepoGround context)
read the project docs, then exercised the CLI directly against RepoGround's
own `core/` and `retrieval/` sources to see whether an agent would actually
want to use RepoGround for codebase context, and where it falls short today.

## Method

Commands run against a clean checkout (`heimgewebe/lenskit`, `main`), reading
only; no repository mutation, no install, no network sync:

```
python3 -m repoground doctor
python3 -m repoground build merger/repoground/core merger/repoground/retrieval \
    --hub <scratch-hub> --level dev --output-mode retrieval --no-pre-pull
python3 -m repoground query --index <chunk_index.index.sqlite> \
    --q "how does canonical_md get resolved" --k 5 --explain --emit text
python3 -m repoground query --index <chunk_index.index.sqlite> \
    --q "resolve_canonical_md" --k 5 --emit text
```

## Findings

1. **`doctor` is trustworthy and side-effect-free.** It correctly reported a
   degraded `jsonschema` dependency, a missing PATH wrapper, and a non-pinned
   Python interpreter, without attempting to fix any of it. This matches the
   project's own stated "read-only, no silent repair" contract.
2. **`build` works end-to-end on a real slice.** A dev-level, retrieval-mode
   build of `core/` + `retrieval/` completed in well under two minutes and
   produced a manifest with per-artifact `sha256`, `contract`/`contract_version`,
   and role fields — real provenance, not decorative JSON.
3. **Natural-language query quality is weak in practice, consistent with the
   project's own measured number.** `--q "how does canonical_md get resolved"`
   lowered to the FTS query `canonical_md AND resolved` and returned
   `citation_map.py` / `ask_context.py` chunks — not `core/merge.py`, where
   `resolve_canonical_md` actually lives. This is the same signal already
   recorded in `docs/status/repobrief-status-truth.v1.json`
   (`TASK-REPOBRIEF-AUDIT-RETRIEVAL-MEASUREMENT-001`: recall@10 = 5.0%,
   expected-target baseline = 1.666667%, promotion blocked). This review did
   not re-run that benchmark; it reproduces the same qualitative symptom on a
   single ad-hoc query, which is corroborating, not new, evidence.
4. **Exact-identifier queries fare better but are still not first-ranked.**
   `--q "resolve_canonical_md"` surfaced `core/merge.py` chunks at rank 2–3,
   behind an unrelated `authority_upgrade_registry.py` chunk at rank 1 — BM25
   token splitting on the snake_case identifier appears to dilute the match.
5. **`core/merge.py` is very large** (observed via the chunking output: chunk
   ranges extend past line 7000). This is the same file already flagged by
   the existing graph-maintainability ratchet task; it is also the file that
   produced the misranked chunk in finding 4, which is a plausible (not
   proven) link between file size/granularity and chunk-level ranking noise.

## Recommendation (not implemented by this review)

- Intent/identifier pre-processing before the FTS query is built (stopword
  trim + identifier extraction) would directly address finding 3 and is
  cheap relative to introducing a full embedding reranker.
- Embedding-based reranking as a second stage behind BM25 is already named
  in the blueprint (`docs/repoground-upgrade-blaupause.md` §5.4/§1) but is not
  exercised by default; this review's result is one more concrete data point
  for prioritizing it before further feature breadth.
- `core/merge.py` size reduction is already tracked elsewhere
  (graph-maintainability ratchet); this review adds one concrete anecdote
  (finding 4/5) rather than a new task.

## STOP — what this review does not establish

- No code change, retrieval fix, or benchmark rerun was made or executed.
- No claim is made about recall/precision beyond the single ad-hoc query
  reproduced above; the quantitative number cited (5.0% / 1.666667%) is taken
  as-is from the existing `repobrief-status-truth.v1.json` and was not
  independently re-measured here.
- No judgment is made about product readiness, release readiness, or any
  other axis this repository's status truth already declares
  `not_established`.
- This note does not open or imply any new Bureau task; it is read-only
  external feedback for whoever triages `docs/proofs/`.
