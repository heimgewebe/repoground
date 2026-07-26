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
- Initial proof revision: `178d1705850b5ef7f8db25223a79541f129de5b1`
- Review-hardening revision: `4759b2a8ca205416d6bfa9b329ee225a0bf58290`
- Review-hardening diff format: `git diff --binary --no-ext-diff <initial-proof>..<review-hardening>`
- Review-hardening diff bytes: `12603`
- Review-hardening diff SHA-256: `f5bc05e58c662b6b2c673b9a40c9bd07516b9a82dce4f1626535184ebd0df0a3`
- Observed date: `2026-07-26`

This proof records a keep-and-integrate disposition for six production modules that previously had test evidence but no measured production entrypoint. It does not close the T004 parent task or establish that every dynamic or private consumer has been discovered.

## Live-state and non-conflict preflight

Before implementation:

- canonical checkout `/home/alex/repos/repoground` was clean at the base revision;
- `origin/main` was fetched immediately before both implementation and review-hardening commits and matched the base revision exactly;
- open PR `#1105` was inspected and changed a disjoint MCP/frontdoor and call-graph scope;
- a separate worktree and branch were used: `refactor/legacy-reconciliation-t004-port-current-v1`;
- an owner-bound path and branch lease protected that workspace;
- the historical T004 worktree and PR #1105 workspace were not modified.

The five historical T004 commits were examined against current `main`. Their complexity baseline, reachability scanner, tests and graph-maintainability budget were already present in newer or stricter forms. Porting them would have duplicated or downgraded current behavior, so no historical commit was retained.

## Exact module inventory

The six domain module files were not modified by the initial disposition. Their observed content identities at the base and implementation revision are:

| Module | Path | SHA-256 | Pre-state | Disposition |
|---|---|---|---|---|
| `merger.repoground.core.answer_grounding_delta` | `merger/repoground/core/answer_grounding_delta.py` | `4c5cf6f4f24662ce2b20ecf4897384a00acfbcc05227e424bbc7bfcb3b813d18` | test-only reachability exception | keep and integrate through `diagnostics answer-delta` |
| `merger.repoground.core.history_lens` | `merger/repoground/core/history_lens.py` | `a02e9797a65affc86c734a2143404cf70506efb4cdecf53479b8309b5ff3cc59` | test-only reachability exception | keep and integrate through `diagnostics history-lens` |
| `merger.repoground.core.memory` | `merger/repoground/core/memory.py` | `0cc08645583c96ce041eab3fcd05b41e72fc61113da8d7e3000d075ba481e304` | test-only reachability exception | keep and integrate through `diagnostics memory-build` and `diagnostics memory-check` |
| `merger.repoground.retrieval.audit_finding` | `merger/repoground/retrieval/audit_finding.py` | `c91545293164819fe0907b5a52922a0fc02cf719a304791fd365e1d8fab6b389` | test-only reachability exception | keep and integrate through `diagnostics audit-findings` |
| `merger.repoground.retrieval.audit_lane` | `merger/repoground/retrieval/audit_lane.py` | `9f5b5982b729c63f78c8f7d7c85bbdffcdb1677d3da0e4605d8af529b22ae306` | test-only reachability exception | keep and integrate through `diagnostics audit-plan` |
| `merger.repoground.retrieval.eval_diagnostics_integration` | `merger/repoground/retrieval/eval_diagnostics_integration.py` | `c97aadf7f6eb8cadde409383721eba34b0148f640a480f647ee7d0f274bad7d9` | test-only reachability exception | keep and integrate through `diagnostics eval-report` |

The review-hardening revision changes only input-shape validation in the integration path. At that revision:

- `merger/repoground/retrieval/eval_diagnostics_integration.py`: `cfffb7011ac03d68b41f933a8e22215c1085a9d1224ae7bb694e016b81500eb4`
- adjacent calibrator `merger/repoground/retrieval/eval_diagnostics.py`: `36acd91d7b768c63e081b8e45beaf851fe46a46a83099aa389c8e79e72af8f03`
- CLI adapter `merger/repoground/cli/cmd_diagnostics.py`: `acaef2845ab6c7197458b24072e763dbaf53907a79f8be1f3aacec47d9d812d0`
- CLI regression tests: `2a6445a094192295541c3fe34a44ed15a0074276c1a51597540ba4910f0cd681`

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
- decoded as UTF-8 and parsed as JSON;
- checked for required top-level and nested element shapes before domain dispatch.

Well-formed JSONL records that are not objects are rejected with a bounded `ValueError`; the CLI translates these and other supported malformed-input errors to exit code 2 without a traceback.

## Review hardening

Codex reviewed initial PR head `178d1705850b5ef7f8db25223a79541f129de5b1` and identified one P2 issue: top-level JSON types were checked, but malformed nested elements could still cause `AttributeError` tracebacks. Examples included history records such as `[1]` and JSONL index records such as `[]`.

Revision `4759b2a8ca205416d6bfa9b329ee225a0bf58290` addresses that finding by:

- validating list members for history records, memory citations, audit paths, audit candidates, citation IDs and verification records;
- validating retrieval-evaluation detail records before field access;
- validating chunk-index and citation-map JSONL object shape and optional string fields before field access;
- preserving invalid-JSON-line tolerance while rejecting well-formed but structurally invalid records;
- adding regression tests that assert exit code 2, empty stdout and absence of `Traceback`;
- extracting small validation helpers after the first implementation exceeded two complexity ratchets.

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

Initial implementation revision checks:

- relevant domain and CLI tests: `148 passed in 0.79s`;
- broad suite excluding only the two host-blocked Bubblewrap files: `4865 passed, 2 skipped in 152.64s`;
- durable broad-test task: `7652d6a5ec724fb2818e6364`;
- durable lifecycle receipt SHA-256: `7357309e3dd33ba0bb244117b49c259e32b3b16e86b4140de3c087eae348357c`.

Review-hardening revision checks:

- relevant domain, CLI and retrieval-diagnostics tests: `151 passed in 0.89s`;
- broad suite excluding only the two host-blocked Bubblewrap files: `4868 passed, 2 skipped in 146.71s`;
- durable broad-test task: `d258e54954d549b5be7ed792`;
- durable lifecycle receipt SHA-256: `9b430567129386e2e0c0807476ac82a61d1ee50e30422284059886c66be277d3`;
- Ruff changed-scope check: pass;
- graph-maintainability ratchet: pass;
- module reachability: `205 production modules, 0 unproven, 0 documentation-only, 0 test-only`;
- staged diff whitespace/error check before commit: pass.

A complete unfiltered suite run on the initial implementation reached `4874 passed, 2 skipped, 33 failed`. All 33 failures were confined to:

- `tests/test_patch_evaluation_sidecar.py`
- `tests/test_patch_evaluation_sidecar_host_readback.py`

Every failure had the same host infrastructure cause: Bubblewrap could not create a namespace and returned `Creating new namespace failed: Resource temporarily unavailable`. The changed files do not implement or call that sidecar. This proof therefore records those tests as not evaluable on the current host, not as passing. The host issue already has Bureau coverage in `OPERATOR-PC-HYGIENE-V1-T014`, and `REPOGROUND-LEGACY-RECONCILIATION-V1-T016` explicitly depends on its resolution; no duplicate task was registered.

## Performance

Thirty fresh-process `python -m merger.repoground.cli.main --help` runs were measured per revision on the same idle host after review hardening:

| Revision | Median | p90 | Minimum | Maximum |
|---|---:|---:|---:|---:|
| base `main` | 139.046 ms | 141.822 ms | 134.844 ms | 142.845 ms |
| review-hardened implementation | 139.853 ms | 143.670 ms | 136.513 ms | 146.926 ms |

Observed median delta: `+0.807 ms` or approximately `+0.58%`. This is small and may include process-start noise. An earlier eager implementation added roughly 4–5 ms and was rejected; lazy parser construction and lazy domain imports removed most of that cost.

## Rollback

Rollback is bounded and mechanical:

1. revert review-hardening revision `4759b2a8ca205416d6bfa9b329ee225a0bf58290`;
2. revert implementation revision `397ebc1a520f1a723f47b267560a6973a1532830`;
3. restore the six exact module names in `allowed_test_only` if they were not restored by the implementation revert;
4. rerun module reachability, graph maintainability, the relevant domain tests and the broad suite available on the host.

Reverting removes only the opt-in CLI, its tests, its documentation, the review input hardening and the reachability-list reduction. It does not delete the six domain modules.

## Limitations

- Organization code search cannot prove the absence of dynamic, generated, local-only or inaccessible private consumers.
- CLI reachability proves a product entrypoint exists; it does not prove real-world usage frequency.
- The current host could not evaluate the two Bubblewrap-dependent sidecar files.
- GitHub CI and a fresh external review of the review-hardened head remain separate post-push evidence.