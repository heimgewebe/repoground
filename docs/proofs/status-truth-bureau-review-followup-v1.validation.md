# Validation plan: status truth Bureau review follow-up v1

Final hosted validation for this change is delegated to the repository's existing required checks on the exact pull-request head.

Focused expectations:

1. `merger/repoground/tests/test_status_truth_followups.py` proves strict freshness and reference-state behavior.
2. `merger/repoground/tests/test_status_truth_bureau_review_regressions.py` proves StateStore snapshot conversion and repository-CI deferral semantics.
3. `.github/workflows/task-index.yml` exercises `check_status_truth_ci.py` on GitHub-hosted infrastructure without claiming Bureau live-state access.
4. Ruff and the full Python suite remain authoritative for style and regression coverage.

No merge should occur while a required final-head check is failing.
