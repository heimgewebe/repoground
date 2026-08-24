# Renovate lock coupling v1 proof

Date: 2026-08-24

Bureau task: `REPOGROUND-LEGACY-RECONCILIATION-V1-FU-RENOVATE-LOCK-COUPLING-20260824`

## Regression evidence

RepoGround PR #1297 (`ruff` 0.16.4) demonstrates the gap on the real Renovate path:

- initial Renovate commit `04a6849467210396804d920f5c34f4d498ff1354` changed only `requirements-dev.txt`;
- follow-up commit `c1953321509c9c785ae7d220a5b02ed0a0416908` regenerated `requirements/repoground-dev.lock.txt` with the canonical lock generator;
- the PR was green and later merged, so existing CI detected lock drift only after the missing generated file had been repaired manually.

## Contract

`renovate.json` binds standard dependency-upgrade branches to the self-hosted fleet command:

`bash /home/alex/.local/share/renovate-fleet/current/automation/renovate/repoground-lock-coupling.sh`

The fleet-side command is outside the Renovate checkout and is enabled only by an exact anchored `allowedCommands` regex in the self-hosted metarepo runtime configuration. The installed wrapper:

1. refuses any checkout whose `origin` is not `heimgewebe/repoground`;
2. no-ops unless the branch changed a root `requirements*.txt` file or a file under `requirements/`;
3. invokes only RepoGround's existing `scripts/release/compile_dependency_locks.sh` standard generator;
4. immediately invokes the same generator with `--check`;
5. propagates every generator or reproducibility failure to Renovate before its commit is created.

`postUpgradeTasks.fileFilters` allows the normal requirement inputs and generated files to be included in Renovate's final branch commit. `executionMode` is `branch`, so grouped standard dependency updates receive one canonical lock refresh for the completed branch state.

## Multi-lock boundary

Three path classes are intentionally excluded from generic Renovate updates:

- `merger/repoground/requirements.txt` because it feeds both the standard runtime/dev locks and the semantic target;
- `merger/repoground/requirements-semantic.txt` because it records semantic compatibility-root intent;
- `requirements/repoground-semantic-*` because the target-specific input, constraints and hash lock are one semantic reproducibility contract.

The semantic contract is generated separately by `scripts/release/compile_semantic_lock.sh` and is additionally hash-bound by `docs/release/repoground-semantic-platforms.v1.json`. Updating any shared or semantic dependency safely therefore requires coordinated regeneration of every affected standard and semantic artifact. Generic Renovate is disabled for those files until such an atomic multi-lock operation exists.

This fail-closed boundary is deliberately smaller than extending the fleet wrapper: standard dependencies remain automated, while shared/semantic dependencies cannot produce a partially refreshed lock set.

No merge, automerge, direct-main, or `--require-hashes` policy is expanded or weakened. The repository config cannot grant `allowedCommands`; that authority remains global-only in the self-hosted fleet runtime.

## Verification

Exact review-worktree evidence on 2026-08-24:

- RepoGround focused coupling + semantic extension tests: `11 passed`;
- modified RepoGround test Ruff check: `All checks passed!`;
- canonical standard lock read-only verification: `scripts/release/compile_dependency_locks.sh --check` -> `All RepoGround dependency locks are reproducible.`;
- target-specific semantic lock read-only verification: `scripts/release/compile_semantic_lock.sh --check` -> `status=pass`, `operation=checked`, `package_count=58`, target `cpython-312-linux-x86_64`;
- installed Renovate fleet release readback: `/home/alex/.local/share/renovate-fleet/current` resolves to metarepo commit `94fafdb533a100d3bc4bbb2560a6e8dd99ee5869`;
- installed runtime config contains the exact anchored allowlist entry for `repoground-lock-coupling.sh`.

The original metarepo implementation had already validated the standard wrapper path before this repository-side review hardening. The review change does not rely on the unmerged nested-input wrapper experiment: unsupported multi-lock inputs are excluded in RepoGround itself, so the currently installed `94fafdb...` runtime remains sufficient for the enabled standard path.
