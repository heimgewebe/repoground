# RepoBrief External Publish v1 — Proof

Date: 2026-07-06

## Decision

External manifest publication belongs to RepoBrief/Lenskit, not Cabinet. Cabinet observes external manifest references; it must not create dumps or publish producer-owned manifests.

## Boundary

The new publish command takes an existing Brief Bundle manifest and a caller-chosen publication root. It writes bounded manifest references under this deterministic layout:

```text
<publication-root>/external/repobrief/<repository>/<ref>/manifest.json
<publication-root>/external/lenskit/<repository>/<ref>/manifest.json
```

The publication root is explicit. RepoBrief does not decide whether that root is a Git checkout, object store sync directory, web root, or local artifact directory.

## Difference from write

`write` writes one manifest to one explicit output path.

`publish` writes one or more manifest families to the stable external layout below a publication root.

## Non-goals

The command does not create or refresh a source snapshot, mutate Cabinet, import into Bureau, dispatch agents, or claim semantic truth, merge readiness, runtime correctness, or repo understanding.


## 2026-07-09 hardening follow-up

External manifest publication is now portable-root strict for the stable `publish` path: the referenced bundle manifest must live inside the explicit publication root. This prevents producer output such as `../../../../../merges/...` from being published into a Git checkout where consumers cannot resolve the bundle.

The external reference also includes linked post-emit sidecars from the bundle manifest `links` surface, specifically `post_emit_health_path` and bundle-surface validation links, without mutating the bundle manifest. These sidecars are intentionally not normal bundle artifacts because they would otherwise create self-hash circularity; the external publication surface may still advertise them as observed companion artifacts with bytes and sha256.

Additional regression coverage:

- `test_publish_rejects_bundle_manifest_outside_publication_root`
- `test_external_manifest_refresh_rejects_output_outside_publication_root`
- `test_external_manifest_refresh_creates_portable_bundle_and_references`
- `test_build_includes_linked_post_emit_health_sidecar`
- `test_linked_sidecar_must_remain_inside_bundle_directory`

The refresh path now validates containment before generating a snapshot. A caller must place `--out` at or below the explicit publication root; the portable publisher boundary is not weakened to accommodate legacy callers that generated bundles elsewhere.

## Target proof

```text
python3 -m pytest merger/lenskit/tests/test_external_manifest_reference.py -q
```

Expected: publication path helper, core publisher, and CLI publish path pass.
