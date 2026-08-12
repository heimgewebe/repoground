# RepoGround fleet publication v1 — implementation proof and cutover runbook

Bureau task: `heimgewebe/bureau#671`

## Implemented in this change

- the active publisher uses `merger/repoground` generator inputs and no longer falls back to a Lenskit checkout;
- the retired GitHub identity `heimgewebe/lenskit` is not discovered as an independent active publication lane; `heimgewebe/repoground` remains the canonical source identity;
- the canonical user units are `repoground-publish-fleet-watch.service` and `.timer`;
- the existing persisted state contract `repobrief.fleet-publication-state.v1` is retained and extended additively;
- state records distinguish the generator Git commit from the generator-input digest and record the verified bundle-manifest path;
- a successful publication is labelled only `fresh_at_publication`; a later unchanged run performs a new remote-head comparison;
- generator preflight and true per-repository publication failures return a non-zero process status and preserve a machine-readable `fleet-last.json` receipt;
- active publication sources are detached, revision-bound worktrees named with the exact source commit instead of a mutable per-ref checkout;
- if such a revision-bound source contains tracked changes or an unproven managed `build/` residue, the publisher does not reset, delete, or rewrite it. It preserves that worktree, creates a separate clean worktree for the same commit, and writes a create-only `managed-source-recovery` receipt before using the replacement;
- safely obsolete revision worktrees are removed only when they are clean, idle, and not protected by an exact active Grabowski lease. Dirty, active, leased, foreign, or otherwise ambiguous worktrees remain preserved;
- the historical fixed per-ref managed source paths remain untouched. They no longer gate new publication, so old retained evidence or semantic dirty state cannot indefinitely poison the hourly fleet.

## Covered by repository tests

The focused tests cover canonical generator inputs, retired Lenskit alias suppression, persisted-state semantics, installer ordering, generator-preflight failure receipts, tracked dirty-source preservation with clean same-commit replacement, unknown `build/`-residue preservation with clean same-commit replacement, safe revision-worktree pruning, structured true-failure receipts, and an unchanged second run that creates no additional bundle and preserves publication time.

These tests do not establish that the user service has already been installed, that Grabowski already accepts the new revision-bound source identity, or that live repositories have already produced fresh bundles through the new path.

## Post-merge live cutover

1. Teach the consuming Grabowski bundle catalog/freshness reader to accept a revision-bound source name only when its embedded commit matches the bundle provenance exactly; retain fail-closed behaviour for malformed or ambiguous names.
2. Install the merged RepoGround runtime with `scripts/ops/install_repoground_publish_fleet_runtime.sh --enable` only after that reader support is active.
3. Verify the old `rb-publish-fleet-watch.*` units are disabled and absent, and the canonical timer is loaded and enabled.
4. Run a targeted changed publication for RepoGround, then validate the emitted manifest, state record, source-worktree name, and Grabowski freshness result against the observed source and generator commits.
5. Exercise a previously blocked repository and verify that an old fixed dirty/retained checkout is preserved while publication proceeds from the exact new revision path.
6. Run the same targeted command again. It must report `unchanged`, create no new version directory, preserve `created_at`, and update only the bounded freshness observation.
7. Exercise the negative path with isolated environment roots and a missing canonical generator input. It must return non-zero, write `fleet-last.json`, and leave production publications untouched.
8. Only after those checks, allow the hourly timer to process the fleet and inspect every remaining true failure before closing Bureau #671.

## Interpretation boundary

A successful fleet run proves that bundles were produced from the recorded commits under the recorded generator and that the publication source satisfied the publisher hygiene gate at generation time. It does not prove repository understanding, retrieval quality, runtime correctness of the scanned software, or freshness after the recorded check time.
