# RepoBrief release-candidate policy

## Purpose

A release candidate is a deterministic source archive used to verify that one
Git commit can be packaged, hashed and reconstructed consistently. It is not a
public release and does not grant distribution permission.

## Version source

`RELEASE_VERSION` is the packaging-version source. Protocol, schema and core
format versions remain independent. Candidate filenames add the first twelve
characters of the bound Git commit, preventing two different commits from
sharing one candidate identity.

## Build

```bash
python scripts/release/build_release_candidate.py \
  --repo . \
  --ref HEAD \
  --out /tmp/repobrief-candidate
```

The builder:

1. refuses a dirty working tree;
2. resolves the exact commit and tree;
3. reads all source bytes from Git, not from mutable working-tree files;
4. normalizes archive order, ownership, modes and timestamps;
5. writes a gzip stream with timestamp zero;
6. writes a JSON manifest and `SHA256SUMS`.

## Verify

```bash
python scripts/release/verify_release_candidate.py \
  --candidate-dir /tmp/repobrief-candidate \
  --repo .
```

Self-contained verification checks hashes and archive safety. Passing `--repo`
also compares every archived file, mode and symlink with the manifest-bound Git
commit.

## Dependency locks

The release-supported Python 3.12 core uses four generated lock surfaces:

- `requirements/repobrief-runtime.lock.txt`;
- `requirements/repobrief-dev.lock.txt`;
- `requirements/repobrief-browser.lock.txt`;
- `requirements/repobrief-lock-tools.lock.txt` for the lock compiler itself.

Every resolved package is exactly versioned and carries SHA-256 hashes. The
input files remain human-maintained; the lock files are regenerated with
`scripts/release/compile_dependency_locks.sh` and reviewed as normal source.

The optional semantic reranking stack (`requirements-semantic.txt`, including
Torch through sentence-transformers) is intentionally outside this first
candidate contract because its platform-specific dependency closure is not yet
locked.

## CI boundary

The `release-candidate` job builds the same commit twice in separate output
directories, compares all bytes and verifies the candidate against Git. It does
not upload or publish the source archive.
