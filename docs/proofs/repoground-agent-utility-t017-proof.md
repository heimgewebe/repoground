# RepoGround Agent Utility T017 proof

Task: `REPOGROUND-AGENT-UTILITY-V1-T017`

Base commit: `08d5691dd65c1ee7e48a259dbfd4377eed12b015`

## Scope and execution boundary

T017 adds one shared **read-only** `repoground doctor` surface and makes the source-install/upgrade/MCP/first-bundle-readback path explicit. It composes existing RepoGround truth surfaces rather than introducing a second catalog, freshness or manifest authority.

The canonical Bureau pickup was attempted first and rejected because T017 remained `planned` and absent from `registry/queue.json`. The queue was concurrently leased by unrelated Bureau closeout work. The implementation therefore used the direct user-authorized fallback on the isolated branch `feat/repoground-agent-utility-t017-20260807` in a standalone clone created from the exact base commit above; no foreign RepoGround checkout or Bureau queue file was modified.

`repoground doctor` explicitly declares and implements a no-effect boundary:

- no package installation or interpreter replacement;
- no Git fetch/pull/reset or other repository mutation;
- no bundle generation or refresh;
- no service start/restart;
- no secret read;
- no network synchronization;
- `writes: []` in the machine-readable mutation boundary.

## Readiness contract

Every check returns one of `available`, `degraded` or `blocked`, plus:

- stable check id;
- cause;
- operational impact;
- allowed next action;
- bounded evidence;
- check-specific nonclaims.

The required checks cover:

- Python runtime against the current CPython 3.12 CI/release-candidate baseline;
- local Git executable readiness without network synchronization;
- SQLite FTS5 via an in-memory create/lookup smoke;
- `jsonschema` availability;
- RepoGround bundle catalog selection through the existing catalog code;
- selected manifest health through the existing manifest-bound health code;
- local snapshot/check-out freshness through the existing no-network freshness code;
- project MCP configuration and its existing `scripts/repoground-mcp-project.py` starter.

Optional checks cover the convenience wrapper and structural adapters. Missing optional Rust/Bash adapters are reported as degraded optional capabilities and do **not** change an otherwise available Python/FTS core status. The existing Python call-graph and decoded SCIP adapters are reported separately from future Rust/Bash lanes.

Ambiguous existing bundle selection is `blocked`: doctor does not guess a generation. A stale, dirty or non-comparable local snapshot is `degraded`: doctor reports it but never refreshes it. Missing `jsonschema` degrades strict schema validation without inventing a core outage. Broken FTS5 is a blocker for the deterministic lexical retrieval path.

## MCP and local-file hardening

The default MCP contract binds `<repo-root>/.mcp.json` to `<repo-root>/scripts/repoground-mcp-project.py`. The Doctor validates this tracked binding but does not claim that an MCP client is connected or that the server is semantically correct.

Explicit MCP config/starter paths are made absolute without resolving symlinks first. Regular-file identity is checked with `lstat`/`fstat`; config reads use `O_NOFOLLOW` when available, are size-bounded, handle short reads, and verify that device/inode/size/mtime stay unchanged while reading. A regression test proves that an explicitly supplied MCP configuration symlink is rejected/degraded rather than followed.

## Reproducible source setup

`docs/GETTING_STARTED.md` now states the actual repository contract rather than inventing a PyPI/Wheel install:

1. clone the source repository;
2. create a local `python3.12 -m venv .venv` environment;
3. apply the hash-bound `requirements/repoground-runtime.lock.txt` through `.venv/bin/python`;
4. run the canonical module CLI and Doctor through that interpreter;
5. optionally apply the hash-bound dev lock for tests;
6. keep semantic reranking opt-in and limited to its documented CPython 3.12/Linux x86-64/CPU platform contract.

Upgrade remains an explicit reviewed Git/deployment action. Doctor does not perform it. After an upgrade the documented path rechecks the exact Git commit, reapplies the current lock and reruns Doctor. The first bundle readback can bind an exact manifest with `--manifest --strict --json`.

## Negative regression set

`merger/repoground/tests/test_doctor.py` covers:

- missing `jsonschema`;
- unavailable/broken FTS5;
- ambiguous bundle catalog selection;
- stale bundle versus local checkout;
- missing MCP project starter;
- valid MCP config/starter binding;
- explicit MCP config symlink rejection;
- optional Rust/Bash adapter absence without Python-core failure;
- summary/mutation-boundary semantics;
- JSON/human CLI output and exit-code behavior.

Focused Doctor tests after the final hardening patch: **10 passed**.

Broader T017 regression selection after the final hardening patch:

```text
merger/repoground/tests/test_doctor.py
merger/repoground/tests/test_module_reachability.py
merger/repoground/tests/test_naming_doc.py
merger/repoground/tests/test_live_freshness.py
```

Result: **46 passed**.

Targeted Ruff on the changed Python surface: **pass**. A later PR-wide Ruff job also passed `ruff check --config ruff-ci.toml .`, but its maintainability ratchet correctly rejected the first PR head because adding a separate `doctor` dispatch branch raised `cli.main::main` from complexity 42 to 43 and `_bundle_checks` introduced complexity 12. The remediation did not raise any ceiling: doctor joined the existing auxiliary handler table and bundle selection/health/freshness were split into bounded helpers. The exact local CI ratchet then reported `status=pass`, `new_count=0`, `finding_count=189`, `excess_total=2314` and `max_complexity=138`; full-scope Ruff remained pass and the 46 focused regressions remained pass.

## Real Heim-PC readback

A real invocation on the isolated T017 checkout ran:

```text
python3 -m merger.repoground doctor --repo-root . --json
```

It returned `degraded`, not `blocked`, for evidence-bound reasons:

- local interpreter: CPython `3.10.12`, therefore outside the current `3.12` CI/release baseline;
- Git: available (`2.34.1`);
- SQLite FTS5: available (`3.37.2`);
- `jsonschema`: available;
- tracked MCP configuration/starter: available;
- convenience wrapper: available;
- Python call-graph adapter: available;
- decoded SCIP adapter: available;
- Rust/Bash structure adapters: absent and therefore degraded **optional** only;
- unique healthy RepoGround publication selected from the canonical local publication catalog;
- selected manifest health: pass;
- snapshot/current commit both `08d5691dd65c1ee7e48a259dbfd4377eed12b015`, but the T017 checkout was intentionally dirty because the implementation was uncommitted, so freshness correctly reported `current_working_tree_is_dirty` as degraded.

The selected manifest was `heimgewebe__repoground__main-max-260807-1301_merge.bundle.manifest.json` with SHA-256 `e818cd52a9deef34050874470d6d06550f1a91563d5a82df529f166888ce3a9b` and existing manifest health `pass`.

This live result is desirable evidence: Doctor distinguishes a usable but non-baseline/dirty development environment from a hard core failure instead of flattening both into one green/red flag.

## Acceptance mapping

- `diagnose-surface`: satisfied by the shared checks for Python, Git, SQLite/FTS, jsonschema, catalog, manifest integrity, MCP configuration, Freshness and optional adapters.
- `machine-readable-status`: satisfied by per-check status/cause/impact/next-action/evidence and summary separation of required vs optional checks.
- `no-side-effect-default`: satisfied by implementation boundaries, bounded tests and machine-readable `mutation_boundary`.
- `onboarding-and-upgrade`: satisfied by the revised source/lock/Python-3.12/MCP/first-manifest-readback documentation.
- `negative-tests`: satisfied by the ten dedicated Doctor regression cases above.

## Nonclaims

This implementation does not establish:

- freshness against GitHub or another remote;
- runtime semantic correctness;
- repository understanding or answer correctness;
- test sufficiency;
- review completeness or merge readiness;
- service reachability;
- semantic completeness of any optional adapter;
- implementation of Rust/Bash structure adapters;
- automatic repair, installation, upgrade or bundle regeneration.

The repository-wide full pytest run and pull-request CI are separate merge gates and are not claimed by this pre-commit proof until their terminal results are observed.
