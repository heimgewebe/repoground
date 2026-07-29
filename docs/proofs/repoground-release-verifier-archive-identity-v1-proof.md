# RepoGround release verifier archive identity proof

- Base: `c0bd029f0be3f370cf946fb311380ea3ea9df4ea`
- Source candidate: `candidate-58d06a2303501fdfef712ac9`
- Finding: archive hashing, materialization, header inspection and reporting previously reopened the candidate path independently.
- Fix: one `O_NOFOLLOW` descriptor now binds device, inode, metadata, byte size, SHA-256, gzip materialization and final report.
- Negative control: replacing the archive path after hashing is rejected in both self-only and source-bound verification.
- Scope: release verifier and release-packaging regressions only; no service or T004 files changed.

## Verification

- Scoped Ruff: pass.
- Focused archive-identity regressions: `7 passed, 51 deselected`.
- Complete release-packaging suite: `58 passed`.
- Semantic lock reproduction: pass.
- Repository-wide Ruff: pass.
- Graph maintainability ratchet: pass.
- Remaining non-browser/non-live suite excluding the two Bubblewrap-dependent sidecar files: `5125 passed, 12 skipped, 13 deselected`.
- Unfiltered local suite: `5135 passed, 12 skipped, 13 deselected, 33 failed`; all 33 failures are confined to `tests/test_patch_evaluation_sidecar.py` and `tests/test_patch_evaluation_sidecar_host_readback.py` because the host rejected Bubblewrap namespace creation with `Resource temporarily unavailable`.
- Exact-base control on unchanged `c0bd029f0be3f370cf946fb311380ea3ea9df4ea`: the representative sidecar test fails with the same Bubblewrap namespace error, so this local infrastructure failure is not introduced by the patch.

## Boundaries

- This proof establishes local regression and static-gate results, not GitHub CI or merge readiness.
- The descriptor identity checks detect path replacement and ordinary in-place metadata changes; they do not claim mandatory exclusion against an equally privileged hostile process outside the verifier contract.
