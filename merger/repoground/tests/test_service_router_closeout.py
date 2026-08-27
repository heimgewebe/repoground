from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from merger.repoground.adapters.security import get_security_config
from merger.repoground.retrieval import index_db
from merger.repoground.service import app as service_app
from merger.repoground.service.auth import verify_token
from merger.repoground.service.models import Artifact, JobRequest


PRE_SPLIT_REVISION = "b7a807dbe22cff864b5407c8b4ba42f6ae97f1e2"
PRE_SPLIT_OPENAPI_SHA256 = (
    "9d645279574fc2c7d086f220fd1287595513b9a77d9700430807d1bd3d103c2e"
)
SERVICE_STATE_FIELDS = (
    "hub",
    "merges_dir",
    "job_store",
    "query_artifact_store",
    "runner",
    "log_provider",
    "host",
)
REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_TIMEOUT_SECONDS = 30

EXPECTED_API_METHOD_PATHS = {
    ("GET", "/api/admin/capabilities"),
    ("POST", "/api/admin/restart"),
    ("POST", "/api/artifact_lookup"),
    ("GET", "/api/artifacts"),
    ("GET", "/api/artifacts/latest"),
    ("GET", "/api/artifacts/{id}"),
    ("GET", "/api/artifacts/{id}/download"),
    ("GET", "/api/atlas"),
    ("POST", "/api/atlas"),
    ("GET", "/api/atlas/latest"),
    ("GET", "/api/atlas/{id}/download"),
    ("POST", "/api/context_lookup"),
    ("GET", "/api/diagnostics"),
    ("POST", "/api/diagnostics/rebuild"),
    ("POST", "/api/export/webmaschine"),
    ("POST", "/api/extras/refresh_all"),
    ("POST", "/api/federation/query"),
    ("GET", "/api/fs"),
    ("GET", "/api/fs/list"),
    ("GET", "/api/fs/roots"),
    ("GET", "/api/health"),
    ("GET", "/api/jobs"),
    ("POST", "/api/jobs"),
    ("GET", "/api/jobs/{job_id}"),
    ("POST", "/api/jobs/{job_id}/cancel"),
    ("GET", "/api/jobs/{job_id}/logs"),
    ("POST", "/api/prescan"),
    ("POST", "/api/query"),
    ("GET", "/api/repos"),
    ("POST", "/api/sources/refresh"),
    ("POST", "/api/sync/metarepo"),
    ("POST", "/api/trace_lookup"),
    ("GET", "/api/version"),
}

EXTRACTED_ROUTE_MODULES = {
    ("GET", "/api/health"): "merger.repoground.service.health_router",
    ("GET", "/api/version"): "merger.repoground.service.health_router",
    ("POST", "/api/query"): "merger.repoground.service.query_router",
    ("POST", "/api/federation/query"): "merger.repoground.service.query_router",
    ("GET", "/api/jobs"): "merger.repoground.service.job_router",
    ("POST", "/api/jobs"): "merger.repoground.service.job_router",
    ("GET", "/api/jobs/{job_id}"): "merger.repoground.service.job_router",
    ("POST", "/api/jobs/{job_id}/cancel"): (
        "merger.repoground.service.job_router"
    ),
    ("GET", "/api/jobs/{job_id}/logs"): "merger.repoground.service.job_router",
    ("GET", "/api/artifacts"): "merger.repoground.service.artifact_router",
    ("GET", "/api/artifacts/latest"): (
        "merger.repoground.service.artifact_router"
    ),
    ("GET", "/api/artifacts/{id}"): (
        "merger.repoground.service.artifact_router"
    ),
    ("GET", "/api/artifacts/{id}/download"): (
        "merger.repoground.service.artifact_router"
    ),
    ("POST", "/api/artifact_lookup"): (
        "merger.repoground.service.artifact_router"
    ),
    ("POST", "/api/trace_lookup"): "merger.repoground.service.artifact_router",
    ("POST", "/api/context_lookup"): (
        "merger.repoground.service.artifact_router"
    ),
    ("GET", "/api/atlas"): "merger.repoground.service.atlas_router",
    ("POST", "/api/atlas"): "merger.repoground.service.atlas_router",
    ("GET", "/api/atlas/latest"): "merger.repoground.service.atlas_router",
    ("GET", "/api/atlas/{id}/download"): (
        "merger.repoground.service.atlas_router"
    ),
    ("POST", "/api/sync/metarepo"): (
        "merger.repoground.service.atlas_router"
    ),
    ("POST", "/api/export/webmaschine"): (
        "merger.repoground.service.atlas_router"
    ),
}


def _api_routes():
    api_routes = []
    pending = list(service_app.app.routes)
    seen_collections: set[int] = set()
    while pending:
        route = pending.pop(0)
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if isinstance(path, str) and path.startswith("/api") and methods:
            api_routes.append(route)

        nested_collections = [getattr(route, "routes", None)]
        original_router = getattr(route, "original_router", None)
        nested_collections.append(getattr(original_router, "routes", None))
        for nested_routes in nested_collections:
            if nested_routes is None:
                continue
            collection_id = id(nested_routes)
            if collection_id in seen_collections:
                continue
            seen_collections.add(collection_id)
            pending.extend(nested_routes)
    return api_routes


def _method_paths(route) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for method in getattr(route, "methods", ())
        if method not in {"HEAD", "OPTIONS"}
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_openapi(openapi: dict[str, object]) -> dict[str, object]:
    normalized = copy.deepcopy(openapi)
    info = normalized.get("info")
    if isinstance(info, dict):
        info["version"] = "t012-benchmark"
    components = normalized.get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    validation_error = (
        schemas.get("ValidationError") if isinstance(schemas, dict) else None
    )
    properties = (
        validation_error.get("properties")
        if isinstance(validation_error, dict)
        else None
    )
    if isinstance(properties, dict):
        properties.pop("ctx", None)
        properties.pop("input", None)
    # archive_scope is an intentional additive API extension covered separately.
    for schema_name in ("QueryRequest", "FederationQueryRequest"):
        schema = schemas.get(schema_name) if isinstance(schemas, dict) else None
        schema_properties = schema.get("properties") if isinstance(schema, dict) else None
        if isinstance(schema_properties, dict):
            schema_properties.pop("archive_scope", None)
    return normalized


def _service_contract_snapshot() -> dict[str, object]:
    routes: list[dict[str, object]] = []
    for route in _api_routes():
        dependencies = {
            dependency.call
            for dependency in getattr(route, "dependant").dependencies
        }
        for method, path in _method_paths(route):
            routes.append(
                {
                    "auth_required": verify_token in dependencies,
                    "endpoint_module": route.endpoint.__module__,
                    "method": method,
                    "path": path,
                }
            )

    openapi = _normalized_openapi(service_app.app.openapi())
    canonical = json.dumps(
        openapi,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    app_path = Path(service_app.__file__).resolve()
    return {
        "source_app": str(app_path.relative_to(REPO_ROOT)),
        "openapi_sha256": hashlib.sha256(canonical).hexdigest(),
        "routes": sorted(
            routes,
            key=lambda row: (str(row["method"]), str(row["path"])),
        ),
    }


def _fresh_service_contract_snapshot() -> dict[str, object]:
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(REPO_ROOT), existing_pythonpath) if part
    )
    env.update(
        {
            "PYTHONHASHSEED": "0",
            "REPOGROUND_BUILD_ID": "t012-benchmark",
            "REPOGROUND_VERSION": "t012-benchmark",
        }
    )
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "merger.repoground.tests.test_service_router_closeout",
                "--service-snapshot",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=SNAPSHOT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            f"fresh service snapshot exceeded {SNAPSHOT_TIMEOUT_SECONDS}s: {exc}"
        )

    if completed.returncode != 0:
        pytest.fail(
            "fresh service snapshot failed "
            f"with exit {completed.returncode}; "
            f"stdout_tail={completed.stdout[-2000:]!r}; "
            f"stderr_tail={completed.stderr[-2000:]!r}"
        )
    try:
        snapshot = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            "fresh service snapshot emitted invalid JSON; "
            f"stdout_tail={completed.stdout[-1000:]!r}; "
            f"stderr_tail={completed.stderr[-1000:]!r}; error={exc}"
        )
    if not isinstance(snapshot, dict):
        pytest.fail(f"fresh service snapshot must be an object: {snapshot!r}")
    routes = snapshot.get("routes")
    if not isinstance(routes, list) or not all(
        isinstance(route, dict) for route in routes
    ):
        pytest.fail(f"fresh service snapshot routes must be objects: {snapshot!r}")
    if snapshot.get("source_app") != "merger/repoground/service/app.py":
        pytest.fail(
            "fresh service snapshot resolved outside the requested checkout: "
            f"{snapshot.get('source_app')!r}"
        )
    if not isinstance(snapshot.get("openapi_sha256"), str):
        pytest.fail(
            f"fresh service snapshot OpenAPI hash must be a string: {snapshot!r}"
        )
    return snapshot


@pytest.fixture(scope="module")
def fresh_service_contract_snapshot() -> dict[str, object]:
    return _fresh_service_contract_snapshot()


def _preserve_init_service_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    for field in SERVICE_STATE_FIELDS:
        monkeypatch.setattr(
            service_app.state,
            field,
            getattr(service_app.state, field),
        )

    security = get_security_config()
    monkeypatch.setattr(
        security,
        "allowlist_roots",
        list(security.allowlist_roots),
    )
    monkeypatch.setattr(security, "token", security.token)
    monkeypatch.setattr(
        security,
        "sensitive_fs_access",
        security.sensitive_fs_access,
    )
    monkeypatch.setattr(
        security,
        "home_preset_root",
        security.home_preset_root,
    )
    monkeypatch.setattr(
        service_app.app,
        "user_middleware",
        list(service_app.app.user_middleware),
    )
    monkeypatch.setattr(service_app.app, "middleware_stack", None)


def _build_query_index(root: Path) -> Path:
    canonical = root / "canonical.md"
    canonical.write_text("def main():\n    return 't012 query result'\n", encoding="utf-8")
    content = canonical.read_text(encoding="utf-8")
    content_bytes = content.encode("utf-8")
    dump = root / "dump.json"
    chunks = root / "chunks.jsonl"
    database = root / "query.index.sqlite"
    dump.write_text(
        json.dumps(
            {
                "artifacts": {
                    "canonical_md": {
                        "path": canonical.name,
                        "role": "canonical_md",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    chunks.write_text(
        json.dumps(
            {
                "artifact_type": "code",
                "canonical_range": {
                    "artifact_role": "canonical_md",
                    "content_sha256": hashlib.sha256(content_bytes).hexdigest(),
                    "end_byte": len(content_bytes),
                    "file_path": canonical.name,
                    "start_byte": 0,
                },
                "chunk_id": "t012-closeout-chunk",
                "content_sha256": hashlib.sha256(content_bytes).hexdigest(),
                "end_line": 2,
                "layer": "core",
                "path": "src/main.py",
                "repo_id": "repo",
                "start_line": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    index_db.build_index(dump, chunks, database)
    return database


@pytest.fixture
def isolated_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    hub = tmp_path / "hub"
    merges = tmp_path / "merges"
    (hub / "repo").mkdir(parents=True)
    merges.mkdir()

    _preserve_init_service_globals(monkeypatch)

    service_app.init_service(
        hub,
        token="t012-closeout-token",
        host="127.0.0.1",
        merges_dir=merges,
    )
    monkeypatch.setattr(service_app.state.runner, "submit_job", lambda _job_id: None)

    database = _build_query_index(merges)
    request = JobRequest(
        repos=["repo"],
        pre_pull=False,
        repo_source_mode="local_current",
    )
    artifact = Artifact(
        id="t012-query-index",
        job_id="t012-fixture",
        hub=str(hub),
        repos=["repo"],
        created_at="2026-07-30T00:00:00+00:00",
        paths={"sqlite_index": database.name},
        params=request,
        merges_dir=str(merges),
    )
    service_app.state.job_store.add_artifact(artifact)

    with TestClient(service_app.app) as client:
        yield client, database


def test_current_api_surface_matches_pre_split_contract(
    fresh_service_contract_snapshot: dict[str, object],
) -> None:
    routes = fresh_service_contract_snapshot["routes"]
    assert isinstance(routes, list)
    actual_method_paths = {
        (str(route["method"]), str(route["path"]))
        for route in routes
        if isinstance(route, dict)
    }
    route_by_method_path = {
        (str(route["method"]), str(route["path"])): route
        for route in routes
        if isinstance(route, dict)
    }

    assert actual_method_paths == EXPECTED_API_METHOD_PATHS
    assert len(actual_method_paths) == len(EXPECTED_API_METHOD_PATHS) == 33

    for key, expected_module in EXTRACTED_ROUTE_MODULES.items():
        assert route_by_method_path[key]["endpoint_module"] == expected_module

    assert (
        fresh_service_contract_snapshot["openapi_sha256"]
        == PRE_SPLIT_OPENAPI_SHA256
    )


def test_all_non_health_api_routes_keep_auth_dependency(
    fresh_service_contract_snapshot: dict[str, object],
) -> None:
    routes = fresh_service_contract_snapshot["routes"]
    assert isinstance(routes, list)
    actual_method_paths = {
        (str(route["method"]), str(route["path"]))
        for route in routes
        if isinstance(route, dict)
    }
    assert actual_method_paths == EXPECTED_API_METHOD_PATHS
    assert len(actual_method_paths) == len(EXPECTED_API_METHOD_PATHS) == 33

    public_routes = {
        ("GET", "/api/health"),
        ("GET", "/api/version"),
    }
    for route in routes:
        assert isinstance(route, dict)
        key = (str(route["method"]), str(route["path"]))
        if key in public_routes:
            assert route["auth_required"] is False
        else:
            assert route["auth_required"] is True, f"{key} lost verify_token"


def test_fresh_snapshot_ignores_mutated_in_process_app() -> None:
    routes = service_app.app.routes
    original_routes = list(routes)
    routes[:] = []
    try:
        assert _api_routes() == []

        snapshot = _fresh_service_contract_snapshot()
        snapshot_routes = snapshot["routes"]
        assert isinstance(snapshot_routes, list)
        assert len(snapshot_routes) == 33
        assert snapshot["openapi_sha256"] == PRE_SPLIT_OPENAPI_SHA256
    finally:
        routes[:] = original_routes

    assert service_app.app.routes == original_routes


def test_isolated_service_readback_covers_health_auth_jobs_and_query(
    isolated_service,
) -> None:
    client, database = isolated_service
    headers = {"Authorization": "Bearer t012-closeout-token"}

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["auth_enabled"] is True
    assert health.json()["running_jobs"] == 0

    assert client.get("/api/jobs").status_code == 401
    assert (
        client.get(
            "/api/jobs",
            headers={"Authorization": "Bearer wrong-token"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/query",
            json={"index_id": "t012-query-index", "q": "t012"},
        ).status_code
        == 401
    )

    created = client.post(
        "/api/jobs",
        headers=headers,
        json={
            "repos": ["repo"],
            "pre_pull": False,
            "repo_source_mode": "local_current",
        },
    )
    assert created.status_code == 200
    job_id = created.json()["id"]
    assert created.json()["status"] == "queued"

    fetched = client.get(f"/api/jobs/{job_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == job_id

    listed = client.get("/api/jobs?status=queued&limit=1", headers=headers)
    assert listed.status_code == 200
    assert [job["id"] for job in listed.json()] == [job_id]

    canceled = client.post(f"/api/jobs/{job_id}/cancel", headers=headers)
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceling"
    assert (
        client.get(f"/api/jobs/{job_id}", headers=headers).json()["status"]
        == "canceling"
    )

    before = (
        database.stat().st_size,
        database.stat().st_mtime_ns,
        _sha256(database),
    )
    query = client.post(
        "/api/query",
        headers=headers,
        json={
            "index_id": "t012-query-index",
            "q": "t012",
            "k": 1,
            "stale_policy": "ignore",
        },
    )
    after = (
        database.stat().st_size,
        database.stat().st_mtime_ns,
        _sha256(database),
    )
    assert query.status_code == 200
    assert query.json()["count"] == 1
    assert query.json()["results"][0]["chunk_id"] == "t012-closeout-chunk"
    assert after == before


def test_init_service_globals_restore_after_monkeypatch_context(
    tmp_path: Path,
) -> None:
    hub = tmp_path / "hub"
    merges = tmp_path / "merges"
    hub.mkdir()
    merges.mkdir()
    security = get_security_config()
    original_state = {
        field: getattr(service_app.state, field)
        for field in SERVICE_STATE_FIELDS
    }
    original_security = {
        "allowlist_roots": security.allowlist_roots,
        "token": security.token,
        "sensitive_fs_access": security.sensitive_fs_access,
        "home_preset_root": security.home_preset_root,
    }
    original_user_middleware = service_app.app.user_middleware
    original_middleware_stack = service_app.app.middleware_stack

    with pytest.MonkeyPatch.context() as context:
        _preserve_init_service_globals(context)
        service_app.init_service(
            hub,
            token="t012-context-token",
            host="127.0.0.1",
            merges_dir=merges,
        )
        assert service_app.state.hub == hub
        assert service_app.state.merges_dir == merges

    for field, original in original_state.items():
        assert getattr(service_app.state, field) is original
    for field, original in original_security.items():
        assert getattr(security, field) is original
    assert service_app.app.user_middleware is original_user_middleware
    assert service_app.app.middleware_stack is original_middleware_stack


@pytest.mark.parametrize(
    ("host", "token", "sensitive_access_expected"),
    [
        ("127.0.0.1", None, False),
        ("0.0.0.0", "t012-token", False),
        ("127.0.0.1", "t012-token", True),
    ],
)
def test_sensitive_filesystem_access_requires_loopback_and_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    host: str,
    token: str | None,
    sensitive_access_expected: bool,
) -> None:
    hub = tmp_path / "hub"
    hub.mkdir()
    security = get_security_config()
    _preserve_init_service_globals(monkeypatch)

    service_app.init_service(hub, token=token, host=host)

    assert security.sensitive_fs_access is sensitive_access_expected
    assert (Path("/") in security.allowlist_roots) is sensitive_access_expected


def _snapshot_main() -> int:
    if sys.argv[1:] != ["--service-snapshot"]:
        raise SystemExit(
            "usage: test_service_router_closeout.py --service-snapshot"
        )
    print(
        json.dumps(
            _service_contract_snapshot(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_snapshot_main())
