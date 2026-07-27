# RepoGround retired release contracts v1 — Proof

## Scope

This change was rebased onto RepoGround `main` commit
`8ec3c7d2a5d04b3df63d52c5cf5eb16b725e418c` and implements Bureau task
`REPOGROUND-LEGACY-RECONCILIATION-V1-T018`, sourced from candidate
`candidate-1696513020f86c092c296a98` event `1324`.

It retires exactly these former release contracts:

- `merger/repoground/contracts/repobrief-release-candidate.v1.schema.json`
- `merger/repoground/contracts/repobrief-semantic-platforms.v1.schema.json`

Other contracts whose stable data identity still contains `repobrief` are outside this
scope and remain unchanged.

## Consumer inventory

A repository-wide exact search after the change classifies every remaining former path,
schema ID and `kind` occurrence as follows:

- **Active enforcement:** the release builder and verifier share one exact retired-path
  denylist; repository hygiene separately guards source-tree absence. They reject
  reintroduction or archived presence; they do not consume either retired schema.
- **Negative and parity tests:** release packaging injects each former path and proves
  fail-closed rejection; verifier coverage rejects `repobrief.release_candidate`; naming
  coverage binds both former identities and successors to the terminal exit contract;
  a direct parity test binds the builder denylist to that contract.
- **Terminal current documentation:** `repoground-compatibility-exit.v1.json`, the contract
  matrix and this proof describe the unsupported state and current RepoGround successors.
- **Historical evidence:** the incremental-retrieval measurement, the former RepoBrief
  packaging proof and the generated task index remain byte-unchanged by this patch.

No production loader, schema resolver or release producer references either retired schema
as a supported input. The release builder archives every tracked Git-tree entry, so the old
schemas were still distributed before this change. The verifier rejected the former release
identity but still accepted canonical RepoGround archives containing the retired paths.

## Implemented boundary

- Both retired schema files are removed from the active contract directory.
- The deterministic release builder rejects either retired path before archive bytes are
  written.
- The verifier requires canonical raw archive member paths, imports the same denylist and
  rejects either retired path immediately after safe member enumeration, both without and
  with repository source binding.
- Repository hygiene requires both paths to stay absent.
- The contracts deletion guard has no broad environment bypass. A protected deletion
  requires an exact pull-request comment by a trusted human repository collaborator,
  bound to the PR number, merge-base, final PR head SHA and SHA-256 of the sorted
  deletion set. PR and associated push runs verify the same marker; missing, malformed,
  stale, ambiguous or unreadable authorization evidence fails closed.
- `repoground-compatibility-exit.v1.json` records former paths, schema IDs and kinds as
  `unsupported`, binds the existing RepoGround successor schemas, and forbids current-tree
  and release-archive presence.
- Builder and verifier share one denylist; a parity test prevents that denylist and the
  compatibility exit from drifting apart.
- The contract matrix distinguishes terminal historical identity from active schemas.
- Historical proof, measurement and task-index files are not rewritten.

## Validation

- `python3 -m pytest tests/test_repository_hygiene.py tests/test_naming_hard_cut.py merger/repoground/tests/test_release_packaging.py -q`
  - Result: `41 passed`.
- `python3 -m ruff check scripts/release/build_release_candidate.py scripts/release/verify_release_candidate.py merger/repoground/tests/test_release_packaging.py tests/test_repository_hygiene.py tests/test_naming_hard_cut.py`
  - Result: `All checks passed`.
- Full repository suite, durable task `2929a8340b4e43c0aee35d68`:
  - Result: `5102 passed, 12 skipped, 33 failed`.
  - Every failure is confined to `test_patch_evaluation_sidecar*` and reports the same
    host-level Bubblewrap failure: `Creating new namespace failed: Resource temporarily
    unavailable`.
  - No changed-path test failed.
  - Lifecycle receipt SHA-256:
    `deb0f53d97506688a614bb8f11ff7d6fb43fb0c612700ff7e5a53cc725a68a76`.
  - Terminalization SHA-256:
    `878474940d80da5c985ce72b8157b3cf78b1edc162553c69b78215c900da42f4`.
- `git diff --check` passes against the rebased `main` baseline.

## Non-claims

This proof does not establish:

- absence of unknown consumers outside the repository;
- that every remaining `repobrief` data contract is obsolete;
- permission to rewrite historical evidence;
- a green full suite while the host Bubblewrap namespace failure persists;
- official release status, product readiness or deployment authorization;
- correctness outside the validated release-contract and repository-hygiene scope.
