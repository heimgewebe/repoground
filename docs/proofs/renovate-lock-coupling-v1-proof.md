# Renovate lock coupling v1 proof

Date: 2026-08-24

Bureau task: `REPOGROUND-LEGACY-RECONCILIATION-V1-FU-RENOVATE-LOCK-COUPLING-20260824`

## Regression evidence

RepoGround PR #1297 (`ruff` 0.16.4) demonstrates the gap on the real Renovate path:

- initial Renovate commit `04a6849467210396804d920f5c34f4d498ff1354` changed only `requirements-dev.txt`;
- follow-up commit `c1953321509c9c785ae7d220a5b02ed0a0416908` regenerated `requirements/repoground-dev.lock.txt` with the canonical lock generator;
- the PR was green and later merged, so existing CI detected lock drift only after the missing generated file had been repaired manually.

## Contract

`renovate.json` now binds dependency-upgrade branches to the self-hosted fleet command:

`bash /home/alex/.local/share/renovate-fleet/current/automation/renovate/repoground-lock-coupling.sh`

The fleet-side command is outside the Renovate checkout and is enabled only by an exact anchored `allowedCommands` regex in the self-hosted metarepo runtime configuration. It:

1. refuses any checkout whose `origin` is not `heimgewebe/repoground`;
2. no-ops unless the branch changed a root `requirements*.txt` file or a file under `requirements/`;
3. invokes only RepoGround's existing `scripts/release/compile_dependency_locks.sh` generator;
4. immediately invokes the same generator with `--check`;
5. propagates every generator or reproducibility failure to Renovate before its commit is created.

`postUpgradeTasks.fileFilters` include both root requirement inputs and `requirements/**`, so a single Renovate proposal can contain the updated input and regenerated hash lock together. `executionMode` is `branch`, so grouped dependency updates receive one canonical lock refresh for the completed branch state.

No merge, automerge, direct-main, or `--require-hashes` policy is expanded or weakened. The repository config cannot grant `allowedCommands`; that authority remains global-only in the self-hosted fleet runtime.

## Verification

Exact implementation checkout evidence on 2026-08-24:

- metarepo focused Renovate tests: `23 passed`;
- metarepo full `ALLOW_NET=1 just validate`: local validation successful and `299 passed`;
- RepoGround focused coupling/toolchain/release tests: `74 passed`;
- RepoGround Ruff: `ruff check --config ruff-ci.toml .` -> `All checks passed!`;
- canonical lock read-only verification: `bash scripts/release/compile_dependency_locks.sh --check` -> `All RepoGround dependency locks are reproducible.`

The first plain metarepo `just validate` attempt stopped before validation because the isolated worktree did not yet contain the pinned `yq` binary and network bootstrap was disabled. Re-running through the repository's supported `ALLOW_NET=1` bootstrap downloaded and checksum-verified the pinned toolchain, then completed the full validation successfully.
