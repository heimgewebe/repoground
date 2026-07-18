# RepoGround fleet publication v1 — implementation proof and cutover runbook

Bureau task: `heimgewebe/bureau#671`

## Implemented in this change

- the active publisher uses `merger/repoground` generator inputs and no longer falls back to a Lenskit checkout;
- the canonical user units are `repoground-publish-fleet-watch.service` and `.timer`;
- the existing persisted state contract `repobrief.fleet-publication-state.v1` is retained and extended additively;
- state records distinguish the generator Git commit from the generator-input digest and record the verified bundle-manifest path;
- a successful publication is labelled only `fresh_at_publication`; a later unchanged run performs a new remote-head comparison;
- generator preflight and per-repository failures return a non-zero process status and preserve a machine-readable `fleet-last.json` receipt.

## Covered by repository tests

The focused tests cover canonical input paths, independent RepoGround discovery, persisted-state field semantics, installer ordering, generator-preflight failure receipts, and an unchanged second run that creates no additional bundle and preserves publication time.

These tests do not establish that the user service has already been installed or that live repositories have already produced fresh bundles.

## Post-merge live cutover

1. Install the merged runtime with `scripts/ops/install_repoground_publish_fleet_runtime.sh --enable`.
2. Verify the old `rb-publish-fleet-watch.*` units are disabled and absent, and the canonical timer is loaded and enabled.
3. Run a targeted changed publication for RepoGround, then validate the emitted manifest and state record against the observed source and generator commits.
4. Run the same targeted command again. It must report `unchanged`, create no new version directory, preserve `created_at`, and update only the bounded freshness observation.
5. Exercise the negative path with isolated environment roots and a missing canonical generator input. It must return non-zero, write `fleet-last.json`, and leave production publications untouched.
6. Only after those checks, allow the hourly timer to process the agreed core-repository fleet and inspect every failure before closing Bureau #671.

## Interpretation boundary

A successful fleet run proves that bundles were produced from the recorded commits under the recorded generator. It does not prove repository understanding, retrieval quality, runtime correctness of the scanned software, or freshness after the recorded check time.
