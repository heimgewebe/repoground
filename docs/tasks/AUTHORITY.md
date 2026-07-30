# docs/tasks authority boundary

**Bureau is the canonical task lifecycle for RepoGround initiatives** such as
`REPOGROUND-LEGACY-RECONCILIATION-V1-*`. Those tasks are owned in the Bureau
registry (`registry/tasks/*.json` in the Bureau repository), not in this folder.

## What lives here

| Path | Role |
| --- | --- |
| `index.json` / `board.md` | Historical / human TASK-* projection and planning-registration ratchet input |
| `planning-registration-baseline.json` | Baseline for the planning-registration CI ratchet |

## What this is not

- Not a second lifecycle truth that can override Bureau.
- Not a claim surface for merge authority, deployment, or initiative closeout.
- Not required reading for answering “what is the next REPOGROUND-LEGACY task?”
  — use Bureau `what-now` / task registry instead.

When Bureau and `docs/tasks` disagree on an initiative task, **Bureau wins**.
Repo-local TASK-* rows remain useful for legacy planning hygiene only.
