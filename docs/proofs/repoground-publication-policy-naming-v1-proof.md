# RepoGround publication-policy naming v1 — proof and cutover contract

Bureau task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T021`

Authoritative Bureau run: `BUR-RUN-20260801T010609Z-887777f424`

Repository baseline: `c11446cb7bdf0c166f804fd71f89786bf8ea5396`

Adopted implementation source: `8cf18c930f024cc6950f539d3d1acd76aec8c8a3`

Claim-branch implementation commit before this proof: `507c48ff7a766453241361757106b771b3e118fd`

## Claim proved by this change

The active publication-policy surface uses RepoGround names for the command,
documentation path, environment variables, version option, and default evidence
root. Existing persisted v1 records intentionally keep their historical
`repobrief.*` schema identifiers and the `lenskit_version` field. The naming cut
does not rewrite existing records, manifests, payloads, or historical proofs.

## Recovery provenance

The first coordinated run, `BUR-RUN-20260731T212630Z-f4ac5418b3`, adopted the
same implementation tree and wrote the initial proof draft. Its worker stopped
without terminalising the run; the leases later expired and no process or open
RepoGround pull request remained. Before recovery, its dirty worktree was bound
to explicit retention at exact head
`507c48ff7a766453241361757106b771b3e118fd`. The run was then marked `failed`
with the stale-worker reason, and its unchanged leases were released through
the coordinated pickup release contract.

The current run re-claimed T021 after that terminal readback. Commits
`8cf18c930f024cc6950f539d3d1acd76aec8c8a3` and
`507c48ff7a766453241361757106b771b3e118fd` have the same parent and the same
Git tree `aae3be5f7a7bb6c1ba39953898cc1f9a170441cb`; their direct diff is empty.
The current branch therefore fast-forwarded to the exact previously tested
implementation instead of recreating or rewriting it.

This recovery does not make the predecessor worktree disposable and does not
transfer authority from its uncommitted bytes. It remains retained until the
current run is terminal and its result is independently readable.

## Bound pre-cutover inventory

The first inventory was read while the predecessor run held the command paths,
both state roots, the publication component, and the fleet timer. It established:

- `~/.local/bin/rb-publication-policy` was a regular, non-symlink file with
  SHA-256 `64278d6fe48b95931f7c75386004694ef3cf9c02aa4bef7f5e18b035cf90f68c`
  and contained the exact retirement marker
  `rb-publication-policy is deprecated; use repoground-publication-policy`.
- `~/.local/bin/repoground-publication-policy` was a regular file with SHA-256
  `0d61e95897f6cc67cc98e7a5007872961a1dbc54a0cfc88c42f809e1390b096a`.
- Neither `~/.local/state/repobrief-publication-policy` nor
  `~/.local/state/repoground-publication-policy` existed.
- No matching `rb-publication-policy` or `repoground-publication-policy`
  process was active in the bounded process read.
- No user-systemd unit referenced either publication-policy command; the only
  matching live file was the installed retirement delegate itself.
- `repoground-publish-fleet-watch.timer` was loaded, enabled, active and
  waiting, with `Result=success`.

Because this observation predates the current run, it is historical evidence,
not current host truth. The current run must repeat the bounded command, state,
process and timer inventory immediately before the post-merge installer effect.
Neither inventory proves that no unknown future or external consumer exists.

## Repository changes

- The current operations document is
  `docs/operations/repoground-publication-policy.md`; the former active document
  path is removed.
- `repoground-publication-policy` defaults new evidence to
  `~/.local/state/repoground-publication-policy` and accepts only the current
  `REPOGROUND_PUBLICATION_*` overrides and `--repoground-version` surface.
- The installer validates old and new publisher and publication-policy roots
  before stopping units. It rejects symlinks, non-directories, and dual truth.
- A sole historical publication-policy directory is moved to the RepoGround
  path without rewriting its contents. The target is created with mode `0700`.
- The canonical command is installed before the retirement delegate is
  removed. Removal requires the exact pre-cutover SHA-256
  `64278d6fe48b95931f7c75386004694ef3cf9c02aa4bef7f5e18b035cf90f68c`;
  the marker text alone is insufficient. An unknown file, marker-spoofing file,
  symlink, or non-regular object fails closed before any service effect.
- Naming audits now detect the retired command and state-root surface in live
  process and configuration inventories.

## Migration decision for the observed host

Both publication-policy state roots were absent in the initial inventory. The
current pre-effect readback must confirm whether this remains true. If so, the
live cutover must not claim a data migration: the installer creates the
canonical RepoGround root and removes only the hash-observed retirement
delegate after installing the canonical command. It must be invoked with
`--enable` only if the fresh timer readback still shows the timer enabled and
active.

Repository tests separately cover the old-root-only migration and prove byte
preservation for a persisted record containing
`repobrief.publication-record.v1` and `lenskit_version`. They also cover dual
roots, an unknown legacy command, and a marker-spoofing file as pre-effect
failures.

## Persisted identity boundary

The active CLI option `--repoground-version` continues to populate the persisted
`lenskit_version` field. Existing `repobrief.*` bundle and record schema IDs
remain versioned data identities. This change does not establish a new data
schema version and grants no permission to rename or rewrite persisted v1 data.

## Verification receipts

Predecessor-run focused verification on implementation commit `507c48ff`:

- command: `python3 -m pytest -q merger/repoground/tests/test_publication_policy.py merger/repoground/tests/test_fleet_runtime.py merger/repoground/tests/test_naming_audit.py tests/test_naming_hard_cut.py`
- result: `159 passed in 15.59s`
- durable job: `grabowski-job-1be92d63690a`
- finalization receipt SHA-256:
  `67d535d7b8817c26df7996ace7a3083013d40ec65a896738a9811f44d9beeb99`

Current-run verification after the digest-bound wrapper hardening:

- focused wrapper identity tests: `4 passed, 85 deselected`;
- affected suite: `169 passed in 15.84s`;
- Ruff: `All checks passed!`;
- staged-diff whitespace check: passed;
- installer shell syntax job: `grabowski-job-a4cf9ed6ac29`, succeeded with
  finalization receipt SHA-256
  `fcde9501b7459c50ad6b73b189555bacf68b972b383c89aae244636f6d8b5d35`;
- full suite job: `grabowski-job-f71a24724fb0`;
- full suite result: `5283 passed, 12 skipped in 196.45s`;
- full-suite finalization receipt SHA-256:
  `b9f49b048a4cae9e098efdf1ec5c77b5723ef7d97bf1f5f17773ea6f81fe6983`.

GitHub CI, merge and live installation remain separate revision-bound gates and
are not predeclared successful here.

## Post-merge cutover and readback

1. Re-read the exact merged commit and the four host paths above.
2. Re-read matching processes, systemd references and the fleet timer state.
3. Preserve the observed enabled/disabled timer policy; use `--enable` only
   when the fresh pre-effect state is enabled and active.
4. Run `scripts/ops/install_repoground_publish_fleet_runtime.sh` from the exact
   merged checkout with the preserved timer policy.
5. Verify the canonical installed command matches the merged source.
6. Verify the former wrapper and former state root are absent.
7. Verify the canonical state root is a non-symlink directory with mode `0700`.
8. Verify the fleet timer retains its prior enabled policy and is healthy; when
   enabled it must be loaded, active and waiting with a successful result.
9. Record exact before/after hashes and systemd readback in the Bureau run
   evidence before terminalising the task.

## Rollback boundary

Revert the exact implementation merge and reinstall the prior canonical runtime
from a bound checkout. If a historical policy root was moved, stop the timer and
move the same unchanged directory back only when the canonical path is the sole
root and the historical path is absent. Any dual-root, symlink, type, ownership,
or content ambiguity fails closed for manual review. Historical records and
proofs must not be rewritten or deleted.

## Nonclaims

This proof does not establish global absence of unknown consumers, future
consumer compatibility, permission to modify foreign worktrees, permission to
rewrite historical evidence, automatic schema migration, task completion,
merge readiness, successful live installation, or permission to delete the
retained predecessor worktree.
