# contracts-validate path filter reconciliation proof

## Scope

This proof records the narrow CI-control-plane fix for `TASK-CI-CONTRACTS-PATHS-001`.

## Problem

The `contracts-validate` workflow was registered as the contract validation gate, but its event path filters watched template paths that do not represent this repository's contract surface:

- `json/**`
- `proto/**`
- `fixtures/**`

The Lenskit contract surface is under `merger/lenskit/contracts/**`, with contract documentation under `docs/contracts/**` and contract/schema regression tests under `merger/lenskit/tests/`.

## Change

The workflow now triggers for:

- `merger/lenskit/contracts/**`
- `docs/contracts/**`
- `merger/lenskit/tests/test_*contract*.py`
- `merger/lenskit/tests/test_*schema*.py`
- `merger/lenskit/tests/test_role_completeness.py`
- `.github/workflows/**`

The deletion guard now protects contract surfaces instead of the non-existent `json/` and `proto/` roots:

- `merger/lenskit/contracts/`
- `docs/contracts/`

## Non-claims

This proof does not establish contract correctness, reusable-workflow correctness, schema completeness, fixture completeness, or release readiness.

It only records that the workflow trigger and deletion guard now target the repository's actual contract paths.
