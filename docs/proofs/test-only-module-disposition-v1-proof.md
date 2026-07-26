# RepoGround test-only module disposition v1 proof

## Binding

- Bureau task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T013`
- Parent task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T004`
- Repository: `heimgewebe/repoground`
- Base revision: `40dd1088a642370c5a7cc0dfd19dbd59e6395a35`
- Implementation revision: `397ebc1a520f1a723f47b267560a6973a1532830`
- Implementation diff format: `git diff --binary --no-ext-diff <base>..<implementation>`
- Implementation diff bytes: `25442`
- Implementation diff SHA-256: `f0f67e5cbb80a23ef93cd39477fd38651bac755279532493de85229c93622abd`
- Observed date: `2026-07-26`

This proof records a keep-and-integrate disposition for six production modules that previously had test evidence but no measured production entrypoint. It does not close the T004 parent task or establish that every dynamic or private consumer has been discovered.

## Live-state and non-conflict preflight

Before implementation:

- canonical checkout `/home/alex/repos/repoground` was clean at the base revision;
- `origin/main` was fetched immediately before commit and matched the base revision exactly;
- open PR `#1105` was inspected and changed a disjoint MCP/frontdoor and call-graph scope;
- a separate worktree and branch were used: `refactor/legacy-reconciliation-t004-port-current-v1`;
- an owner-bound path and branch lease protected that workspace;
- the historical T004 worktree and PR #1105 workspace were not modified.

The five historical T004 commits were examined against current `main`. Their complexity baseline, reachability scanner, tests and graph-maintainability budget were already present in newer or stricter forms. Porting them would have duplicated or downgraded current behavior, so no historical commit was retained.

## Exact module inventory

The domain module files were not modified by this disposition. Their observed content identities at the base and implementation revision are:

| Module | Path | SHA-256 | Pre-state | Disposition |
|---|---|---|---|---|
| `merger.repoground.core.answer_grounding_delta` | `merger/repoground/core/answer_grounding_delta.py` | `4c5cf6f4f24662ce2b20ecf4897384a00acfbcc05227e424bbc7bfcb3b813d18` | test-only reachability exception | keep and integrate through `diagnostics answer-delta` |
| `merger.repoground.core.history_lens` | `merger/repoground/core/history_lens.py` | `a02e9797a65affc86c734a2143404cf70506efb4cdecf53479b8309b5ff3cc59` | test-only reachability exception | keep and integrate through `diagnostics history-lens` |
| `merger.repoground.core.memory` | `merger/repoground/core/memory.py` | `0cc08645583c96ce041eab3fcd05b41e72fc61113da8d7e3000d075ba481e304` | test-only reachability exception | keep and integrate through `diagnostics memory-build` and `diagnostics memory-check` |
| `merger.repoground.retrieval.audit_finding` | `merger/repoground/retrieval/audit_finding.py` | `c91545293164819fe0907b5a52922a0fc02cf719a304791fd365e1d8fab6b389` | test-only reachability exception | keep and integrate through `diagnostics audit-findings` |
| `merger.repoground.retrieval.audit_lane` | `merger/repoground/retrieval/audit_lane.py` | `9f5b5982b729c63f78c8f7d7c85bbdffcdb1677d3da0e4605d8af529b22ae306` | test-only reachability exception | keep and integrate through `diagnostics audit-plan` |
| `merger.repoground.retrieval.eval_diagnostics_integration` | `merger/repoground/retrieval/eval_diagnostics_integration.py` | `c97aadf7f6eb8cadde409383721eba34b0148f640a480f647ee7d0f274bad7d9` | test-only reachability exception | keep and integrate through `diagnostics eval-report` |

## Consumer and removal assessment

Repository searches separated these evidence classes:

- direct production imports: absent before this change;
- CLI/runtime entrypoint: absent before this change;
- tests and proof documents: present for all six modules;
- packaging presence: all six modules were shipped inside the production package tree;
- organization code search: searches for `check_answer_grounding_delta`, `build_history_lens`, `build_memory_record`, `adapt_audit_findings`, `plan_audit_lanes` and `integrate_diagnostics_with_eval_results` returned RepoGround-local implementations, tests or documents, with no separate Heimgewebe consumer observed.

Static absence was not treated as deletion authority. The modules contain tested, bounded domain behavior, and their proof history shows deliberate authority constraints. The safer disposition is therefore explicit opt-in integration rather than deletion.

## Product surface

The implementation adds `repoground diagnostics` with seven operations:

- `answer-delta`
- `history-lens`
- `memory-build`
- `memory-check`
- `audit-plan`
- `audit-findings`
- `eval-report`

The nested parser and domain imports are lazy. Normal indexing, querying, service, MCP, merge and publication paths do not execute these modules.

CLI-owned JSON control files are:

- limited to 8 MiB;
- required to be regular files;
- rejected when presented as symbolic links;
- opened with `O_NOFOLLOW` when supported;
- checked by device and inode before and after opening to detect path replacement;
- decoded as UTF-8 and parsed as JSON.

## Authority boundary

The new surface does not:

- establish repository or claim truth;
- establish retrieval, review or audit completeness;
- approve audit candidates;
- modify retrieval metrics or rankings;
- edit repositories or create issues;
- refresh snapshots;
- grant merge permission;
- execute automatically in normal RepoGround flows.

Revision identities and input provenance remain caller responsibilities. Live Git, GitHub, CI and working-tree state must still be checked separately.

## Verification

Exact implementation revision checks:

- relevant domain and CLI tests: `148 passed in 0.79s`;
- broad suite excluding only the two host-blocked Bubblewrap files: `4865 passed, 2 skipped in 152.64s`;
- durable broad-test task: `7652d6a5ec724fb2818e6364`;
- durable lifecycle receipt SHA-256: `7357309e3dd33ba0bb244117b49c259e32b3b16e86b4140de3c087eae348357c`;
- Ruff changed-scope check: pass;
- graph-maintainability ratchet: pass;
- module reachability: `205 production modules, 0 unproven, 0 documentation-only, 0 test-only`;
- staged diff whitespace/error check before commit: pass.

A complete unfiltered suite run reached `4874 passed, 2 skipped, 33 failed`. All 33 failures were confined to:

- `tests/test_patch_evaluation_sidecar.py`
- `tests/test_patch_evaluation_sidecar_host_readback.py`

Every failure had the same host infrastructure cause: Bubblewrap could not create a namespace and returned `Creating new namespace failed: Resource temporarily unavailable`. The changed files do not implement or call that sidecar. This proof therefore records those tests as not evaluable on the current host, not as passing.

## Performance

Thirty fresh-process `python -m merger.repoground.cli.main --help` runs were measured per revision on the same host:

| Revision | Median | p90 | Minimum | Maximum |
|---|---:|---:|---:|---:|
| base `main` | 142.030 ms | 144.947 ms | 137.964 ms | 148.940 ms |
| implementation | 142.889 ms | 147.076 ms | 139.087 ms | 152.772 ms |

Observed median delta: `+0.859 ms` or approximately `+0.60%`. This is small and may include process-start noise. An earlier eager implementation added roughly 4–5 ms and was rejected; lazy parser construction and lazy domain imports removed most of that cost.

## Rollback

Rollback is bounded and mechanical:

1. revert implementation revision `397ebc1a520f1a723f47b267560a6973a1532830`;
2. restore the six exact module names in `allowed_test_only` within `config/repoground-module-reachability.v1.json`;
3. rerun module reachability, graph maintainability, the relevant domain tests and the broad suite available on the host.

Reverting removes only the opt-in CLI, its tests, its documentation and the reachability-list reduction. It does not delete or mutate the six domain modules.

## Limitations

- Organization code search cannot prove the absence of dynamic, generated, local-only or inaccessible private consumers.
- CLI reachability proves a product entrypoint exists; it does not prove real-world usage frequency.
- The current host could not evaluate the two Bubblewrap-dependent sidecar files.
- GitHub CI and external review are separate post-push evidence and are not established by this local proof.
