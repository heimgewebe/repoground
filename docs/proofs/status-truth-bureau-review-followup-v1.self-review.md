# Self-review: status truth Bureau review follow-up v1

Reviewed branch: `fix/status-truth-bureau-review-followup-20260826`

## Finding 1 — required GitHub check had no Bureau snapshot

Accepted, but solved by separating authorities rather than copying local Bureau state into GitHub CI.

Bureau documents its operational StateStore outside Git. The GitHub-hosted `task-index` job therefore uses a repository-only wrapper that defers only `STATUS_TRUTH_BUREAU_UNAVAILABLE`. Every other status-truth finding remains blocking. The report records the deferred count and explicitly states that live Bureau state was not established.

## Finding 2 — stale snapshots were accepted indefinitely

Accepted and fixed fail-closed.

A strict snapshot now requires a versioned kind, authoritative StateStore task projection, `task_spec_root_sha256`, offset-aware observation time, a five-minute maximum age, future-clock rejection, and complete Live Register coverage for candidate references.

## Source integration

The capture helper consumes Bureau's existing read-only `status-projection --skip-github` and `live-list --kind candidate_task` commands. It does not inspect Bureau's SQLite schema directly and does not mutate Bureau.

## Risks checked

- GitHub CI cannot silently claim live Bureau verification: explicit `deferred_external` boundary.
- Stale or undated snapshots cannot verify a reference.
- Candidate snapshots cannot hide truncated Live Register coverage.
- Existing `no_task` status truth remains independent of Bureau availability.
- Existing strict `check_status_truth.py --bureau-snapshot` remains fail-closed.

## Validation available before hosted CI

The isolated new logic was exercised locally with seven focused tests covering fresh, stale, undated and future snapshots, candidate coverage, capture conversion and CI deferral behavior.

Hosted repository CI remains the authority for full-suite, lint, workflow and integration validation on the final PR head.
