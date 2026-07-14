# RepoBrief latest-complete registry v2 proof

Task: `RBV1-T021`

Status: implementation proof for byte-consistent manifest capture, unambiguous source lanes, fail-closed v1 migration and explicit publication durability receipts.

## Problem closed by v2

Version 1 could parse a manifest and hash it in separate reads, identify unrelated local repositories only by a shared display name, leave a persistent lock-file artifact, and surface some failures after `os.replace` without a machine-readable distinction between “not written” and “visible but not yet proven durable”. A legacy registry with an implausibly future clock could also block valid candidates indefinitely.

Version 2 addresses those failure modes without turning read paths into refresh paths.

## Byte-consistent candidate capture

The bundle manifest is read once as bytes. JSON parsing, byte length and SHA-256 all derive from that one captured payload. The registry records:

- `manifest_capture: single_read_bytes_sha256_bound`;
- the captured byte length;
- the SHA-256 of those exact bytes.

The read-only status path uses the same single-capture rule for manifest hash comparison and eligibility recomputation. Sidecars remain independently observed artifacts and retain their own recorded SHA-256 values.

## Source-lane identity

Each recorded repository must contribute a source identity:

- credential-free normalized network `repo_remote`, when available; otherwise
- SHA-256 of the normalized recorded **absolute** repository root. Local `file://` remotes are not treated as global identities. Relative roots are rejected as context-dependent and therefore ambiguous.

The raw local root is not copied into the registry. URL user information, query parameters and fragments are removed before a remote is stored or used in the lane. Every repository in a multi-repository source must be identifiable; a partially identified lane is ineligible. Equal display names therefore do not collapse unrelated roots.

## v1 read and migration boundary

Version 2 can read an existing v1 registry only when its source lane is unambiguous from recorded remotes. A v1 registry without remote identity fails closed.

A valid remote-bound v1 registry is migrated by an explicit write. An implausibly future bundle-generation timestamp is treated as an invalid legacy ordering claim and replaced by the current eligible v2 candidate for the same lane. Successful receipts list the legacy future-clock fields that were observed. A future `updated_at` alone does not affect bundle ordering and therefore cannot justify downgrading a newer legacy bundle; normal generated-at ordering still applies. A future-clock v2 registry fails closed rather than being silently rewritten.

## Publication protocol

Writers serialize with an advisory lock on the parent directory inode. No persistent `.lock` file is created or modified. The same opened directory descriptor anchors temporary-file creation, replacement, directory `fsync` and readback; path-to-inode identity is checked before and after replacement. Publication uses:

1. component-wise creation of missing target directories, recording the exact paths created by this invocation; concurrent external creation is accepted but not claimed as the writer’s mutation;
2. unique temporary file creation through the locked directory descriptor;
3. byte write, flush and file `fsync`;
4. atomic `os.replace` within that same directory descriptor;
5. parent-directory `fsync`;
6. exact target readback by SHA-256 through the same descriptor;
7. post-publication directory-identity verification.

Temporary-file creation is an explicit mutation even when the file is later renamed or removed. Its generated name and cleanup outcome are included in failure receipts.

An identical v2 retry does not rewrite the file. Before revalidation it compares a stable registry identity covering all registry fields except the write receipt timestamp and the eligibility reference time, so a same-manifest but otherwise manipulated v2 registry cannot masquerade as an identical candidate. It then revalidates the existing bytes plus file and directory durability. An older candidate verifies the directory identity again before returning an unchanged result.

## Machine-readable failure states

The CLI emits JSON errors to stderr. Exit code `2` denotes validation or another failure before publication. Exit code `1` denotes uncertain publication durability.

The write receipt distinguishes:

- `failed_before_replace`: no target replacement observed;
- `failed_before_replace_with_temp_artifact`: no target replacement occurred, but temporary-file cleanup failed and explicit cleanup is required;
- `uncertain_after_replace`: replacement occurred, but directory durability, readback or final directory identity was not confirmed;
- `durability_unconfirmed`: an existing matching registry could not be revalidated, while the retry itself performed no second replacement.

Receipts include phase, error code, exact target directories created by the invocation, temporary-file creation/write/cleanup state, file `fsync`, replacement, directory `fsync`, directory identity, the observation namespace (locked directory descriptor or resolved path), expected and observed target SHA-256, observed writes and a recovery action. They do not claim automatic rollback.

## Read-only boundary

`latest-complete status` may read the registry, manifest, sidecars and an explicitly supplied local repository HEAD. It does not create snapshots, refresh bundles, write the registry, mutate Git, create patches or establish merge readiness.

## Validation scope

Focused tests cover:

- v2 schema validation plus rejection of contradictory source identities;
- single-read parse/hash binding in write and status paths;
- exact source-lane separation for same-name absolute local roots, rejection of relative roots, credential stripping and local-remote fallback;
- complete identity requirements for multi-repository lanes;
- valid v1 migration and ambiguous-v1 rejection;
- future bundle-clock v1 replacement without downgrading a newer bundle for `updated_at` alone;
- monotone selection, fail-closed timestamp collisions, stable-v2 identity checks and verified no-change returns;
- no persistent lock-file side effect;
- symlink target rejection;
- exact directory-creation attribution under concurrent and partial creation, unresolvable path handling, pre/post-replace directory-identity drift and post-replace directory `fsync` failures;
- exact uncertain-state CLI JSON and explicit temporary-file cleanup receipts;
- idempotent durability recovery and truthful no-second-replace evidence;
- sidecar drift and fresh/stale/unknown status behavior.

## Non-claims

This proof does not establish content truth, semantic completeness, remote freshness, runtime correctness outside the exercised paths, test sufficiency, regression absence, repository understanding, review completeness or merge readiness.
