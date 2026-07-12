# RepoBrief latest-complete registry v1 proof

Task: `RPU-V1-T003`

Status: implementation proof for eligibility-bound, monotone and crash-durable latest-complete RepoBrief publication plus the read-only freshness/status path.

## Implemented surface

This slice adds a small machine-readable registry with kind:

```text
repobrief.latest_complete_registry
```

The registry records:

- bundle stem, manifest path and manifest SHA-256;
- run id and normalized generation timestamp;
- recorded source commit and stable source lane from `snapshot_provenance`;
- health status and SHA-256 for the finalization sidecars;
- an explicit eligibility result;
- the deterministic selection key;
- the publication durability contract;
- freshness status vocabulary and explicit unknown state.

A candidate is publishable only when its generation timestamp is not implausibly in the future, the recorded full source commit is unambiguous, the profile is known, the profile evaluation is not failed, and the required finalization surfaces are acceptable. In particular, `post_emit_health` and every profile-required export gate must pass.

## Read-only status path

The read-only status command is:

```bash
python -m merger.lenskit.cli.main repobrief latest-complete status --registry <registry.json> [--repo <repo>]
```

Without `--repo`, source freshness is `unknown` with reason `live_repo_not_provided`.

With `--repo`, the status path compares the registry's recorded source commit with the explicit local repo `HEAD`:

- matching commit: `fresh`;
- different commit: `stale` with reason `head_drift`;
- unavailable repo or missing commit: `unknown`.

A stale result is not a failure by itself. It is a visible observation that consumers can use before relying on a bundle.

## Explicit write paths

The registry is written only by explicit write operations:

```bash
python -m merger.lenskit.cli.main repobrief latest-complete write --bundle-manifest <manifest> --out <registry.json>
```

or during explicit snapshot creation when the caller passes:

```bash
--latest-complete-registry <registry.json>
```

Read paths do not update the registry.

## Monotone durable publication

Writers serialize on a persistent lane-local advisory lock file. The lock file is an explicit part of the write boundary. Under that lock they compare the candidate with the already published registry using:

```text
generated_at
```

An older or byte-identical candidate leaves the published file byte-identical. Equal timestamps with different manifest identities fail closed instead of choosing by an arbitrary hash or run-id ordering. A source-lane mismatch fails closed. A newer eligible candidate is written to a temporary file, file-synchronized, atomically replaced, followed by a parent-directory `fsync` and exact readback. This prevents a delayed older run from moving the pointer backwards and closes the rename-without-directory-sync durability gap.

The status path rechecks the stored manifest hash, recomputes eligibility from the current sidecars and reports sidecar-hash drift without mutating the registry.

## Boundary

The read-only status path does not:

- create snapshots;
- refresh bundles;
- mutate Git;
- alter the source working tree;
- write registry files;
- write bundle artifacts;
- create pull requests;
- run tests or reviews.

## Validation scope

Tests cover:

- registry field emission and JSON-schema validation;
- eligibility rejection for incomplete candidates;
- monotone and idempotent selection, future-timestamp rejection and fail-closed timestamp collisions;
- source-lane mismatch rejection;
- symlink-target rejection;
- file and parent-directory synchronization;
- health signal projection and sidecar hash drift;
- fresh/stale/unknown freshness states;
- read status not writing files or mutating the registry;
- CLI write/status and explicit publication during `snapshot create`.

## Non-claims

This proof does not establish:

- content truth;
- semantic or domain completeness beyond the checked RepoBrief finalization contract;
- runtime correctness;
- test sufficiency beyond the checked scope;
- review completeness;
- merge readiness;
- repo understanding;
- claim truth;
- freshness against a remote branch;
- agent quality improvement.
