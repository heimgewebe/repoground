#!/usr/bin/env python3
"""Measure the T012 service-router split against two exact Git revisions.

The driver archives both revisions, alternates fresh subprocess measurements,
and compares the normalized FastAPI/OpenAPI surface.  Request timings use the
in-process ASGI ``TestClient`` so socket, Uvicorn, proxy, and TLS costs are
deliberately outside this benchmark.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROUNDS = 9
DEFAULT_REQUEST_SAMPLES = 30
DEFAULT_WARMUP_REQUESTS = 5
WORKER_TIMEOUT_SECONDS = 120

DOES_NOT_ESTABLISH = [
    "cross-host comparability of absolute timings",
    "production network or Uvicorn latency",
    "production workload representativeness",
    "steady-state or whole-system memory usage",
    "statistical significance of small before/after differences",
    "absence of regressions on unmeasured endpoints",
]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalized_openapi(openapi: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(openapi))
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
    return normalized


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def _exact_revision(repo: Path, revision: str) -> dict[str, str]:
    commit = _git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}")
    tree = _git(repo, "rev-parse", "--verify", f"{commit}^{{tree}}")
    return {"requested": revision, "commit": commit, "tree": tree}


def _archive_revision(repo: Path, commit: str, destination: Path) -> None:
    archive = destination.parent / f"{commit}.tar"
    completed = subprocess.run(
        [
            "git",
            "archive",
            "--format=tar",
            f"--output={archive}",
            commit,
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git archive failed for {commit}: {completed.stderr.strip()}"
        )
    destination.mkdir(parents=True)
    completed = subprocess.run(
        ["tar", "-xf", str(archive), "-C", str(destination)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"tar extraction failed for {commit}: {completed.stderr.strip()}"
        )


def _rss_kib() -> int:
    statm = Path("/proc/self/statm")
    if not statm.is_file():
        raise RuntimeError("RSS measurement requires Linux /proc/self/statm")
    fields = statm.read_text(encoding="ascii").split()
    if len(fields) < 2:
        raise RuntimeError("unexpected /proc/self/statm shape")
    return int(fields[1]) * int(os.sysconf("SC_PAGE_SIZE")) // 1024


def _peak_rss_kib() -> int:
    status = Path("/proc/self/status")
    if not status.is_file():
        raise RuntimeError("peak RSS measurement requires Linux /proc/self/status")
    for line in status.read_text(encoding="ascii").splitlines():
        if line.startswith("VmHWM:"):
            fields = line.split()
            if len(fields) == 3 and fields[2] == "kB":
                return int(fields[1])
            break
    raise RuntimeError("unexpected VmHWM shape in /proc/self/status")


def _route_inventory(app: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pending = list(app.routes)
    seen_collections: set[int] = set()
    while pending:
        route = pending.pop(0)
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if isinstance(path, str) and path.startswith("/api") and methods:
            response_model = getattr(route, "response_model", None)
            rows.append(
                {
                    "include_in_schema": bool(
                        getattr(route, "include_in_schema", False)
                    ),
                    "methods": sorted(
                        method
                        for method in methods
                        if method not in {"HEAD", "OPTIONS"}
                    ),
                    "name": str(getattr(route, "name", "")),
                    "path": path,
                    "response_model": (
                        getattr(response_model, "__name__", str(response_model))
                        if response_model is not None
                        else None
                    ),
                }
            )

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
    return sorted(
        rows,
        key=lambda row: (
            row["path"],
            row["methods"],
            row["name"],
        ),
    )


def _worker_measurement(
    source_root: Path,
    *,
    warmup_requests: int,
    request_samples: int,
) -> dict[str, Any]:
    if not (source_root / "merger" / "repoground" / "service" / "app.py").is_file():
        raise RuntimeError(f"source root has no RepoGround service app: {source_root}")

    sys.path.insert(0, str(source_root))
    rss_before_import_kib = _rss_kib()
    import_started = time.perf_counter_ns()
    from merger.repoground.service import app as app_module

    import_ms = (time.perf_counter_ns() - import_started) / 1_000_000
    rss_after_import_kib = _rss_kib()
    peak_rss_after_import_kib = _peak_rss_kib()

    openapi = _normalized_openapi(app_module.app.openapi())
    route_inventory = _route_inventory(app_module.app)
    openapi_sha256 = _sha256_bytes(_canonical_json(openapi))
    route_inventory_sha256 = _sha256_bytes(_canonical_json(route_inventory))

    from fastapi.testclient import TestClient

    with tempfile.TemporaryDirectory(prefix="repoground-t012-worker-") as raw_tmp:
        worker_root = Path(raw_tmp)
        hub = worker_root / "hub"
        merges = worker_root / "merges"
        (hub / "repo").mkdir(parents=True)
        merges.mkdir()

        app_module.app.middleware_stack = None
        app_module.init_service(
            hub,
            token="t012-benchmark-token",
            host="0.0.0.0",
            merges_dir=merges,
        )
        latencies_ms: list[float] = []
        with TestClient(app_module.app) as client:
            for _ in range(warmup_requests):
                response = client.get("/api/health")
                if response.status_code != 200:
                    raise RuntimeError(
                        f"health warmup returned HTTP {response.status_code}"
                    )
            for _ in range(request_samples):
                started = time.perf_counter_ns()
                response = client.get("/api/health")
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
                if response.status_code != 200:
                    raise RuntimeError(
                        f"health request returned HTTP {response.status_code}"
                    )
                body = response.json()
                if body.get("status") != "ok" or body.get("auth_enabled") is not True:
                    raise RuntimeError("health response failed benchmark invariants")
                latencies_ms.append(round(elapsed_ms, 6))

    return {
        "import_app_ms": round(import_ms, 6),
        "rss_before_import_kib": rss_before_import_kib,
        "rss_after_import_kib": rss_after_import_kib,
        "rss_import_delta_kib": rss_after_import_kib - rss_before_import_kib,
        "peak_rss_after_import_kib": peak_rss_after_import_kib,
        "rss_after_requests_kib": _rss_kib(),
        "peak_rss_after_requests_kib": _peak_rss_kib(),
        "health_request_ms": latencies_ms,
        "openapi_sha256": openapi_sha256,
        "route_inventory_sha256": route_inventory_sha256,
        "route_count": len(route_inventory),
        "openapi_path_count": len(openapi.get("paths", {})),
        "openapi_schema_count": len(
            openapi.get("components", {}).get("schemas", {})
        ),
    }


def _run_worker(
    script: Path,
    source_root: Path,
    *,
    warmup_requests: int,
    request_samples: int,
) -> dict[str, Any]:
    environment = dict(os.environ)
    environment.update(
        {
            "LC_ALL": "C.UTF-8",
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": str(source_root),
            "REPOGROUND_BUILD_ID": "t012-benchmark",
            "REPOGROUND_VERSION": "t012-benchmark",
            "TZ": "UTC",
        }
    )
    command = [
        sys.executable,
        str(script),
        "--worker",
        "--source-root",
        str(source_root),
        "--warmup-requests",
        str(warmup_requests),
        "--request-samples",
        str(request_samples),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=source_root,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=WORKER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"worker timed out after {WORKER_TIMEOUT_SECONDS}s in {source_root}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"worker failed in {source_root}: {detail[-2000:]}")
    return json.loads(completed.stdout)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("cannot calculate a percentile of an empty sample")
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    import_values = [float(row["import_app_ms"]) for row in rows]
    latency_values = [
        float(value)
        for row in rows
        for value in row["health_request_ms"]
    ]

    def median_int(field: str) -> int:
        return int(statistics.median(int(row[field]) for row in rows))

    return {
        "fresh_process_rounds": len(rows),
        "request_samples_total": len(latency_values),
        "import_app_ms": {
            "min": round(min(import_values), 6),
            "median": round(statistics.median(import_values), 6),
            "max": round(max(import_values), 6),
            "samples": [round(value, 6) for value in import_values],
        },
        "health_request_ms": {
            "min": round(min(latency_values), 6),
            "p50": round(_percentile(latency_values, 0.50), 6),
            "p95": round(_percentile(latency_values, 0.95), 6),
            "max": round(max(latency_values), 6),
        },
        "memory_kib": {
            "rss_before_import_median": median_int("rss_before_import_kib"),
            "rss_after_import_median": median_int("rss_after_import_kib"),
            "rss_import_delta_median": median_int("rss_import_delta_kib"),
            "peak_rss_after_import_median": median_int(
                "peak_rss_after_import_kib"
            ),
            "rss_after_requests_median": median_int("rss_after_requests_kib"),
            "peak_rss_after_requests_median": median_int(
                "peak_rss_after_requests_kib"
            ),
        },
        "api_observations": {
            "openapi_sha256": sorted(
                {str(row["openapi_sha256"]) for row in rows}
            ),
            "route_inventory_sha256": sorted(
                {str(row["route_inventory_sha256"]) for row in rows}
            ),
            "route_counts": sorted({int(row["route_count"]) for row in rows}),
            "openapi_path_counts": sorted(
                {int(row["openapi_path_count"]) for row in rows}
            ),
            "openapi_schema_counts": sorted(
                {int(row["openapi_schema_count"]) for row in rows}
            ),
        },
    }


def _percent_change(before: float, after: float) -> float:
    if before == 0:
        return 0.0 if after == 0 else float("inf")
    return ((after - before) / before) * 100.0


def _api_parity(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    before_api = before["api_observations"]
    after_api = after["api_observations"]
    stable_each_side = all(
        len(observation[field]) == 1
        for observation in (before_api, after_api)
        for field in (
            "openapi_sha256",
            "route_inventory_sha256",
            "route_counts",
            "openapi_path_counts",
            "openapi_schema_counts",
        )
    )
    identical = before_api == after_api
    return {
        "status": "pass" if stable_each_side and identical else "fail",
        "stable_within_each_revision": stable_each_side,
        "identical_between_revisions": identical,
        "before": before_api,
        "after": after_api,
    }


def _environment() -> dict[str, Any]:
    dependency_versions: dict[str, str | None] = {}
    for name in ("fastapi", "httpx", "pydantic", "starlette"):
        try:
            dependency_versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependency_versions[name] = None

    cpu_model = None
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("model name") and ":" in line:
                cpu_model = line.split(":", 1)[1].strip()
                break
    return {
        "cpu_count": os.cpu_count(),
        "cpu_model": cpu_model,
        "dependencies": dependency_versions,
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "rss_source": "/proc/self/statm current RSS and /proc/self/status VmHWM on Linux",
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def run_comparison(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo.resolve()
    before_binding = _exact_revision(repo, args.before_revision)
    after_binding = _exact_revision(repo, args.after_revision)
    script = Path(__file__).resolve()
    load_start = list(os.getloadavg())

    with tempfile.TemporaryDirectory(
        prefix="repoground-t012-comparison-"
    ) as raw_tmp:
        comparison_root = Path(raw_tmp)
        source_roots = {
            "before": comparison_root / "before",
            "after": comparison_root / "after",
        }
        _archive_revision(
            repo,
            before_binding["commit"],
            source_roots["before"],
        )
        _archive_revision(
            repo,
            after_binding["commit"],
            source_roots["after"],
        )

        rows: dict[str, list[dict[str, Any]]] = {"before": [], "after": []}
        execution_order: list[list[str]] = []
        for round_index in range(args.rounds):
            order = (
                ["before", "after"]
                if round_index % 2 == 0
                else ["after", "before"]
            )
            execution_order.append(order)
            for label in order:
                rows[label].append(
                    _run_worker(
                        script,
                        source_roots[label],
                        warmup_requests=args.warmup_requests,
                        request_samples=args.request_samples,
                    )
                )

    summaries = {
        label: _summary(case_rows)
        for label, case_rows in rows.items()
    }
    parity = _api_parity(summaries["before"], summaries["after"])
    before_import = summaries["before"]["import_app_ms"]["median"]
    after_import = summaries["after"]["import_app_ms"]["median"]
    before_latency = summaries["before"]["health_request_ms"]["p50"]
    after_latency = summaries["after"]["health_request_ms"]["p50"]
    before_memory = summaries["before"]["memory_kib"][
        "rss_after_import_median"
    ]
    after_memory = summaries["after"]["memory_kib"][
        "rss_after_import_median"
    ]

    report = {
        "kind": "repoground.t012_service_router_split_measurement",
        "version": "v1",
        "status": "pass" if parity["status"] == "pass" else "fail",
        "binding": {
            "repository": str(repo),
            "benchmark_script": str(script.relative_to(repo)),
            "benchmark_script_sha256": _sha256_file(script),
            "before": before_binding,
            "after": after_binding,
            "before_is_ancestor_of_after": (
                subprocess.run(
                    [
                        "git",
                        "merge-base",
                        "--is-ancestor",
                        before_binding["commit"],
                        after_binding["commit"],
                    ],
                    cwd=repo,
                    check=False,
                    capture_output=True,
                ).returncode
                == 0
            ),
        },
        "configuration": {
            "rounds_per_revision": args.rounds,
            "request_samples_per_round": args.request_samples,
            "warmup_requests_per_round": args.warmup_requests,
            "fresh_process_per_round": True,
            "execution_order": execution_order,
            "pythonhashseed": "0",
            "repoground_version_override": "t012-benchmark",
            "repoground_build_id_override": "t012-benchmark",
        },
        "environment": {
            **_environment(),
            "load_average_start": load_start,
            "load_average_end": list(os.getloadavg()),
        },
        "method": {
            "source_materialization": "git archive of exact commit, extracted into a temporary directory",
            "import_start": "perf_counter_ns around fresh-process import of merger.repoground.service.app; app construction occurs during import",
            "request_latency": "FastAPI TestClient GET /api/health after per-process warmups",
            "memory": "current and peak resident set size in KiB; RSS after import is the primary comparison",
            "api_parity": "canonical JSON SHA-256 of OpenAPI after removing only FastAPI/Pydantic ValidationError ctx/input diagnostics, plus normalized /api route inventory",
            "ordering": "alternating before/after order to limit systematic shared-host drift",
        },
        "api_parity": parity,
        "summaries": summaries,
        "comparison": {
            "import_app_median_change_pct": round(
                _percent_change(before_import, after_import),
                3,
            ),
            "health_request_p50_change_pct": round(
                _percent_change(before_latency, after_latency),
                3,
            ),
            "rss_after_import_median_change_pct": round(
                _percent_change(before_memory, after_memory),
                3,
            ),
            "interpretation": "observational only; no performance threshold is an acceptance gate",
        },
        "raw_rounds": rows,
        "does_not_establish": DOES_NOT_ESTABLISH,
    }
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument("--before-revision")
    parser.add_argument("--after-revision", default="HEAD")
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    parser.add_argument(
        "--request-samples",
        type=int,
        default=DEFAULT_REQUEST_SAMPLES,
    )
    parser.add_argument(
        "--warmup-requests",
        type=int,
        default=DEFAULT_WARMUP_REQUESTS,
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source-root", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for field in ("rounds", "request_samples"):
        if getattr(args, field) <= 0:
            raise SystemExit(f"--{field.replace('_', '-')} must be positive")
    if args.warmup_requests < 0:
        raise SystemExit("--warmup-requests must be non-negative")

    if args.worker:
        if args.source_root is None:
            raise SystemExit("--source-root is required with --worker")
        payload = _worker_measurement(
            args.source_root.resolve(),
            warmup_requests=args.warmup_requests,
            request_samples=args.request_samples,
        )
    else:
        if not args.before_revision:
            raise SystemExit("--before-revision is required")
        payload = run_comparison(args)

    if args.output is not None:
        _write_json_atomic(args.output.resolve(), payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("status", "pass") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
