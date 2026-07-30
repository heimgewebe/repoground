# T005 freigabefähiger Slice: Docs/CI control planes

Bureau task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T005`

Base revision: post-merge `fe1e82dd` (includes T011 residual #1125 and T012 #1124).

## Scope of this slice

This is a **bounded control-plane slice**, not full T005 closeout:

| Acceptance | This slice |
| --- | --- |
| task-truth | `docs/tasks/AUTHORITY.md`, board header, `index.json` `_authority` declare Bureau as canonical lifecycle for REPOGROUND-LEGACY-* |
| ci-value | All 21 workflows classified in `config/workflow-control-plane.v1.json`; fail-closed inventory check in `lint` |
| freshness | Entry-document link gate over fixed operator entry set; 0 broken links observed |
| truth-layers | `docs/architecture/control-planes.md` separates architecture, Bureau, proofs, diagnostics, CI |
| context-budget | Documented; default retrieval re-weighting of entire `docs/proofs/**` deferred |

## Workflow classes (counts)

See inventory `counts_by_class`. No workflow is classified as `historical_ballast` in this revision; dual parity surfaces remain `fast_feedback` with distinct roles.

## Validation

```bash
python scripts/ci/check_workflow_control_plane.py --root . --format json
python scripts/ci/check_entry_doc_links.py --root . --format json
pytest scripts/ci/tests/test_workflow_control_plane.py -q
```

## Does not establish

- Full archival migration of all historical proofs
- Automatic removal of any workflow
- That `docs/tasks` TASK-* rows are deleted
- Parent T004 closeout

## Follow-ups

- Optional retrieval profile exclusion weights for `docs/proofs/**` and `docs/diagnostics/**`
- Branch-protection alignment audit against `required_protection` class
- Bureau registry state sync for T011/T012 after landed code
