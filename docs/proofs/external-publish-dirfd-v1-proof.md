# RepoBrief External Publish — trusted dirfd proof

Date: 2026-07-15
Task: `RBV1-T025`

## Decision

Security-sensitive RepoBrief external publication no longer relies on a sequence of pathname checks followed by pathname-based writes. Source bundle access and publication access are anchored to already-open directory file descriptors (`dirfd`). Descendant traversal, creation, inspection, locking, replacement, tree verification and cleanup use `openat`-equivalent Python operations with `dir_fd`.

The public RepoBrief API remains unchanged. Successful publication reports:

```json
{
  "generation": {
    "filesystemBinding": "trusted_dirfd_openat"
  }
}
```

## Threat model

In scope:

- an accidental or hostile same-host actor replaces a source or publication parent directory while RepoBrief is operating;
- a path component is changed into a symbolic link;
- a regular file is replaced by a symbolic link or special file;
- publication-root, lane, generation, pointer or compatibility parents are renamed concurrently;
- a source file or source parent changes identity while it is being copied;
- a concurrent operation creates an already expected content-addressed destination;
- an interrupted write leaves a temporary file or unselected generation.

The implementation must not escape the intended source/publication trees, must not write into a replacement path, and must not report success when the visible path no longer identifies the directory used for the operation.

## Supported platform contract

The hardened path requires a POSIX platform exposing all of these primitives through Python:

- directory-relative `open`, `mkdir`, `rename`, `stat`, `unlink` and `rmdir`;
- `O_DIRECTORY`;
- `O_NOFOLLOW`;
- advisory `flock` for the publication lane.

Every absolute directory is opened component by component from `/`. Every component is opened with `O_DIRECTORY | O_NOFOLLOW`. Missing components may be created only through their already-open parent directory and are then reopened with the same no-follow flags.

A platform without these primitives fails closed with `RootedFilesystemError`. There is no silent fallback to weaker pathname operations.

## Identity binding

A `DirectoryBinding` records the device and inode of an open root directory. Descendant operations select the longest matching active binding and traverse from a duplicated root descriptor.

After security-sensitive reads or writes, RepoBrief reopens the visible path without following links and compares device/inode identity with the descriptor used for the operation. A mismatch is a hard error even when bytes were safely written into the old, renamed directory. This prevents a hidden anchored write from being misreported as a visible successful publication.

Regular-file reads and copies similarly reopen the visible file path and compare identity before a copy is committed.

## Write and replacement protocol

Atomic file replacement:

1. open the target parent directory through the trusted binding;
2. create a random temporary regular file with `O_EXCL | O_NOFOLLOW` relative to that descriptor;
3. write and `fsync` the temporary file;
4. rename it to the target name with source and destination `dir_fd`;
5. `fsync` the parent directory;
6. verify that the visible parent path still identifies that descriptor.

Generation and bundle directories are built as temporary directory trees below an anchored parent and committed by directory-relative rename. Reused content-addressed trees are enumerated through directory descriptors and reject symbolic links, special files, missing entries, unexpected entries and byte/hash mismatches.

The publication lock is opened through its anchored parent, must be a regular file, and verifies the parent identity both before and after the critical section.

## Reader protocol

The authoritative generation reader binds the publication root before reading the pointer. Pointer, descriptor, source bundle and family manifests are opened without following links. The existing generation integrity contract remains in force: canonical paths, byte counts, SHA-256 values, family set, source binding and shared generation identity must all match.

After readback, the publication-root identity is checked again. A root rename during the read therefore fails instead of returning a selection from a no-longer-visible tree.

## Compatibility

The public functions and historical stable family paths remain available. Compatibility projections are still non-authoritative; only the verified generation pointer selects a cross-family state.

Consumers do not need a new CLI flag. Unsupported hosts receive a fail-closed error rather than silently weaker publication.

## Focused adversarial evidence

The focused suites cover:

- symlinked publication-root components;
- symlinked files and linked/special tree entries;
- publication-root replacement before pointer commit;
- source-parent replacement during materialization;
- pointer-parent replacement during atomic pointer write;
- root replacement during authoritative readback;
- parent replacement during a low-level atomic write;
- lock-parent replacement while holding the lock;
- unsupported-platform failure before publication;
- ordinary publication, readback, recovery, crash and concurrent-publisher behavior from the generation protocol;
- source-file identity replacement after copying but before destination commit.

Run:

```text
python3 -m pytest -q \
  merger/lenskit/tests/test_external_manifest_reference.py \
  merger/lenskit/tests/test_external_manifest_generation.py \
  merger/lenskit/tests/test_rooted_filesystem.py \
  merger/lenskit/tests/test_external_manifest_dirfd.py

python3 scripts/ci/check_graph_maintainability.py --root . --format json
```

Current focused result on the final implementation: `60 passed`.

Complete Lenskit suite on the final pre-commit tree: `4003 passed, 1 skipped`.

## CLI dogfood evidence

A real `repobrief external-manifest refresh` run created an agent-portable snapshot of a temporary Git repository and published both families below one bound publication root.

Observed:

- publication status: `committed`;
- generation: `dac4de5d36518fe81cf8c27f8828370032eec020627e07f11fe3995877a8b18b`;
- filesystem binding: `trusted_dirfd_openat`;
- pointer durability: `durable`;
- compatibility status: `ok`;
- independent authoritative readback selected the same generation and both `lenskit` and `repobrief` families;
- pointer SHA-256: `8d434e0b1a902d4a9bdf1d5835607ff1c1febe6c007f41671d160005f66149cc`;
- descriptor SHA-256: `48e2937624a2d7ef0c717fe187c56564040e37448b88e7a26cff22c0247febd1`;
- 200 low-level write/read/lock cycles changed the open-file-descriptor count by `0`.

## Non-claims

This change does not establish:

- resistance to kernel bugs;
- equivalence of network or distributed filesystems to the tested local filesystem semantics;
- a privilege boundary against a more privileged process;
- security on untested platforms;
- distributed consensus or cross-host transactionality;
- remote freshness or semantic truth.

The implementation is a local-filesystem identity and integrity protocol. It is not a sandbox, mandatory access-control system, distributed lock or remote attestation mechanism.
