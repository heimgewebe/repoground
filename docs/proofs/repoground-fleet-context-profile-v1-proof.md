# RepoGround Fleet Context Profile v1 Proof

## Binding

- Bureau task: `OPERATOR-ECOSYSTEM-REDUNDANCY-V1-T008`
- Bureau run: `BUR-RUN-20260731T152008Z-287eff15d0`
- RepoGround baseline: `f49a978e161797fb6a1740f5c9b723bb2ae054af`
- Measurement summary SHA-256: `e2651cdd00fd5d849f46f43f971970bcc2d9e1ea3a6e15cad9025d776b9f1fdf`
- Full receipt SHA-256: `59dd6445a65d560bb4a573cb67b744b226f092af12067a842bb371a3b59a9755`
- Rejected archive receipt SHA-256: `2d1bb28679b6549d26d7ffb450169e6aa4966ab116b79e291c0d9ffce815a6c2`
- Accepted compact receipt SHA-256: `45f34fa085583c371f01e0406c0919c1884f8605630a38231422e580da26de54`

The implementation was produced in the Bureau-created isolated RepoGround worktree. The coordinated claim covered the publication component and the six exact source, test, policy, and proof paths. It did not authorize foreign-worktree cleanup, merge, or deployment.

## Consumer boundary

The pre-implementation inventory was bound to immutable consumer revisions:

- `heimgewebe/grabowski` at `fdc9266016a07c27c86925976a4b56c17b0483c6`: the normal context-pack path binds manifest identity, freshness, health, cited query results, and bounded ranges. It does not require the raw canonical dump, SQLite index, Python symbol index, or Python call graph in the normal context path.
- `heimgewebe/systemkatalog` at `f7c6ecd0ada80194a57e2bf84d46823ab20559b7`: no active direct reader of individual RepoGround bundle sidecars was found.

These observations are revision-bound. They do not establish future compatibility after either consumer changes.

## Decision

Ordinary daily fleet publication uses the agent-facing `fleet-context` profile with `dual` output. The dual renderer creates the citation map and chunk index. Profile finalization then removes these heavy, regenerable artifacts from the published surface:

- `sqlite_index`
- `python_symbol_index_json`
- `python_call_graph_json`

The compact profile still requires canonical Markdown, the bundle manifest, the agent reading pack, the citation map, the chunk index, output health, post-emit health, bundle-surface validation, and the export-safety report. The snapshot plan and retrieval evaluation remain recommended.

`full-max` remains the explicit diagnostic path. `vault-gewebe` remains on `agent-portable` with `dual` output so this migration does not silently narrow its existing contract.

## Rejected alternative

The first candidate used `fleet-context` with `archive` output. The real receipt returned `fail` because both `citation_map_jsonl` and `chunk_index_jsonl` were missing required artifacts. That candidate was rejected without a commit. Storage reduction is not accepted when it weakens citation truth.

## Same-repository storage measurement

Both accepted runs used the same committed synthetic repository, source commit `e193aa630fc969609a776627fb2f7e6c02389a35`. The corpus contained 120 Python modules, 20 Markdown documents, and one README.

| Variant | Published bytes | Profile result |
|---|---:|---|
| `full-max` / `dual` | 2,207,247 | `warn` because the recommended relation-card artifact was absent |
| `fleet-context` / `dual` | 1,264,876 | `pass` |

Measured effect:

- saved bytes: **942,371**;
- reduction: **42.6944%**;
- required context roles preserved: canonical Markdown, manifest, agent pack, citation map, chunk index, all health controls, and export-safety report;
- removed heavy artifacts: SQLite index, Python symbol index, and Python call graph.

The accepted compact receipt listed the three removed files explicitly. Its profile evaluation reported no missing required or recommended artifacts and no excluded role still present.

## Compatibility and migration

The fleet publisher selects `fleet-context` only for new ordinary fleet publications. Existing generations remain governed by the existing retention, pin, transaction, and crash-recovery policy. This change deletes no existing published generation. Operators can still request `full-max` when SQLite or Python diagnostic indexes are needed.

## Validation

- focused profile and fleet-routing tests: `4 passed`;
- broader profile, fleet, snapshot-CLI, and symbol-consumer tests: `142 passed`;
- full repository suite: `5269 passed`, `12 skipped`, and three Web-UI cases timed out while loading `http://localhost:8000/`;
- exact isolated rerun of those three Web-UI cases: `3 passed` without code changes;
- repository-wide Ruff with `ruff-ci.toml`: passed;
- Python compilation of the changed implementation files: passed;
- `git diff --check`: passed;
- real full-versus-compact snapshot generation: both accepted commands completed; compact profile `pass`.

The three full-suite failures were outside the changed publication surface and shared the same `Page.goto` timeout. Their isolated rerun is evidence of a transient browser/static-server startup failure, not proof that the Web-UI tests can never be flaky.

## Does not establish

This proof does not establish search parity without SQLite, complete repository understanding, runtime causality, test sufficiency beyond the executed checks, absence of future consumer changes, a permanently non-flaky Web UI, full CI success, or merge readiness by itself.
