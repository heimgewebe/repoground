# RepoGround T009 Contract Hardening v2 — Proof

## Scope

This corrective slice repairs report-renderer contract defects that remained in the
already-merged PR #1098 without rewriting its historical evidence. The implementation
commit is `684fd3aa8f0b99f6b743386e233d09b997144310` with tree
`457e8af17214a216035a9b3a704ef4c746c9ced2`.

## Corrected contracts

- one frozen emission projection for selected, includable, emitted and metadata-only counts;
- plan-only reports emit zero content claims in header, YAML, plan and repo snapshots;
- extension filters are applied instead of merely normalized;
- render-local file copies prevent mutation of caller-owned `FileInfo` objects;
- canonical SHA-256 path anchors and collision-safe legacy aliases;
- single-line Base64url JSON machine markers that round-trip the original path;
- structured diagnostics in the existing YAML metadata block;
- context-bound redaction without broad long-identifier false positives;
- fail-closed benchmark commit/tree/dirty checks and explicit smoke-gate semantics;
- fail-closed evidence validation and a real two-revision comparison.

## Revision binding

| Role | Commit | Tree |
|---|---|---|
| PR #1098 base | `2afc2836fa1a49a593c7b57eda43086844e8fb2b` | `dc591643961ce7c44513ba488cf213dc35c7bd61` |
| merged defect state | `c91d640bce2b14c4a78a64e83169d56c818fa662` | `36113af31c4cb6ba381302b8fcef61a024049336` |
| corrective implementation | `684fd3aa8f0b99f6b743386e233d09b997144310` | `457e8af17214a216035a9b3a704ef4c746c9ced2` |

## Verification

- focused semantic, evidence, link, redactor and benchmark matrix: 120 passed;
- broad repository suite excluding the two host-blocked Sidecar files: 4,853 passed, 2 skipped;
- Ruff over all changed Python files: pass;
- `git diff --check`: pass;
- graph maintainability ratchet: 197 findings, maximum complexity 138, no new finding;
- two-revision renderer comparison: no unapproved difference;
- CI shallow-history regression: 84 passed in the complete checkout;
- depth-1 CI simulation: 4 passed and 2 explicitly skipped because historical objects were unavailable;
- performance smoke gate: pass for every measured non-optional case, with 5% timing and traced-memory ceilings.

The two excluded Sidecar test files fail because Bubblewrap cannot create a namespace
on the host (`Resource temporarily unavailable`). The same failure was reproduced on
the unchanged merged-defect commit, so it is not attributed to this patch.

## Evidence

The canonical corrective evidence is
`docs/proofs/repoground-legacy-t009-delivery.evidence-v2.json`. It references five
new, hash-bound artifacts. Historical T009 evidence files remain unchanged.

## Current delivery state

Verification is `pass`; delivery remains `pending` until the corrective branch is
pushed, required GitHub checks pass on the final head, the PR is merged, the immutable
runtime is deployed and Bureau truth is reconciled.

## Non-claims

This proof does not establish production deployment, final GitHub check success,
resolution of the host Bubblewrap failure or Bureau closeout.
