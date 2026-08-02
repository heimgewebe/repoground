# Fleet Context Call Navigation Restore v1 Proof

## Binding

- RepoGround baseline: `6a6e9ae227976fb9b2b596ca0a944e9f7c5d2d93` (`main`, clean worktree)
- Regression introduced by: `288ced5fcc46d25e91cb671e103e6cd8d0382289` ("feat(repoground): compact daily fleet context")
- Superseded decision: [`repoground-fleet-context-profile-v1-proof.md`](repoground-fleet-context-profile-v1-proof.md)

## Observed failure

The daily fleet publication resolves to the `fleet-context` profile
(`publication_config` in `scripts/ops/repoground-publish-fleet`). That profile set
`python_symbol_index_json` and `python_call_graph_json` to `profile_excluded`, so the
published bundle carried neither artifact.

All four agent-facing call-navigation tools failed closed against the live
publication `heimgewebe__repoground__main-max-260802-0701`:

| Tool | Status | Error code |
|---|---|---|
| `find_symbol` | `missing` | `python_symbol_index_json_missing` |
| `find_references` | `missing` | `python_call_graph_json_missing` |
| `get_callers` | `missing` | `python_call_graph_json_missing` |
| `get_callees` | `missing` | `python_call_graph_json_missing` |

The bundle itself reported `freshness: fresh_exact` and `post_emit_health: pass`, and the
profile evaluation reported `status: pass` with no excluded role present. Every existing
gate was green while four tools were unreachable. No GitHub issue tracked it.

`context_compose` degraded honestly over the same bundle (`status: degraded`, gap
`source_unavailable/python_symbol_index_json`, skipped lanes `symbol_navigation` and
`call_graph`), which is the behaviour the call-navigation tools now adopt.

## Cause

The superseded decision recorded a consumer-boundary inventory bound to
`heimgewebe/grabowski` at `fdc9266016a07c27c86925976a4b56c17b0483c6`. It concluded that the
consumer "does not require the raw canonical dump, SQLite index, Python symbol index, or
Python call graph **in the normal context path**".

That statement is accurate and insufficient. The same consumer also exposes `find_symbol`,
`find_references`, `get_callers`, and `get_callees`, which read exactly the two
excluded artifacts. The inventory covered the context-pack path only, so the exclusion
silently removed a second consumer path that was never inspected.

## Decision

`fleet-context` keeps `python_symbol_index_json` and `python_call_graph_json` at
`recommended`. `sqlite_index` remains `profile_excluded` and remains the only role in
`PROFILE_POST_EMIT_DROPPABLE_ROLES` for this profile.

Alternative considered and rejected: resolving the call-navigation tools against a separate
`agent-portable` or `full-max` bundle. Rejected because it is the larger and weaker
contract — it would require publishing a second bundle per repository (increasing storage
rather than reducing it) and would split freshness across two publications, so
`fresh_exact` would no longer be one coherent claim for one repository.

### Storage effect

The compact intent is preserved. Measured on the published fleet bundles:

| Repository | Bundle total | Restored indexes | Share |
|---|---:|---:|---:|
| `heimgewebe__semantAH` | 12 MB | 1.6 MB | ~13% |

For context, the same `fleet-context` bundle for `heimgewebe__repoground` already carries a
16 MB canonical Markdown, a 4.9 MB citation map, and a 2.7 MB architecture graph. The
`sqlite_index` exclusion, which is retained, remains the dominant saving.

## Degradation visibility

Only `resolved` call edges can produce callers or callees. Every other resolution status is
an edge the resolver saw but could not bind, so any caller or callee list is complete only
relative to the resolved share. The three call-graph-backed navigation tools now report
`call_graph_coverage` at the top level of the response:

- `scope`: `observed_call_edges` (never the repository-wide call graph)
- `completeness`: `complete`, `partial`, or `unknown` within that scope
- `resolved_call_edges` / `total_call_edges` / `resolved_ratio`
- `unresolved_by_status` (per `candidate`, `ambiguous`, `unresolved`)
- `does_not_establish`: `complete_call_graph`, `caller_completeness`,
  `callee_completeness`, `unresolved_edges_are_irrelevant`

`unknown` is reported when the graph carries no `resolution_counts`, so a graph that never
declared coverage is not read as a complete one.

This matters at the observed scale: the 2026-07-28 measurement over the fleet found 17,765
of 67,836 call edges resolved (~26%), with module-qualified calls (`mod.target(...)`)
routinely unbound. Results looked exhaustive and were not.

## Regression guard

`merger/repoground/tests/test_publication_surface_smoke.py` emits a real publication through
the same CLI path the fleet publisher uses
(`merger.repoground.cli.ground external-manifest refresh --profile fleet-context`), then
calls the MCP frontdoors `find_symbol`, `find_references`, `get_callers`, and
`get_callees` against the emitted manifest.

The existing profile tests are assertions about the rule tables and stayed green throughout
the regression. This test reads the shipped artifact back through the agent-facing surface,
which is the only level at which the failure was observable.

Verified to catch the regression: with the `profile_excluded` values restored, all five
tests in the file fail (`assert 'missing' == 'available'`). With the fix in place, all five
pass.

## Verification

- `python3 -m pytest` → 5347 passed, 12 skipped
- `ruff check --config ruff-ci.toml .` → All checks passed
- Live re-read after the fix, against a real `fleet-context` publication:
  `find_symbol` → `available`, 1 hit (`target`, `pkg/core.py`);
  `find_references` → `available`, non-empty call-site list;
  `get_callers` → `available`, caller `pkg/caller.py`, coverage `complete` (ratio `1.0`);
  `get_callees` → `available`, non-empty callee list.
- Publication report: `profile_evaluation.status: pass`,
  `profile_excluded_present: []`, `removed_profile_excluded_artifacts` contains only the
  SQLite index.

## Does not establish

- That the ~26% call-edge resolution rate is improved. This change makes the shortfall
  visible; it does not raise it.
- That other consumers of `fleet-context` were re-inventoried. Only the call-navigation
  path was corrected.
- Retrieval quality for natural-language queries, which remains keyword/FTS only.
