# T012: Service app router split

Bureau task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T012`

## Change

`merger/repoground/service/app.py` was reduced from ~2394 lines to ~886 by
extracting domain routers:

- `health_router.py` — `/api/health`, `/api/version` (live app-module attributes)
- `query_router.py` — federation/query endpoints
- `job_router.py` — job lifecycle and SSE
- `artifact_router.py` — artifact lookup/download
- `atlas_router.py` — atlas creation and export
- `router_support.py` — AttributeProxy / dynamic callables for test hooks

`app.py` remains the composition surface (FastAPI app, middleware, init, UI).

## Validation

- `pytest merger/repoground/tests/ -k service`: 218 passed, 1 skipped

## Boundaries

- Foreign dirty worktree `repoground-t004-chatgpt-20260729` was used only as a
  read-only reference and was not modified.
- Does not close parent T004; T010/T011/T013/T014 remain separate.

## Review hardening (post-PR review)

Addressed review and CI failures on PR #1124:

- shared `path_helpers.py` for `_resolve_request_path` / `_is_safe_filename` used by
  `api_prescan` and query routers (no private cross-router coupling)
- CodeQL suppression inventory updated for moved path-injection sites
- C901 baseline paths updated for moved atlas/job handlers; query helpers that fell
  under threshold were allowed to resolve
- job GC/SSE knobs resolve live from the app module
- dead runtime-metadata comment banner removed from `app.py`
- bare `raise` for rethrown HTTPException in atlas router

Local validation after hardening:

- `scripts/ci/check_codeql_suppressions.py`: pass
- `scripts/ci/check_graph_maintainability.py`: pass
- focused pytest (`service or api_query or codeql`): 268 passed, 1 skipped
