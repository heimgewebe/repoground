# RepoBrief fleet generation and retention

## Decision

The fleet publisher uses a content identity instead of a timestamp as the generation decision. A repository is regenerated only when at least one input that can alter the result changes:

- the remote default-branch commit;
- the Lenskit generator tree under `merger/lenskit`;
- the explicit publication configuration.
- the collision-free publication identity (`owner__repository`).

A timestamp remains in the directory name only to order the retained history. It is not sufficient to trigger generation.

Stable external manifests and consumer-local bundle paths use `owner__repository` rather than the repository name alone. This prevents repositories with the same name under different GitHub owners from sharing one publication address. Existing name-only external paths are left in place as frozen compatibility data; the fleet publisher no longer updates them.

## Retention

Each repository and ref keeps the latest three successful publication directories. The consumer-local content-addressed bundle copies are pruned to the hashes still referenced by those three versions or by the stable external manifests.

Three versions are the default compromise:

1. current state;
2. previous state for a direct comparison;
3. one additional rollback or trend point.

Keeping only one version saves more storage but removes useful comparison and recovery evidence. Keeping eight versions multiplied full bundles without enough operational benefit.

## Safety

- The old unrestricted `--force` option is rejected.
- A forced republish is possible only for explicitly named repositories and requires a reason.
- Concurrent fleet runs are blocked by a process lock.
- Dedicated tool and source worktrees must be clean, detached, and belong to the expected repository. Dirty, ignored, foreign, or branch-attached worktrees abort the run and are never cleaned or force-removed.
- A failed generation is removed only from its newly allocated output directory and is never written as the current state.
- Bulk cleanup is dry-run by default. Deletion requires `--apply-prune`.
- Exact paths can be protected from cleanup with repeated `--protect-path` options.

## Runtime state

The installer leaves automatic publication paused unless invoked with `--enable`. This prevents an installation or migration from silently resuming generation.

Legacy source-only state markers are intentionally not trusted as proof that generator and configuration inputs are unchanged. The first explicit reactivation can therefore produce one controlled publication per repository before normal fingerprint-based skipping begins.

The publication fingerprint schema is now v2 because the owner-qualified publication identity is part of the content decision. Therefore the first enabled fleet cycle after this migration intentionally republishes each inventoried repository once into its collision-free address. A second immediate cycle with unchanged source commits, generator code and configuration must skip every repository.

Dry-run current, legacy, and retired special storage:

```bash
rb-publish-fleet --prune-current --prune-legacy --prune-special --retention 3
```

Apply only after reviewing the receipt and protecting any referenced historical paths:

```bash
rb-publish-fleet --prune-current --prune-legacy --prune-special --retention 3 --apply-prune \
  --protect-path /exact/path/to/protected/version
```
