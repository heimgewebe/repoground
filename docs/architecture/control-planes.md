# RepoGround control planes (truth layers)

Status: accepted architecture boundary for the freigabefähigen slice of
`REPOGROUND-LEGACY-RECONCILIATION-V1-T005`.

## Layers

| Layer | Authority | Typical paths | Normative for agents? |
| --- | --- | --- | --- |
| Product architecture & boundaries | Repo docs on `main` | `docs/architecture/*`, `README.md`, `docs/GETTING_STARTED.md` | Yes |
| Live operator / initiative tasks | Bureau registry | `~/repos/bureau/registry/tasks/*` | Yes for task lifecycle |
| Repo-local historical task projection | Local board/index only | `docs/tasks/*` | **No** – projection / ratchet surface |
| Historical proofs | Evidence archive | `docs/proofs/*` | No – evidence, not current product contract |
| Diagnostics snapshots | Generated/run evidence | `docs/diagnostics/*`, canary outputs | No – run-bound diagnostics |
| CI checks | GitHub Actions + repository rulesets | `.github/workflows/*` | Required checks are defined in GitHub rulesets; tests verify behavior |

## Rules

1. **Do not treat proofs as live product truth.** Proofs bind a past revision and
   claim; they remain findable but are not the default reading surface for
   “how the system works now”.
2. **Do not treat `docs/tasks` as Bureau.** The local board/index may drive the
   planning-registration ratchet and human navigation of historical TASK-*
   rows. Canonical REPOGROUND-LEGACY-* / Bureau initiatives live in Bureau.
3. **CI checks follow actual behavior.** GitHub rulesets define required checks;
   workflows run substantive tests. Do not maintain a second SHA-256 registry of
   Git-tracked workflow files or block routine workflow edits on hash refresh.
4. **Entry links stay resolvable.** The entry-document link gate covers the
   fixed operator entry set (README, AGENTS, GETTING_STARTED, system map, …).

## Does not establish

- That proofs are worthless or may be mass-deleted without migration.
- That every diagnostic workflow must become required branch protection.
- That dual parity workflows are redundant copies of each other.
