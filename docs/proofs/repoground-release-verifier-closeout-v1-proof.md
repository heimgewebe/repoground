# RepoGround Release-Verifier Closeout v1

## Scope

This proof is bound to `REPOGROUND-LEGACY-RECONCILIATION-V1-T019` and starts
from merge commit `37a83704695532f8c8d17a532709e3de92cafb38`.

PR #1113 established the archive, member, decompressed-stream, compression-ratio,
member-count and single-blob content-processing limits. This closeout does not
restate that implementation as new work. It closes two remaining input surfaces.

## Candidate metadata limits

The verifier now applies these ceilings before JSON parsing or checksum-line
processing:

- release manifest: 1 MiB
- `SHA256SUMS`: 64 KiB

Both files must be regular non-symlink files. Reading uses an opened descriptor,
checks the opened file type and verifies that its device/inode identity still
matches the pre-open `lstat` result. A read of one additional byte detects growth
past the declared limit.

The release manifest is parsed once and the same parsed object is carried into the
full verification path. Its digest is computed from those captured bytes and reused
for `SHA256SUMS` verification and the final report, so a later pathname replacement
cannot authenticate different bytes. This also avoids a second unbound manifest read
between contract selection and candidate validation.

## Source-bound repository limit

Every immutable Git blob remains individually limited to 16 MiB. The size preflight
now also rejects the aggregate Git-tree content above 128 MiB before the persistent
`git cat-file --batch` content process is opened.

The existing content path still reads, validates and discards at most one bounded
blob at a time.

## Adversarial regressions

The release packaging suite covers:

- oversized manifest rejected before JSON parsing;
- symlinked manifest rejected before reading;
- post-parse manifest replacement rejected because checksums remain bound to the captured bytes;
- oversized `SHA256SUMS` rejected before line processing;
- symlinked `SHA256SUMS` rejected before reading;
- aggregate Git-blob overflow rejected before the content batch starts;
- the archive, PAX/GNU, member-count, compression and single-blob protections from
  PR #1113.

## Validation

Required final evidence:

- targeted release-packaging tests;
- repository hygiene and naming tests;
- Ruff;
- graph/complexity maintainability ratchet;
- full pytest and CodeQL on the final PR head;
- post-merge CI readback.

## Non-claims

This proof does not establish public exposure of the verifier, absence of all CPU
exhaustion below the selected ceilings, release readiness, deployment authorization,
or permission to modify or clean foreign dirty worktrees.
