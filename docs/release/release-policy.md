# RepoGround release-candidate policy

## Purpose

A release candidate is a deterministic source archive used to verify that one
Git commit can be packaged, hashed and reconstructed consistently. RepoGround
source candidates are distributable under Apache-2.0, but candidate creation
alone does not designate an archive as an official project release.

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
  --out /tmp/repoground-candidate
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
  --candidate-dir /tmp/repoground-candidate \
  --repo .
```

Self-contained verification checks hashes and archive safety. Passing `--repo`
also compares every archived file, mode and symlink with the manifest-bound Git
commit.

## Dependency locks

The release-supported Python 3.12 core uses four generated lock surfaces:

- `requirements/repoground-runtime.lock.txt`;
- `requirements/repoground-dev.lock.txt`;
- `requirements/repoground-browser.lock.txt`;
- `requirements/repoground-lock-tools.lock.txt` for the lock compiler itself.

Every resolved package is exactly versioned and carries SHA-256 hashes. The
input files remain human-maintained; the lock files are regenerated with
`scripts/release/compile_dependency_locks.sh` and reviewed as normal source.

## Optional semantic extension

Semantic reranking remains outside the default/core dependency set. It has one
explicitly supported reproducible target:

- CPython 3.12;
- Linux x86-64;
- CPU-only Torch;
- selected binary wheels only.

Its 58-package closure is stored in
`requirements/repoground-semantic-linux-x86_64-py312.lock.txt`. Every selected
wheel has exactly one SHA-256, and Torch is bound to a direct target-specific
CPU wheel URL plus hash. Other platforms fail closed and are not implied by the
lock.

The machine-readable platform boundary is
`docs/release/repoground-semantic-platforms.v1.json`. Regeneration and
byte-for-byte checking use the digest-pinned container wrapper:

```bash
scripts/release/compile_semantic_lock.sh --check
```

An isolated installation check uses:

```bash
scripts/release/compile_semantic_lock.sh \
  --verify-install /tmp/repoground-semantic-install
```

The release-candidate manifest records this semantic surface as
`optional_locked` and `default_enabled: false`. This proves neither semantic
quality, model availability, vulnerability absence, GPU support nor readiness
to enable semantic reranking by default.

## CI boundary

The `release-candidate` job builds the same commit twice in separate output
directories, compares all bytes and verifies the candidate against Git. It does not upload or publish the source archive automatically. This is an
operational CI boundary, not a restriction on distribution rights granted by
Apache-2.0.
