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

## Second review-hardening addendum

Codex reviewed PR head `b00e443b6b39e56503fc4ddb87e0a666e042eab0` and identified a second P2 boundary issue. Object-shaped retrieval-evaluation details could still carry invalid field types. In particular, `"is_relevant": "false"` is a truthy string in Python and could silently suppress a miss, while a non-string `query` could produce a diagnostics artifact that violates its schema.

The finding is addressed by revision `e080654c4c4b0d11d426a44d4088028bbff79163`.

- Parent head: `b00e443b6b39e56503fc4ddb87e0a666e042eab0`
- Field-hardening diff format: `git diff --binary --no-ext-diff <parent>..<field-hardening>`
- Field-hardening diff bytes: `7510`
- Field-hardening diff SHA-256: `09c640246ac6072d442e5058ed7478e5c39dde9e42128e469b1168db0b2952d4`

The adapter now validates these present fields before miss classification:

- `query`: string;
- `expected`: list of strings;
- `is_relevant`: boolean;
- `found_count`: non-negative integer, explicitly excluding booleans;
- `top_results`: list of strings.

Missing fields retain the previous bounded defaults. Present malformed fields fail with exit code 2 and without a traceback. Nine parameterized regression cases cover scalar/list mismatches, invalid list members, boolean-as-integer ambiguity and negative hit counts.

Verification on the exact field-hardening revision:

- focused diagnostics tests: `45 passed in 0.84s`;
- relevant domain, CLI and retrieval-diagnostics tests: `160 passed in 1.17s`;
- broad suite excluding only the two already documented host-blocked Bubblewrap files: `4877 passed, 2 skipped in 149.90s`;
- durable broad-test task: `f681a924ca8a45c8a14b488e`;
- durable lifecycle receipt SHA-256: `98ee3e1be27530188343811a3346348d7bceeb40607548104f1911a9fed332c7`;
- Ruff changed-scope check: pass;
- graph-maintainability ratchet: pass;
- module reachability: `205 production modules, 0 unproven, 0 documentation-only, 0 test-only`.

Thirty fresh-process normal CLI starts were measured after the broad suite completed:

| Revision | Median | p90 | Minimum | Maximum |
|---|---:|---:|---:|---:|
| base `main` | 142.167 ms | 145.178 ms | 137.477 ms | 150.679 ms |
| field-hardened implementation | 143.214 ms | 144.771 ms | 138.812 ms | 147.088 ms |

Observed median delta: `+1.047 ms` or approximately `+0.74%`. The validation functions remain behind the lazy diagnostics parser and therefore do not execute during normal `--help`, indexing, querying, service, MCP, merge or publication paths. The measured delta is compatible with fresh-process noise, but is reported rather than treated as zero.

This addendum supersedes the earlier statement that a fresh external review of the first review-hardened head remained pending. A further current-head review and current-head GitHub CI are still separate post-push gates.


## Third review-hardening addendum

Codex reviewed PR head `edb317473c13c6100b486f8db96e7f7108b5c9f5` and identified a third P2 boundary issue. `answer-delta` still delegated its citation-map path to older tolerant domain loading. A well-formed but structurally invalid JSONL line such as `[]` could therefore be ignored and misreported as a missing citation with exit code 0 instead of a malformed-input error.

The finding is addressed by revision `3cb2350cd94e2bc3891b6349793e6a70611fb183`.

- Parent head: `edb317473c13c6100b486f8db96e7f7108b5c9f5`
- Citation-map-hardening diff format: `git diff --binary --no-ext-diff <parent>..<citation-map-hardening>`
- Citation-map-hardening diff bytes: `10592`
- Citation-map-hardening diff SHA-256: `d23ef945fe95f842f3bcf373d568b06ed2e56204af87b1d24b1950bd80e6e7af`

The CLI adapter now reads a supplied answer citation map once through the existing bounded, no-symlink file loader and requires every nonblank JSONL line to:

- contain valid JSON;
- be an object;
- contain a non-empty string `citation_id`;
- use a `citation_id` that has not already appeared in the same map.

The parsed records are passed into `check_answer_grounding_delta()` through the optional `new_citation_entries` parameter. When that parameter is supplied, the domain function validates and copies the in-memory mapping and does not reread the citation-map path. A regression test deletes the original map before evaluation and still obtains a valid result, proving that validation and consumption use the same parsed records rather than two path reads.

Six CLI regression cases cover non-object records, missing, empty and non-string IDs, duplicate IDs and invalid JSON. These inputs return exit code 2 with empty stdout and no traceback.

Verification on the exact citation-map-hardening revision:

- focused answer-delta and CLI tests: `31 passed in 1.12s`;
- relevant domain, CLI and retrieval-diagnostics tests: `167 passed in 1.34s`;
- broad suite excluding only the two already documented host-blocked Bubblewrap files: `4884 passed, 2 skipped in 148.99s`;
- durable broad-test task: `c06ec494a85b4c8282c812e8`;
- durable lifecycle receipt SHA-256: `c8d8dbde5c2d1b9f99661aae3802790d81259cdf6b71b302f23fc37e01da4918`;
- Ruff changed-scope check: pass;
- graph-maintainability ratchet: pass;
- module reachability: `205 production modules, 0 unproven, 0 documentation-only, 0 test-only`.

Thirty fresh-process normal CLI starts were measured after the broad suite completed:

| Revision | Median | p90 | Minimum | Maximum |
|---|---:|---:|---:|---:|
| base `main` | 139.228 ms | 141.323 ms | 135.801 ms | 141.881 ms |
| citation-map-hardened implementation | 140.228 ms | 142.329 ms | 136.065 ms | 146.392 ms |

Observed median delta: `+1.000 ms` or approximately `+0.72%`. The strict citation-map reader remains behind the lazy diagnostics parser and executes only when `diagnostics answer-delta --new-citation-map` is invoked. The measured normal-start delta is compatible with process-start noise, but is reported rather than treated as zero.

Rollback of this addendum is the revert of `3cb2350cd94e2bc3891b6349793e6a70611fb183`; the previous tolerant domain path remains available to pre-existing callers that do not supply prevalidated entries. Current-head GitHub CI and a fresh Codex review remain separate post-push gates.


## Fourth review-hardening addendum

Codex reviewed PR head `6aad39035b78ddb67660b62cfd3dcdd205b464f0` and identified a fourth P2 boundary issue. The `answer-delta` adapter validated only that the old declaration was an object. Object-valued or otherwise malformed `used_citations` and `used_ranges` collections could therefore be iterated by the tolerant domain function and silently omit declared evidence. In the concrete review example, an object-valued `used_citations` collection beside one valid range could still produce an overall `valid` result with no citation checks.

The finding is addressed by revision `dcba932d00e074f685da26a703ebf777271d3a21`.

- Parent head: `6aad39035b78ddb67660b62cfd3dcdd205b464f0`
- Declaration-hardening diff format: `git diff --binary --no-ext-diff <parent>..<declaration-hardening>`
- Declaration-hardening diff bytes: `4819`
- Declaration-hardening diff SHA-256: `f435059dd11bc1b80d26c78f426cf99c5b6098986f2fa00e05917fc458c4b938`

At the CLI boundary:

- missing `used_citations` and `used_ranges` remain compatible with the previous empty-declaration defaults;
- present `used_citations` and `used_ranges` values must be JSON lists;
- every list member must be a JSON object;
- each citation member must carry a non-empty string `citation_id`;
- each range member must carry an object-valued `range_ref`.

Nine parameterized regression cases cover the Codex example, object-valued collections, scalar list members, missing, empty and non-string citation IDs, and missing or non-object range references. All malformed inputs return exit code 2 with empty stdout and no traceback.

Verification on the exact declaration-hardening revision:

- focused answer-delta and CLI tests: `40 passed in 1.29s`;
- relevant domain, CLI and retrieval-diagnostics tests: `176 passed in 1.66s`;
- broad suite excluding only the two already documented host-blocked Bubblewrap files: `4893 passed, 2 skipped in 189.12s`;
- durable broad-test task: `2f90a62335ff47c0b22eaff8`;
- durable lifecycle receipt SHA-256: `6963f8dce31bd680825296805c2489c61ef8258c0fdf6623c8bdaf78ce52fb9b`;
- Ruff changed-scope check: pass;
- graph-maintainability ratchet: pass;
- module reachability: `205 production modules, 0 unproven, 0 documentation-only, 0 test-only`.

Thirty fresh-process normal CLI starts were measured after the broad suite completed:

| Revision | Median | p90 | Minimum | Maximum |
|---|---:|---:|---:|---:|
| base `main` | 142.541 ms | 146.209 ms | 137.695 ms | 151.107 ms |
| declaration-hardened implementation | 144.485 ms | 147.171 ms | 141.525 ms | 151.200 ms |

Observed median delta: `+1.944 ms` or approximately `+1.36%`. The declaration validator remains behind the lazy diagnostics parser and executes only for `diagnostics answer-delta`. The normal-start delta is reported as measured and may include fresh-process noise.

Rollback of this addendum is the revert of `dcba932d00e074f685da26a703ebf777271d3a21`. Current-head GitHub CI and a fresh Codex review remain separate post-push gates.


## Fifth review-hardening addendum

Codex reviewed PR head `737538559d9064648019e7b2b7ae5a4a90dcf037` and identified a fifth P2 boundary issue. Empty strings in `expected` or `top_results` are valid Python strings but match every path during substring comparison, producing a false high-confidence `target_in_top_k` diagnosis.

The finding is addressed by revision `f2c55552e69e47c3f98c0c74ae0957cb2199237a`.

- Parent head: `737538559d9064648019e7b2b7ae5a4a90dcf037`
- Path-hardening diff bytes: `2065`
- Path-hardening diff SHA-256: `e9a4b7bb6050e6e8955a33d75928be517273008675ba1b28d5acfcae60563461`

The existing string-list validator now requires every present `expected` and `top_results` member to contain non-whitespace text. Empty lists remain valid. Four regression cases cover empty and whitespace-only members in both fields.

Verification on the exact path-hardening revision:

- focused CLI and retrieval-diagnostics tests: `64 passed in 1.45s`;
- relevant domain, CLI and retrieval-diagnostics tests: `180 passed in 1.80s`;
- broad suite excluding only the two documented host-blocked Bubblewrap files: `4897 passed, 2 skipped in 149.84s`;
- durable broad-test task: `4b602c2afd684d8486e930a6`;
- durable lifecycle receipt SHA-256: `1a82112726764c2a383b418a8e5a500ace97405195b123f1887a81d7b89a0859`;
- Ruff changed-scope check: pass;
- graph-maintainability ratchet: pass;
- module reachability: `205 production modules, 0 unproven, 0 documentation-only, 0 test-only`.

Thirty fresh-process normal CLI starts were measured after the broad suite completed:

| Revision | Median | p90 | Minimum | Maximum |
|---|---:|---:|---:|---:|
| base `main` | 137.554 ms | 139.092 ms | 135.129 ms | 142.155 ms |
| path-hardened implementation | 139.565 ms | 143.065 ms | 135.950 ms | 146.168 ms |

Observed median delta: `+2.011 ms` or approximately `+1.46%`. The path-member validation remains behind the lazy diagnostics parser and executes only for `diagnostics eval-report`. The normal-start delta is reported as measured and may include fresh-process noise.

Rollback of this addendum is the revert of `f2c55552e69e47c3f98c0c74ae0957cb2199237a`. Current-head GitHub CI and a fresh Codex review remain separate post-push gates.
