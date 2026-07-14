# RepoBrief External Publish v1 — Proof

Date: 2026-07-06
Last hardened: 2026-07-14

## Decision

External manifest publication belongs to RepoBrief/Lenskit, not the Heimgewebe-Systemkatalog. The Heimgewebe-Systemkatalog observes external manifest references; it must not create dumps or publish producer-owned manifests.

## Boundary

The `publish` command takes an existing Brief Bundle manifest and a caller-chosen publication root. The publication root is explicit. RepoBrief does not decide whether that root is a Git checkout, object-store synchronization directory, web root, or local artifact directory.

The portable bundle copy remains content-addressed below:

```text
<publication-root>/external/_bundles/<repository>/<ref>/<source-manifest-sha256>/...
```

## Generation-coherent publication contract

Since the 2026-07-14 RBV1-T024 hardening, one publication creates an immutable generation containing all requested family manifests:

```text
<publication-root>/external/_generations/<repository>/<ref>/<generation-id>/generation.json
<publication-root>/external/_generations/<repository>/<ref>/<generation-id>/families/repobrief/manifest.json
<publication-root>/external/_generations/<repository>/<ref>/<generation-id>/families/lenskit/manifest.json
```

The generation identifier is a deterministic SHA-256 over the repository, ref, source bundle-manifest SHA-256, and sorted family set. Every authoritative family manifest records the same generation identifier and the same generation timestamp.

A complete generation becomes authoritative only through one atomically replaced pointer:

```text
<publication-root>/external/_current/<repository>/<ref>/generation.json
```

The reader rule is deliberately singular:

1. Read the pointer exactly once.
2. Validate its repository, ref, generation identifier, and canonical descriptor path.
3. Validate the descriptor bytes and SHA-256.
4. Validate the source bundle manifest and every declared family manifest by canonical path, byte count, SHA-256, and generation binding.
5. Reject the publication if any check fails.

Consumers must not independently select the newest family files by timestamp or directory enumeration. That could recreate the mixed-generation problem the pointer contract prevents.

## Compatibility path and migration rule

The historical stable paths remain available for single-family consumers:

```text
<publication-root>/external/repobrief/<repository>/<ref>/manifest.json
<publication-root>/external/lenskit/<repository>/<ref>/manifest.json
```

These files are compatibility projections, not the authoritative multi-family commit point. Each projection records:

- `publicationGeneration.id`;
- `publicationGeneration.authoritative: false`;
- the authoritative generation-manifest path;
- the atomic pointer path;
- the selection rule `read_pointer_once_then_verify_complete_generation`.

Existing consumers can continue reading one stable family path. Consumers that need cross-family coherence must migrate to `read_external_manifest_publication(...)` or implement the documented pointer-verification rule.

`recover_external_manifest_publication(...)` deterministically rebuilds the stable compatibility projections from the already committed generation. It never chooses a generation by directory order and never promotes an unpointed generation.

## Interruption and recovery semantics

Publication is serialized per repository/ref lane with an exclusive advisory `flock` at:

```text
<publication-root>/external/_locks/<repository>/<ref>/publish.lock
```

The write order is:

1. verify and materialize the source bundle;
2. build all family manifests in a temporary generation directory;
3. fsync files and directories;
4. atomically install the immutable generation directory;
5. atomically replace and read back the one generation pointer;
6. refresh the non-authoritative compatibility projections.

Consequences:

- Failure before or between family writes cannot change the authoritative pointer.
- Failure after generation installation but before pointer replacement leaves only an unselected immutable generation.
- Failure after pointer replacement cannot produce a mixed authoritative generation because the pointer selects one complete descriptor-bound set.
- Failure while refreshing historical stable paths produces `committed_compatibility_degraded`; authoritative generation reading remains complete, and recovery can rebuild the projections.
- A visible pointer whose parent-directory fsync failed is reported as `committed_durability_uncertain`; the exact pointer and generation are still read back and verified rather than silently declared durable.
- Concurrent publishers are serialized. The later lock holder may become the winner only after publishing and verifying its own complete generation.

## Difference from `write`

`write` writes one manifest to one explicit output path. It does not establish a multi-family generation.

`publish` uses the generation protocol above and then maintains the historical stable paths as compatibility projections.

## Portable-root and integrity hardening

The referenced bundle manifest must live inside the explicit publication root after consumer-local materialization. This prevents producer paths such as `../../../../../merges/...` from being advertised where consumers cannot resolve them.

The external reference includes linked post-emit sidecars from the bundle manifest `links` surface, specifically `post_emit_health_path` and bundle-surface validation links, without mutating the bundle manifest. These sidecars are intentionally not normal bundle artifacts because that would create self-hash circularity; the external publication may still advertise them as observed companion artifacts with byte count and SHA-256.

Regular-file reads use no-follow semantics. Reused content-addressed bundles and generation directories reject symlinks, missing entries, unexpected entries, byte mismatches, and SHA-256 mismatches.

## Focused evidence

The focused suite covers, among other cases:

- one committed generation shared by all families;
- failure between family writes preserving the old authoritative generation;
- pointer-write failure preserving the old authoritative generation;
- post-pointer compatibility failure plus deterministic recovery;
- visible pointer with uncertain directory-fsync durability;
- tampered family-manifest rejection;
- symlinked pointer rejection;
- concurrent publisher serialization;
- idempotent immutable-generation reuse;
- portable bundle survival after producer-source removal.

Run:

```text
python3 -m pytest -q merger/lenskit/tests/test_external_manifest_reference.py merger/lenskit/tests/test_external_manifest_generation.py
python3 scripts/ci/check_graph_maintainability.py --root . --format json
```

## Non-goals and non-claims

The publication protocol does not create or refresh a source snapshot, mutate the Heimgewebe-Systemkatalog, import into Bureau, dispatch agents, or establish semantic truth, merge readiness, runtime correctness, repo understanding, distributed consensus, cross-host transactionality, remote freshness, or guarantees beyond the local filesystem and explicit readback evidence.
