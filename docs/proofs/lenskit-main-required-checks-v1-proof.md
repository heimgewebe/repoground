# Lenskit main required checks v1 proof

Status: implemented and structurally verified on 2026-07-10. Positive implementation-PR evidence is recorded before merge.

## Scope

A separate repository ruleset named `main-required-checks` protects only `refs/heads/main`.
It does not replace the existing `zweigschutz` ruleset, which continues to protect deletion and non-fast-forward updates.

The new ruleset has GitHub ruleset id `18784275`, has no bypass actors, and requires these checks from their observed GitHub Apps:

| Required context | Integration id | Evidence guarded |
|---|---:|---|
| `Lenskit CodeQL policy (python)` | `15368` | The repository CodeQL workflow, including suppression-inventory validation and the post-analysis raw-SARIF clean gate |
| `CodeQL` | `57789` | GitHub Advanced Security's pull-request CodeQL result |
| `pytest-full` | `15368` | The full Python test suite excluding explicitly non-blocking markers |
| `release-candidate` | `15368` | Hash-locked release contract, duplicate deterministic candidate build and source-bound verification |
| `ruff` | `15368` | The pinned repository-wide Ruff ratchet |
| `webui-js-tests` | `15368` | The Web UI JavaScript test suite |

`strict_required_status_checks_policy` is enabled. A pull request whose branch is behind `main` must therefore be brought up to date and revalidated before merge. This trades extra CI reruns for evidence against the current base.

The custom workflow job has the unique context `Lenskit CodeQL policy (python)` so GitHub's separate default `Analyze (python)` check cannot ambiguously satisfy this policy.

The machine-readable desired state is `config/github-main-required-checks.v1.json`. The read-only, network-free validator is `scripts/ci/check_github_main_ruleset.py`. It fails unless the observed API response identifies `source=heimgewebe/lenskit` and `source_type=Repository`; a same-shaped ruleset from another repository is therefore rejected.

Operator check:

```bash
gh api repos/heimgewebe/lenskit/rulesets/18784275 \
  | python3 scripts/ci/check_github_main_ruleset.py
```

A successful validator result establishes only structural agreement between the observed API response and the checked-in policy. It does not establish that GitHub will enforce the rule at merge time.

## Staged activation proof

The ruleset was first created with `enforcement=disabled`.
The validator failed with exactly one finding:

```text
enforcement mismatch: expected 'active', found 'disabled'
```

After the payload was checked, the same ruleset was updated to `enforcement=active`, read back from the GitHub API, and validated with `status=pass` and no findings.

## Negative enforcement proof

Disposable pull request [#955](https://github.com/heimgewebe/lenskit/pull/955) used head commit `9a777407c43a002a7a528cf98bdf69ef2ec322d7` and intentionally introduced one Ruff `F401` violation.

Observed on 2026-07-10:

- GitHub computed the branch as `mergeable=MERGEABLE`; there was no content conflict.
- Required check `ruff` completed with `FAILURE`.
- GitHub reported `mergeStateStatus=BLOCKED`.
- The pull request was closed without merge.
- The disposable remote branch and worktree were removed.

This demonstrates that a content-mergeable pull request is blocked when a configured required check fails. It does not prove that every possible bypass, permission path, GitHub outage, or future rule edit is covered.

## Positive implementation proof

Implementation pull request [#956](https://github.com/heimgewebe/lenskit/pull/956) ran head `d9b1b0478e0a7e8cc3fcbff2637d6a3a4da9f56f` against base `dcce9ae48606aad1ea7684a1205fe6c844cb4faf`.

GitHub reported `mergeable=MERGEABLE` and `mergeStateStatus=CLEAN` after all configured required checks completed successfully:

- `Lenskit CodeQL policy (python)`: `SUCCESS`;
- `CodeQL`: `SUCCESS`;
- `pytest-full`: `SUCCESS`;
- `ruff`: `SUCCESS`;
- `webui-js-tests`: `SUCCESS`.

The uniquely named Lenskit CodeQL policy job and GitHub's separate default `Analyze (python)` job were both visible, demonstrating that the required context no longer relies on the ambiguous shared name.

The final documentation-only proof commit must repeat the required checks before merge; the merge gate, not this paragraph, remains authoritative for the final head.


## Release-candidate extension

After PR [#978](https://github.com/heimgewebe/lenskit/pull/978) merged as
`50de5cd4c95f473fff5d6420d0e8c99ba92771bf`, the Main job
`release-candidate` completed successfully in run `29153314855`, job
`86546260543`. Ruleset `18784275` was then updated to require the same context
from GitHub Actions integration `15368`. API read-back validation against the
checked-in desired state passed with no findings.

The source workflow `.github/workflows/test-suite.yml` has unfiltered
`pull_request` and `push` triggers for `main`, so the context is produced for
every relevant PR rather than only for release-file changes. The repository
also carries `.github/grabowski-required-checks.json`, allowing the local
review gate to derive the same required check names from the target branch.

## Rollback

If an incorrect context or GitHub incident deadlocks merges:

1. set ruleset `18784275` to `enforcement=disabled`;
2. diagnose the mismatched context or integration id;
3. update the checked-in desired state and tests through a reviewed pull request;
4. reactivate only after API read-back validation and a fresh negative/positive proof.

Deleting this separate ruleset is a last-resort rollback. It does not modify the existing deletion/non-fast-forward `zweigschutz` ruleset.

## Non-claims

This proof does not establish:

- test sufficiency;
- absence of security findings;
- CodeQL or Ruff correctness;
- runtime correctness;
- review completeness;
- permanent GitHub availability;
- merge readiness of any unrelated pull request.
