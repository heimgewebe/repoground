# Status truth Bureau review follow-up v1

## Scope

This follow-up closes the two P2 review findings left on PR #1304 without making RepoGround a Bureau authority.

## Authority boundary

Bureau operational state remains outside Git in the Bureau StateStore. GitHub-hosted RepoGround CI therefore performs repository-structural status-truth validation only and explicitly records live Bureau reference resolution as `deferred_external` when no authoritative StateStore snapshot is available.

Strict Bureau reference validation remains fail-closed. A supplied snapshot is accepted only when it is:

- a versioned `bureau_status_truth_snapshot`;
- sourced from Bureau's StateStore task projection;
- revision-bound by `task_spec_root_sha256`;
- observed no more than 300 seconds before validation;
- not materially future-dated;
- complete for the Live Register candidate projection when candidate references are checked.

## Operator capture

`scripts/docmeta/capture_bureau_status_snapshot.py` consumes Bureau's existing read-only `status-projection --skip-github` and `live-list --kind candidate_task` surfaces. It does not read or mutate Bureau's SQLite schema directly and does not write Bureau state.

The generated snapshot can be passed to the existing strict checker with `--bureau-snapshot`.

## What this establishes

- GitHub CI no longer becomes unusable merely because a status-truth follow-up references Bureau.
- An old or unbound Bureau snapshot can no longer establish a verified reference.
- RepoGround remains a read-only consumer of Bureau facts.

## What this does not establish

- GitHub CI does not prove current Bureau task or candidate state.
- RepoGround does not gain task, queue, claim, dispatch, merge or completion authority.
- A snapshot older than the freshness window must be recaptured rather than trusted.
