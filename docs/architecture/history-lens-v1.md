# RepoGround History Lens v1

Status: optional derived navigation
Initiative: `REPOBRIEF-FRONTDOOR-GROUNDING-V1`
Task: `RBGV-V1-T009`

History Lens is a derived navigation and diagnostic surface for explicit history records such as commit, file, and pull-request provenance hints.

It is not canonical content truth. Canonical repository content remains the selected RepoGround snapshot's canonical source. Current work still requires live GitHub, CI, PR and working-tree checks.

## Profiles and export policy

History metadata is governed by an explicit profile:

- `disabled`: no history metadata included;
- `summary`: file churn summary only;
- `full`: provenance chains included.

Author metadata is excluded by default and may only be included when explicitly requested by the caller/profile.

## Forbidden verdicts

History Lens must not emit or imply:

- person blame;
- ownership verdicts;
- correctness verdicts;
- completeness verdicts;
- merge-readiness verdicts.

## Non-claims

A History Lens output does not establish canonical content truth, repository understanding, live GitHub state, CI state, PR state, correctness, completeness, ownership, person blame, merge readiness or security correctness.
