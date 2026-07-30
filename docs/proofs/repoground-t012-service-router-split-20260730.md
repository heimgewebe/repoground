# T012: Service app router split closeout

Bureau task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T012`

## Contract and revision binding

This proof closes the remaining acceptance gaps after PR #1124.  It does not
change service or API semantics.

| Role | Revision | Tree | Meaning |
| --- | --- | --- | --- |
| historical before | `b7a807dbe22cff864b5407c8b4ba42f6ae97f1e2` | `f3c1fee19daa12df3dee8889edb45f24e5339023` | direct parent of the T012 squash merge; monolithic `service/app.py` |
| measured T012 after | `20b9fa60add19370a8f0e1620c59a640ed135139` | `2b61f3c35930cf98fbf71306bacb27d7410289de` | exact PR #1124 squash merge, `refactor(service): split app.py into domain routers (T012)` |
| test and closeout basis | `04f83dcce6cb40aa572ca155ca15eb88ae2202d4` | `421697968fa3cdbf1433835bd6c32a8b24c09367` | clean `origin/main` input to this closeout; not a performance endpoint |

`git merge-base --is-ancestor` confirms that the before revision is an
ancestor of the exact T012 merge.  The two performance revisions are
materialized by `git archive`, not by reusing another worktree.  Tests,
runtime/security readback, and closeout review remain bound to `04f83dcc`.
Performance values are attributed only to the exact
`b7a807db` → `20b9fa60` T012 change, not to `04f83dcc` or any later change.

The required RepoGround `pr_review` preflight passed against the exact
`04f83dcc` publication:

- stem: `heimgewebe__repoground__main-max-260730-0902`
- manifest SHA-256:
  `c5f3b0394c1c2cd5d8569ea82ef0a2c12cbbb00f9bad5db772133224eb02b7ab`
- bundle commit, generator commit, clean live source checkout, and this
  worktree input all resolved to `04f83dcc`
- `canonical_md`, `agent_reading_pack`, `citation_map_jsonl`,
  `post_emit_health`, `bundle_surface_validation`, `claim_evidence_map_json`,
  and `snapshot_plan_json` were available; post-emit and surface status were
  `pass`

This context pass is navigation/freshness evidence only.  It does not establish
runtime correctness, test sufficiency, review completeness, or merge readiness.

## Landed split

`merger/repoground/service/app.py` was reduced from about 2,394 lines to about
886 by extracting domain routers:

- `health_router.py` — `/api/health`, `/api/version`
- `query_router.py` — federation/query endpoints
- `job_router.py` — job lifecycle and SSE
- `artifact_router.py` — artifact lookup/download
- `atlas_router.py` — atlas creation and export
- `router_support.py` — live attribute/callable compatibility hooks

`app.py` remains the composition surface for the FastAPI application,
middleware, service initialization, the remaining control-plane endpoints,
and the UI.

The original review hardening remains present:

- shared `path_helpers.py` for request-path and filename checks
- CodeQL suppression inventory for moved path-injection boundaries
- updated C901 baseline paths
- live app-module resolution for version, GC, and SSE values
- no private cross-router helper coupling

## Isolated service readback

`test_service_router_closeout.py::test_isolated_service_readback_covers_health_auth_jobs_and_query`
creates a temporary Hub, merges directory, repository, JobStore, and SQLite
retrieval index.  The runner submission hook is replaced with a no-op so the
test exercises the API lifecycle without scanning a real checkout or starting
background work.

The readback proves:

1. `GET /api/health` returns HTTP 200, `status=ok`,
   `auth_enabled=true`, and zero active jobs at initialization.
2. Protected requests with no token or a wrong bearer token return HTTP 401;
   this includes both the job surface and `/api/query`.
3. An authenticated job traverses API-visible
   `POST /api/jobs` → `GET /api/jobs/{id}` → filtered `GET /api/jobs` →
   `POST /api/jobs/{id}/cancel` → `GET /api/jobs/{id}`, ending in the expected
   `canceling` state for a runner that has not acknowledged cancellation.
4. An authenticated `POST /api/query` reads a real canonical
   `*.index.sqlite` and returns the expected chunk.
5. Size, `st_mtime_ns`, and SHA-256 of that SQLite file are identical before
   and after the query.  This corroborates the production `read_only=True`
   query path and immutable SQLite open mode.

Boundary: this is a hermetic in-process ASGI/FastAPI `TestClient` readback.  It
does not include a TCP socket, Uvicorn, a reverse proxy, TLS, or a real job
runner.

The fixture and the parametrized sensitive-filesystem test preserve all global
fields assigned by `init_service` (`hub`, `merges_dir`, `job_store`,
`query_artifact_store`, `runner`, `log_provider`, and `host`) through one
MonkeyPatch helper.  The pre-existing security and middleware restoration is
kept in the same helper.  A separate `MonkeyPatch.context()` regression test
checks that every saved reference is restored by identity after the context,
preventing order-dependent state leakage into later service tests.

## API parity

A bounded fresh Python interpreter ratchets all 33 API method/path pairs,
the owning endpoint module, each route's `verify_token` binding, and the
normalized OpenAPI fingerprint.  The subprocess is rooted at the exact
repository, has a 30-second timeout, emits canonical JSON, and fails closed on
nonzero exit, timeout, malformed JSON, or malformed shape.  This prevents
previous tests that mutate the process-global FastAPI app from producing a
false failure or false pass.  A regression test deliberately reduces the
in-process app to two routes and confirms that the fresh snapshot still returns
the complete 33-route contract.  The benchmark independently imports the
archived before and after revisions and compares:

| Observation | Before | After | Result |
| --- | --- | --- | --- |
| API method/path pairs | 33 | 33 | identical |
| OpenAPI paths | 33 | 33 | identical |
| OpenAPI component schemas | 18 | 18 | identical |
| normalized route-inventory SHA-256 | `01028deb2057dc0d267d18d13b4040f7241897a6c32d1a1870b1db570bc4dc4a` | same | pass |
| canonical OpenAPI SHA-256 | `9d645279574fc2c7d086f220fd1287595513b9a77d9700430807d1bd3d103c2e` | same | pass |

The service build/version label is fixed to `t012-benchmark` on both sides so
the comparison measures API shape rather than the expected revision-label
difference.  OpenAPI and route hashes were stable across all nine fresh
processes for each revision.

## Central security boundaries

The closeout test and existing focused tests explicitly cover these boundaries:

| Boundary | Evidence |
| --- | --- |
| Authentication stays attached after router extraction | `test_all_non_health_api_routes_keep_auth_dependency` checks the fresh-interpreter snapshot for `verify_token` on all 31 protected API method/path pairs; only the historically public Health/Version pair is exempt |
| Auth rejects missing/invalid credentials | isolated readback returns 401; `test_service_auth_hardening.py` also covers constant-time comparison and bearer/query-token compatibility |
| Broad filesystem access is conjunctive | `test_sensitive_filesystem_access_requires_loopback_and_auth` proves root access is refused for loopback without a token and non-loopback with a token, and enabled only for loopback plus token |
| Request/file paths remain confined | `test_code_scanning_security.py`, `test_service_artifact_security.py`, and `test_service_hardening.py` cover traversal, symlink escape, allowlist, and safe artifact-GC paths |
| Query paths stay bundle/artifact-root bound | `test_api_query.py` covers invalid filenames, missing artifacts, graph paths, and redacted runtime failures; the closeout readback verifies non-mutation of the SQLite index |
| Restart remains local, authenticated, allowlisted, and idle-only | `test_service_admin_restart.py` covers disabled/invalid/non-loopback/running-job failure modes |
| Query-token leakage is bounded | `test_service_runtime_security.py` proves Uvicorn raw access logging remains disabled |

No defect was found in the landed router implementation, so this closeout does
not modify `merger/repoground/service/`.

## Reproducible performance measurement

Machine-readable evidence:
`docs/proofs/repoground-t012-service-router-split-20260730.measurement.json`.

Command:

```bash
python3 scripts/benchmarks/measure_service_router_split.py \
  --before-revision b7a807dbe22cff864b5407c8b4ba42f6ae97f1e2 \
  --after-revision 20b9fa60add19370a8f0e1620c59a640ed135139 \
  --rounds 9 \
  --warmup-requests 5 \
  --request-samples 30 \
  --output docs/proofs/repoground-t012-service-router-split-20260730.measurement.json
```

Method:

- exact revisions are exported to separate temporary directories
- nine fresh Python processes are used per revision
- order alternates before/after, then after/before, to reduce systematic
  shared-host drift
- import/start is `perf_counter_ns` around
  `import merger.repoground.service.app`; FastAPI app construction occurs
  during that import
- request latency is 30 measured in-process `GET /api/health` calls per round
  after five warmups, for 270 measured requests per revision
- current RSS comes from `/proc/self/statm`; peak RSS comes from
  `/proc/self/status` `VmHWM`; values are KiB
- `PYTHONHASHSEED=0`, `REPOGROUND_VERSION=t012-benchmark`,
  `REPOGROUND_BUILD_ID=t012-benchmark`, `TZ=UTC`, and `LC_ALL=C.UTF-8`
  are fixed on both sides

Environment:

- CPython 3.10.12, Linux 7.0.11 x86-64, glibc 2.35
- AMD Ryzen 9 5900XT, 32 logical CPUs
- FastAPI 0.125.0, Starlette 0.50.0, Pydantic 2.12.5, HTTPX 0.28.1
- load averages at start/end and all raw timing/memory samples are retained in
  the measurement JSON

Results for the exact T012 parent/squash-merge pair:

| Metric | Before `b7a807db` | After `20b9fa60` | Observed change |
| --- | ---: | ---: | ---: |
| import/app construction median | 268.343918 ms | 286.854323 ms | +6.898% |
| import/app construction min–max | 264.562442–325.263352 ms | 283.867342–2,304.573017 ms | observational; one after-process import outlier is retained |
| Health request p50 | 0.855495 ms | 0.856675 ms | +0.138% |
| Health request p95 | 1.026847 ms | 0.984106 ms | after is slightly lower |
| RSS after import median | 50,216 KiB | 50,988 KiB | +772 KiB / +1.537% |
| RSS import delta median | 30,360 KiB | 31,120 KiB | +760 KiB |
| RSS after requests median | 56,188 KiB | 56,840 KiB | +652 KiB |

These are bounded before/after observations, not an improvement claim or
a performance verdict.  The task contract defines no threshold, so the
benchmark is evidence rather than a pass/fail gate.  `TestClient` measures
in-process ASGI dispatch only: it does not measure TCP or Uvicorn, nor proxy or
TLS costs.  Small differences do not establish statistical significance or an
SLO.  Absolute timing is not cross-host comparable; the shared host was not
quiesced, OS page cache was not flushed, and nine rounds do not establish
production workload behavior, steady-state memory, or absence of regressions
on other endpoints.  No value in this table is attributed to `04f83dcc` or
later changes.

## Validation

Fresh-process closeout ratchet:

```text
python3 -m pytest -q -p no:cacheprovider \
  merger/repoground/tests/test_service_router_closeout.py
8 passed
```

Adjacent runtime/security set:

```text
python3 -m pytest -q -p no:cacheprovider \
  merger/repoground/tests/test_service_health.py \
  merger/repoground/tests/test_service_auth_hardening.py \
  merger/repoground/tests/test_service_artifact_security.py \
  merger/repoground/tests/test_service_hardening.py \
  merger/repoground/tests/test_service_runtime_security.py \
  merger/repoground/tests/test_service_admin_restart.py \
  merger/repoground/tests/test_api_query.py \
  merger/repoground/tests/test_code_scanning_security.py \
  merger/repoground/tests/test_atlas_system.py
94 passed
```

Exact GitHub `pytest-full` selection, repeated locally after the
fresh-interpreter correction:

```text
python3 -m pytest -q -m 'not browser and not doc_freshness_live'
5208 passed, 12 skipped, 13 deselected
```

This full-order run is the regression proof for the original PR #1130 failure:
earlier tests may mutate the process-global FastAPI app, while the closeout
ratchet now reads the canonical service contract from a fresh interpreter.

Relevant CI/readback guards:

```text
python3 scripts/ci/check_codeql_suppressions.py
pass: 30 suppressions, all inventoried

python3 scripts/ci/check_graph_maintainability.py --root . --format json
pass: 0 findings; 189/189 baseline findings, max complexity 138

python3 scripts/ci/check_module_reachability.py --root . --format json
pass: 232 modules, 0 findings, 0 unproven

python3 scripts/ci/check_workflow_control_plane.py --root . --format json
pass: 21 workflows, 0 errors

python3 scripts/ci/check_entry_doc_links.py --root . --format json
pass: 10 entry documents, 0 broken links

python3 tools/parity_guard.py
pass

ruff check --config ruff-ci.toml .
pass

git diff --check
pass
```

## Closeout boundaries

- No service production code or API semantics are changed by this closeout.
- No Bureau file, Bureau registry state, foreign worktree, deployment, product
  runtime, or service production code is mutated by this PR.
- The committed measurement is host- and dependency-bound and is not a
  performance SLO.
- Performance observations compare only the exact T012 parent and squash
  merge; `04f83dcc` remains the test/closeout basis and is not assigned those
  values.
- The ASGI readback is not a live Uvicorn/TCP deployment test.
- T012 does not close parent T004; T010/T011/T013/T014 remain separate tasks.

With the listed checks green and the final Git readback clean, this evidence
supports merging the T012 closeout.
