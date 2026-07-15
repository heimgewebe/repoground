# RepoBrief fleet generation and retention

## Decision

The fleet publisher uses a content identity instead of a timestamp as the generation decision. A repository is regenerated only when at least one input that can alter the result changes:

- the remote default-branch commit;
- the canonical RepoBrief generator inputs: the two RepoBrief CLI entry files plus `core`, `contracts`, and `retrieval`;
- the explicit publication configuration;
- the collision-free publication identity (`owner__repository`).

A timestamp remains in the directory name only to order retained history. It is not sufficient to trigger generation.

Service, Web UI, test, and documentation-only changes are deliberately outside the generator-input digest. They cannot alter a RepoBrief bundle produced by `external-manifest refresh` and therefore must not regenerate the fleet. The digest is built from Git blob identities, modes, and paths for the allowlisted generator inputs; missing mandatory CLI entry files fail closed.

Stable external manifests and consumer-local bundle paths use `owner__repository` rather than the repository name alone. This prevents repositories with the same name under different GitHub owners from sharing one publication address. Only these owner-qualified stable manifests are authoritative reachability roots. Existing name-only external paths remain frozen compatibility data: the fleet publisher neither updates them nor uses their possibly stale targets to authorize or block canonical retention.

## Retention policy

Each repository and ref keeps the latest three successful publication directories. Consumer-local content-addressed copies are retained while their SHA-256 is referenced by one of those versions or by a stable external manifest.

Three versions provide:

1. the current state;
2. the previous state for direct comparison;
3. one additional rollback or trend point.

Keeping only one version saves more storage but removes useful comparison and recovery evidence. Keeping many complete generations multiplies storage without equivalent operational benefit. Operators may choose a value from 1 through 10, but the fleet default remains 3.

## Reachability roots

A reachability root is authoritative evidence that a publication is still in use. Retention must not remove a directory that is equal to, contains, or is contained by any current root.

The publisher rebuilds the protected set before every destructive step from:

- canonical owner-qualified stable external manifests;
- every valid fleet state file and its `publication_dir`;
- active publication markers under `STATE_ROOT/active-publications`;
- explicit repeated `--protect-path` arguments.

State and marker files are parsed strictly. An unsupported schema, missing `publication_dir`, missing current state target, symlink, or path outside the managed RepoBrief roots aborts cleanup. A stale active marker therefore retains data rather than guessing that a publication is dead. Removing such a marker requires separate operator inspection; retention never expires it automatically.

## Active publication markers

Before generation starts, the publisher writes a marker containing the repository, ref, fingerprint, process ID, and intended publication directory. The marker is cleared only after the generated bundle has been validated and the new state pointer has been written.

This closes the interval in which cleanup could otherwise remove a directory that another publisher is still creating. If generation fails, only its newly allocated output is discarded. If the process stops after producing valid output but before committing state, the remaining marker deliberately protects the output until it is inspected.

## Strict storage classification

Cleanup recognises only declared layouts:

- current bundles: `bundles/<owner__repo>/<ref>/<timestamp-fingerprint>`;
- modern legacy bundles: `repobrief-auto/<owner__repo>/<ref>/<timestamp>`;
- older direct legacy bundles: `repobrief-auto/<legacy-group>/<timestamp>`;
- retired special bundles: `repobrief-auto/<group>/<timestamp>`;
- localised copies: `external/_bundles/<owner__repo>/<ref>/<sha256>`.

Timestamp directories must match the canonical UTC naming pattern. Localised directories must be exact lowercase SHA-256 values. Files, symlinks, mixed legacy layouts, malformed names, or any other unexpected entry abort cleanup instead of being ignored or guessed about.

## Transactional deletion

Deletion is not performed directly on the selected source directory.

For every candidate the publisher:

1. records a tree snapshot containing device and inode identity, file metadata, and SHA-256 digests;
2. recomputes all reachability roots;
3. verifies that the tree still matches the snapshot;
4. writes a transaction journal under `STATE_ROOT/retention-transactions`;
5. atomically renames the directory into a quarantine directory on the same filesystem;
6. verifies the quarantined identity and recomputes reachability again;
7. restores the source if it became protected;
8. otherwise deletes only the quarantined copy and records the terminal result.

The source and its exact group must resolve below one of the three managed RepoBrief roots. Symlinks and non-regular files inside a candidate are rejected. These checks are repeated immediately before the irreversible step, so a parallel state or manifest change causes retention to preserve or restore the data.

## Crash recovery

Every normal fleet run first reconciles unfinished retention transactions. Reconciliation is idempotent: repeating it produces the same safe outcome.

- A planned transaction whose source is still present is terminalised without deleting it.
- A source already moved into quarantine is restored when it has become reachable, otherwise the quarantined copy is deleted.
- A transaction journal that says `quarantined` while both copies are absent is recorded as an already completed delete.
- Two copies, an identity mismatch, malformed metadata, an unknown state, or loss of both copies from a merely planned transaction aborts reconciliation.

Preview reconciliation without modifying data:

```bash
rb-publish-fleet --reconcile-prune
```

Apply the deterministic reconciliation decision:

```bash
rb-publish-fleet --reconcile-prune --apply-prune
```

## Cleanup operation

Bulk cleanup is dry-run by default. It writes a machine-readable receipt and does not delete data:

```bash
rb-publish-fleet --prune-current --prune-legacy --prune-special --retention 3
```

Apply only after reviewing that receipt and protecting any additional historical evidence:

```bash
rb-publish-fleet --prune-current --prune-legacy --prune-special --retention 3 --apply-prune \
  --protect-path /exact/path/to/protected/version
```

An apply run uses the same strict classification and fresh reachability checks as the dry run. A cleanup error is written to the receipt and returns a failing exit status.

## General safety controls

- The old unrestricted `--force` option is rejected.
- A forced republish is possible only for explicitly named repositories and requires a reason.
- Concurrent fleet runs are blocked by a process lock.
- Dedicated tool and source worktrees must be clean, detached, and belong to the expected repository. Dirty, ignored, foreign, or branch-attached worktrees abort the run and are never cleaned or force-removed.
- A failed generation is never written as the current state.
- Deletion requires the explicit `--apply-prune` switch.

## Runtime state

The installer leaves automatic publication paused unless invoked with `--enable`. Installation or migration must not silently resume generation.

When enabled, the watcher uses `OnCalendar=hourly` with a bounded randomized delay. `Persistent=true` performs one catch-up run after downtime.

Legacy source-only state markers are not trusted as proof that generator and configuration inputs are unchanged. The publication fingerprint schema is v3 because it combines the owner-qualified publication identity with the scoped generator-input digest. The first explicit reactivation after migration can therefore produce one controlled publication per repository; the next unchanged cycle must skip every repository.
