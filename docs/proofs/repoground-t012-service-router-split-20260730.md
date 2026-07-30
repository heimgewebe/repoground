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
