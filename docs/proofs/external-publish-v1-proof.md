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

## Target proof

```text
python3 -m pytest merger/lenskit/tests/test_external_manifest_reference.py -q
```

Expected: publication path helper, core publisher, and CLI publish path pass.
