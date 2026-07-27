# REPOGROUND-LEGACY-RECONCILIATION-V1-T004 / T011 bundle-access proof

## Scope and revision binding

This slice decomposes the read-only `merger/repoground/core/bundle_access.py`
surface without changing its public entry-point names, default verbose behavior
or compact/MCP projections. It is based on commit
`a029bbcd2779e7bed1ac41e936bdf720249f0538` and tree
`0768606f5ea218b7a188c598be590ab2738bb583`. Per task instruction, the result is
an uncommitted, reviewable dirty worktree. The adjacent machine-readable
measurement is
`docs/proofs/repoground-legacy-t011-bundle-access.measurement.json`.

Repository discovery and repository-to-bundle selection remain owned by
`bundle_catalog.py`; request-scoped generation binding remains owned by
`manifest_snapshot.py`. The decomposition begins after that selection boundary:

| Responsibility | Owner after T011 |
| --- | --- |
| selected manifest, role inventory and read-only snapshot projections | `bundle_roles.py` |
| fixed-size descriptor reads, actual-byte fingerprints and declared metadata validation | `bounded_artifact_read.py` |
| verified read-only SQLite source and portable-copy integrity | `sqlite_artifact_read.py` |
| citation row validation and full/compact source evidence projections | `citation_projection.py` |
| pure call-graph record/model/count/run binding validation | `call_graph_validation.py` |
| orchestration, cache lifecycle and historical public facade | `bundle_access.py` |

The facade keeps compatibility aliases needed by the existing impact-index
consumer and tests. Public read-only functions remain reachable at their
historical import path: role/snapshot reads, `range_get`,
`query_existing_index`, symbol search, reference/caller/callee navigation and
`snapshot_check`. Existing response-projection tests exercise both
`verbose=True` and `compact=True`; MCP/resource/stdio/query-routing tests use the
same facade rather than a parallel shape.

## Fail-closed access result

Selected manifests now use the existing 4 MiB stable manifest-snapshot bound
instead of an unbounded `read_text`. Registered JSON/JSONL navigation artifacts
have a fixed 256 MiB cap; SQLite uses the same fixed cap before hashing or
querying. Reads bind descriptor identity before/after content and re-check the
pathname afterwards.

Legacy manifests may omit `bytes` and `sha256` only as a pair. That compatibility
case still reads within the fixed bound and records the actual byte count and
SHA-256 in the cache fingerprint. Partial fields, booleans-as-byte-counts,
negative sizes, malformed/uppercase digests and declared sizes above the cap
fail before the artifact is consumed.

The new focused adversarial suite proves:

- partial or malformed integrity metadata is rejected with
  `*_integrity_unavailable`;
- declared oversize is rejected before the artifact reader is called;
- descriptor reads stop at the requested byte bound;
- `..`, absolute paths and symlinks escaping the bundle root are rejected as
  `*_path_invalid`;
- duplicate registered roles are rejected as `*_role_ambiguous`, not selected
  by manifest order;
- missing/empty/non-string manifest run IDs are rejected before artifact
  selection;
- an oversized manifest is not parsed;
- citation-map same-size hash drift cannot become projected evidence;
- manifest bytes are re-hashed after the artifact read even when path metadata
  is spoofed to the earlier identity;
- pathname replacement after a descriptor read is classified as
  `source_changed`.

The pre-existing suites additionally retain exact hash/size drift errors,
call-graph/symbol run-ID and canonical-dump binding, active-manifest generation
coherence, weak-stat strict hashing, cache invalidation, post-read TOCTOU
rejection, SQLite portable-copy verification and cleanup, freshness/availability
projection, compact/verbose response contracts and read-only MCP wrappers.
Malformed citation rows remain a bounded per-row diagnostic; artifact-level
path, size, hash or metadata failure invalidates the citation-map source.

## Measured structural result

`bundle_access.py` fell from 3,676 lines / 134,274 bytes to 2,618 lines /
94,004 bytes: 1,058 lines (28.78%) and 40,270 bytes (29.99%) less. The five new
production modules are 181–580 lines each.

This is a decomposition and hardening slice, not an aggregate-LOC reduction:
the six production files together contain 4,282 lines. The measurement records
that explicitly rather than treating moved or expanded validation code as
deleted code.

The clean-start and final scans used the repository gate:

`python3 scripts/ci/check_graph_maintainability.py --root . --format json`

| Dimension | Clean slice start | Final dirty state | Delta |
| --- | ---: | ---: | ---: |
| C901 findings | 194 | 193 | -1 |
| Excess mass | 2,351 | 2,348 | -3 |
| Maximum | 138 | 138 | 0 |
| `bundle_access` findings | 1 | 0 | -1 |

The budget was lowered to the observed 193 / 2,348 / 138. The target
`_citation_row_is_valid` baseline identity was removed only after the real scan
fell. Baseline synchronization also removed three pre-existing stale identities
and recorded two pre-existing lower complexities; these unrelated baseline
updates are not claimed as T011 reductions.

## Independent review hardening

The first unfiltered full-suite run exposed two distinct classes of evidence:

- 35 real compatibility regressions in legacy manifest reads, MCP read-only access
  and snapshot preflight; the extraction had routed permissive historical facade
  calls through the stricter request-bound manifest decoder. The facade now keeps
  bounded stable JSON reads without manufacturing a `run_id` requirement, while
  active request snapshots remain strict.
- the already tracked Bubblewrap host failure in the two Patch Evaluation Sidecar
  test files. Those failures remain infrastructure evidence, not a product PASS.

A separate adversarial review also demonstrated that the first descriptor helper
could follow a final symlink introduced during a pathname race. The final reader
uses `os.open` with `O_NOFOLLOW`, compares the pre-open pathname identity with the
opened descriptor before reading, rechecks descriptor and pathname identity after
reading, and preserves weak-filesystem identity handling through content-hash
verification. Existing atomic-replacement and weak-identity tests and the new
symlink test all pass.

## Verification

- focused bundle/catalog/freshness/evidence/symbol/call/MCP/adapter/
  maintainability regression: **332 passed, 10 skipped**;
- new adversarial suite: **20 passed**;
- changed-file Ruff: **pass**;
- C901 on all changed production modules: **pass**;
- graph-maintainability gate: **pass** at 193 findings, max 138, excess 2,348,
  zero new or resolved baseline identities;
- module-reachability gate: **pass**, 214 modules, zero unproven and zero
  documentation-only;
- frontend parity guard: **pass**;
- broad repository suite excluding only the two host-blocked Bubblewrap files:
  **5,072 passed, 12 skipped**, receipt
  `a3601d63ff286d864280df268ae5994139113cc3a15e353b49ea0dc00fc19035`.

A separate full-suite attempt reached **5,046 passed, 68 failed and 12 skipped**.
The logs contain an explicit host-infrastructure failure from Bubblewrap
(`Creating new namespace failed: Resource temporarily unavailable`), but the 68
failures have not been individually proven to be exclusively infrastructural.
The full-suite gate therefore remains open and this slice is not merge-ready.

The two parse warnings emitted by the maintainability scanner are the deliberate
invalid Python fixtures already classified by the gate; the gate itself passes.

## Does not establish

This proof does not establish an unfiltered host full-suite PASS, remote freshness,
MCP transport/authentication availability, correctness of every legacy bundle,
absence of maintainability debt below the C901 threshold, aggregate product LOC
reduction, commit publication, pull-request state or merge readiness.
