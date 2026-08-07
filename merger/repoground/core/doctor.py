"""Read-only RepoGround environment and evidence readiness diagnostics.

The doctor composes existing RepoGround truth surfaces.  It may inspect local
runtime capabilities, existing bundle publications and one explicitly selected
local checkout.  It never installs dependencies, refreshes bundles, mutates Git,
starts services, reads secrets or performs network synchronization.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
from typing import Any, Callable

from merger.repoground.core.bundle_catalog import (
    BundleCatalogError,
    checkout_repo_identity,
    inspect_bundle_health,
    select_bundle_manifest,
)
from merger.repoground.core.live_freshness import evaluate_live_freshness

KIND = "repoground.doctor"
VERSION = "1.0"
STATUS_VALUES = ("available", "degraded", "blocked")
_MAX_CONFIG_BYTES = 256 * 1024
_GIT_TIMEOUT_SECONDS = 3

DOES_NOT_ESTABLISH = (
    "remote_freshness",
    "runtime_correctness",
    "repository_understanding",
    "answer_correctness",
    "test_sufficiency",
    "review_completeness",
    "merge_readiness",
    "service_reachability",
    "optional_adapter_semantic_correctness",
)


def _check(
    check_id: str,
    status: str,
    *,
    cause: str,
    impact: str,
    next_action: str,
    optional: bool = False,
    evidence: dict[str, Any] | None = None,
    does_not_establish: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    if status not in STATUS_VALUES:
        raise ValueError(f"unsupported doctor status: {status}")
    return {
        "id": check_id,
        "status": status,
        "optional": optional,
        "cause": cause,
        "impact": impact,
        "next_action": next_action,
        "evidence": evidence or {},
        "does_not_establish": list(does_not_establish),
    }


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def check_python_runtime() -> dict[str, Any]:
    version = tuple(sys.version_info[:3])
    evidence = {
        "implementation": sys.implementation.name,
        "version": ".".join(str(item) for item in version),
        "ci_release_baseline": "3.12",
    }
    if version < (3, 10):
        return _check(
            "python",
            "blocked",
            cause="python_version_too_old",
            impact="RepoGround uses language/runtime features that require Python 3.10 or newer.",
            next_action="Use Python 3.12, the current CI and release-candidate baseline.",
            evidence=evidence,
        )
    if version[:2] != (3, 12):
        return _check(
            "python",
            "degraded",
            cause="python_version_outside_ci_release_baseline",
            impact="Core commands may work, but this interpreter is not the currently reproduced CI/release baseline.",
            next_action="Prefer Python 3.12 for reproducible validation; do not auto-install or replace the interpreter.",
            evidence=evidence,
        )
    return _check(
        "python",
        "available",
        cause="python_ci_release_baseline_matches",
        impact="The interpreter matches the current RepoGround full-suite and release-candidate baseline.",
        next_action="No action required.",
        evidence=evidence,
    )


def _git_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def check_git_runtime() -> dict[str, Any]:
    executable = shutil.which("git")
    if not executable:
        return _check(
            "git",
            "blocked",
            cause="git_executable_missing",
            impact="Local provenance and freshness checks cannot establish a repository revision.",
            next_action="Make an existing Git executable available; doctor will not install it.",
        )
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
            env=_git_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _check(
            "git",
            "blocked",
            cause="git_probe_failed",
            impact="Git exists but could not be executed for bounded local diagnostics.",
            next_action="Inspect the local Git installation; no network or repair was attempted.",
            evidence={"error_type": type(exc).__name__},
        )
    if completed.returncode != 0:
        return _check(
            "git",
            "blocked",
            cause="git_version_command_failed",
            impact="Git cannot be trusted for local provenance diagnostics in this process.",
            next_action="Inspect the local Git installation; no repository mutation was attempted.",
            evidence={"returncode": completed.returncode},
        )
    return _check(
        "git",
        "available",
        cause="git_executable_available",
        impact="Bounded local Git provenance checks are available.",
        next_action="No action required.",
        evidence={"executable": executable, "version": completed.stdout.strip()},
        does_not_establish=["remote_repository_state"],
    )


def check_sqlite_fts(
    *, connect: Callable[..., sqlite3.Connection] = sqlite3.connect
) -> dict[str, Any]:
    connection: sqlite3.Connection | None = None
    try:
        connection = connect(":memory:")
        connection.execute("CREATE VIRTUAL TABLE doctor_fts USING fts5(content)")
        connection.execute("INSERT INTO doctor_fts(content) VALUES (?)", ("repoground",))
        row = connection.execute(
            "SELECT count(*) FROM doctor_fts WHERE doctor_fts MATCH ?", ("repoground",)
        ).fetchone()
        if not row or row[0] != 1:
            raise sqlite3.DatabaseError("FTS5 smoke query returned an unexpected result")
    except (sqlite3.Error, OSError, RuntimeError) as exc:
        return _check(
            "sqlite_fts",
            "blocked",
            cause="sqlite_fts5_unavailable",
            impact="The deterministic lexical retrieval index cannot be built or queried with FTS5.",
            next_action="Use a Python/SQLite build with FTS5 support; doctor will not modify SQLite or install packages.",
            evidence={
                "sqlite_version": sqlite3.sqlite_version,
                "error_type": type(exc).__name__,
                "error": str(exc)[:240],
            },
        )
    finally:
        if connection is not None:
            connection.close()
    return _check(
        "sqlite_fts",
        "available",
        cause="sqlite_fts5_smoke_passed",
        impact="In-memory FTS5 creation and lookup work for the lexical retrieval core.",
        next_action="No action required.",
        evidence={"sqlite_version": sqlite3.sqlite_version},
    )


def check_jsonschema_dependency() -> dict[str, Any]:
    available = _module_available("jsonschema")
    if not available:
        return _check(
            "jsonschema",
            "degraded",
            cause="jsonschema_dependency_missing",
            impact="Core reading remains available, but full schema validation and some strict integrity gates are degraded.",
            next_action="Install the pinned development dependencies when strict validation is required; doctor will not install them.",
            evidence={"available": False},
        )
    return _check(
        "jsonschema",
        "available",
        cause="jsonschema_dependency_available",
        impact="Strict JSON-Schema validation paths can be used.",
        next_action="No action required.",
        evidence={"available": True},
    )


def check_wrapper() -> dict[str, Any]:
    executable = shutil.which("repoground")
    if executable is None:
        return _check(
            "wrapper",
            "degraded",
            cause="repoground_wrapper_not_on_path",
            impact="The optional convenience command is unavailable, but the canonical module CLI remains usable.",
            next_action="Use `python -m merger.repoground`; install a wrapper only if desired.",
            optional=True,
            evidence={"module_cli": "python -m merger.repoground"},
            does_not_establish=["module_cli_failure"],
        )
    return _check(
        "wrapper",
        "available",
        cause="repoground_wrapper_on_path",
        impact="The optional convenience starter is discoverable on PATH.",
        next_action="No action required.",
        optional=True,
        evidence={"executable": executable},
        does_not_establish=["service_readiness"],
    )


def _regular_file(path: Path) -> tuple[bool, str | None]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        return False, type(exc).__name__
    if stat.S_ISLNK(metadata.st_mode):
        return False, "symbolic_link"
    if not stat.S_ISREG(metadata.st_mode):
        return False, "not_regular_file"
    return True, None


def _read_json_object(path: Path) -> dict[str, Any]:
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError("configuration is not a regular non-symlink file")
    if before.st_size > _MAX_CONFIG_BYTES:
        raise ValueError("configuration exceeds doctor size bound")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        opened_identity = (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        )
        if identity != opened_identity or not stat.S_ISREG(opened.st_mode):
            raise ValueError("configuration changed before reading")
        chunks: list[bytes] = []
        remaining = _MAX_CONFIG_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(raw) > _MAX_CONFIG_BYTES:
            raise ValueError("configuration exceeds doctor size bound")
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if after_identity != opened_identity or len(raw) != after.st_size:
            raise ValueError("configuration changed while reading")
    finally:
        os.close(descriptor)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("configuration must be a JSON object")
    return value


def check_mcp_configuration(
    repo_root: str | Path,
    *,
    config_path: str | Path | None = None,
    starter_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    config = (
        Path(config_path).expanduser().absolute()
        if config_path is not None
        else root / ".mcp.json"
    )
    starter = (
        Path(starter_path).expanduser().absolute()
        if starter_path is not None
        else root / "scripts" / "repoground-mcp-project.py"
    )
    starter_ok, starter_error = _regular_file(starter)
    if not starter_ok:
        return _check(
            "mcp_configuration",
            "degraded",
            cause="mcp_project_starter_unavailable",
            impact="Project-local MCP startup is unavailable; the module CLI and non-MCP RepoGround core are unaffected.",
            next_action="Restore the tracked project starter or use the documented module-form MCP command; doctor will not create it.",
            evidence={
                "config_path": str(config),
                "starter_path": str(starter),
                "starter_error": starter_error,
            },
            does_not_establish=["core_cli_failure"],
        )
    try:
        payload = _read_json_object(config)
        servers = payload.get("mcpServers")
        server = servers.get("repoground") if isinstance(servers, dict) else None
        command = server.get("command") if isinstance(server, dict) else None
        args = server.get("args") if isinstance(server, dict) else None
        expected_relative = "scripts/repoground-mcp-project.py"
        valid = (
            isinstance(command, str)
            and bool(command.strip())
            and isinstance(args, list)
            and all(isinstance(item, str) for item in args)
            and bool(args)
            and args[0] in {expected_relative, str(starter)}
        )
        if not valid:
            raise ValueError("repoground MCP server entry does not target the project starter")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return _check(
            "mcp_configuration",
            "degraded",
            cause="mcp_project_configuration_invalid",
            impact="The tracked project-local MCP configuration cannot be used reliably; non-MCP RepoGround remains available.",
            next_action="Repair the project-local MCP configuration deliberately; doctor will not rewrite it.",
            evidence={
                "config_path": str(config),
                "starter_path": str(starter),
                "error_type": type(exc).__name__,
                "error": str(exc)[:240],
            },
            does_not_establish=["core_cli_failure"],
        )
    return _check(
        "mcp_configuration",
        "available",
        cause="mcp_project_configuration_bound_to_starter",
        impact="The tracked MCP configuration points to the existing project-local starter.",
        next_action="No action required.",
        evidence={
            "config_path": str(config),
            "starter_path": str(starter),
            "command": command,
            "starter_argument": args[0],
        },
        does_not_establish=["mcp_client_connected", "mcp_runtime_correctness"],
    )


_ADAPTER_MODULES = (
    ("python_call_graph", "merger.repoground.core.call_graph_navigation"),
    ("scip_graph", "merger.repoground.core.scip_adapter"),
    ("rust_structure", "merger.repoground.core.rust_structure_adapter"),
    ("bash_structure", "merger.repoground.core.bash_structure_adapter"),
)


def check_optional_adapters() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for adapter_id, module in _ADAPTER_MODULES:
        available = _module_available(module)
        checks.append(
            _check(
                f"adapter:{adapter_id}",
                "available" if available else "degraded",
                cause=("adapter_module_available" if available else "adapter_module_unavailable"),
                impact=(
                    "The optional adapter module can be used when coherent evidence is supplied."
                    if available
                    else "This optional structural lane is unavailable; lexical/text and Python-core paths remain unaffected."
                ),
                next_action=(
                    "No action required."
                    if available
                    else "Keep using supported fallback lanes; do not auto-install or infer adapter output."
                ),
                optional=True,
                evidence={"module": module, "available": available},
                does_not_establish=["runtime_behavior", "adapter_semantic_completeness"],
            )
        )
    return checks


def _default_bundle_root(repo_root: Path) -> Path | None:
    configured = os.environ.get("REPOGROUND_BUNDLE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    configured = os.environ.get("REPOGROUND_PUBLICATION_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    candidates = [repo_root.parent / "manifest-publications" / "bundles"]
    candidates.extend(
        parent / "manifest-publications" / "bundles" for parent in repo_root.parents[:3]
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _catalog_check_from_selection(
    root: Path,
    repo_identity: str | None,
    selection: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    evidence = {
        "bundle_root": str(root),
        "repo_identity": repo_identity,
        "selection_status": selection.get("status"),
        "selection_reason": selection.get("reason"),
    }
    selected = selection.get("selected")
    selected_manifest = (
        selected.get("manifest_path") if isinstance(selected, dict) else None
    )
    status = selection.get("status")
    if status == "available" and isinstance(selected_manifest, str):
        evidence.update(
            {
                "manifest_path": selected_manifest,
                "manifest_sha256": selected.get("manifest_sha256"),
            }
        )
        return (
            _check(
                "bundle_catalog",
                "available",
                cause="unique_healthy_bundle_selected",
                impact="A unique healthy existing RepoGround bundle is selected for this repository identity.",
                next_action="No action required.",
                evidence=evidence,
            ),
            selected_manifest,
        )
    if status == "ambiguous":
        return (
            _check(
                "bundle_catalog",
                "blocked",
                cause=str(selection.get("reason") or "bundle_selection_ambiguous"),
                impact="Doctor cannot choose one evidence generation without guessing.",
                next_action="Bind an exact --manifest or a qualified repository identity through the existing publication setup.",
                evidence=evidence,
            ),
            None,
        )
    if status == "blocked":
        failure_evidence = {
            **evidence,
            **{key: value for key, value in selection.items() if key.startswith("error")},
        }
        return (
            _check(
                "bundle_catalog",
                "blocked",
                cause=str(selection.get("reason") or "bundle_catalog_probe_failed"),
                impact="Existing publication discovery could not be evaluated safely.",
                next_action="Inspect the catalog error; doctor will not repair or refresh publications.",
                evidence=failure_evidence,
            ),
            None,
        )
    return (
        _check(
            "bundle_catalog",
            "degraded",
            cause=str(selection.get("reason") or "no_matching_healthy_bundle"),
            impact="No unique healthy existing bundle is available for manifest/freshness checks.",
            next_action="Create or select a healthy bundle explicitly outside doctor.",
            evidence=evidence,
        ),
        None,
    )


def _select_bundle_for_doctor(
    repo_root: Path,
    *,
    bundle_root: str | Path | None,
    manifest: str | Path | None,
) -> tuple[dict[str, Any], str | None]:
    if manifest is not None:
        selected_manifest = str(Path(manifest).expanduser().resolve())
        return (
            _check(
                "bundle_catalog",
                "available",
                cause="exact_manifest_selected",
                impact="Doctor will validate the explicitly selected existing manifest without catalog discovery.",
                next_action="No action required.",
                evidence={
                    "manifest_path": selected_manifest,
                    "selection_mode": "exact_manifest",
                },
            ),
            selected_manifest,
        )
    root = (
        Path(bundle_root).expanduser().resolve()
        if bundle_root is not None
        else _default_bundle_root(repo_root)
    )
    if root is None:
        return (
            _check(
                "bundle_catalog",
                "degraded",
                cause="bundle_root_not_configured_or_discovered",
                impact="No existing publication can be selected for integrity or freshness checks.",
                next_action="Pass --bundle-root/--manifest or create a bundle explicitly outside doctor.",
            ),
            None,
        )
    try:
        repo_identity = checkout_repo_identity(repo_root)
        selection = select_bundle_manifest(
            root,
            repo=repo_identity,
            require_healthy=True,
        )
    except (BundleCatalogError, OSError, RuntimeError, ValueError) as exc:
        repo_identity = None
        selection = {
            "status": "blocked",
            "reason": "bundle_catalog_probe_failed",
            "error_type": type(exc).__name__,
            "error": str(exc)[:240],
        }
    return _catalog_check_from_selection(root, repo_identity, selection)


def _manifest_integrity_check(selected_manifest: str) -> dict[str, Any]:
    try:
        health = inspect_bundle_health(selected_manifest)
    except (OSError, RuntimeError, ValueError) as exc:
        health = {
            "status": "invalid",
            "health_status": "invalid",
            "reasons": [str(exc)],
            "manifest_sha256": None,
        }
    if health.get("health_status") == "pass":
        return _check(
            "manifest_integrity",
            "available",
            cause="manifest_bound_health_passed",
            impact="The selected manifest and its bound health evidence pass existing RepoGround integrity checks.",
            next_action="No action required.",
            evidence={
                "manifest_path": selected_manifest,
                "manifest_sha256": health.get("manifest_sha256"),
                "health_status": health.get("health_status"),
            },
            does_not_establish=["content_truth", "runtime_correctness"],
        )
    return _check(
        "manifest_integrity",
        "blocked",
        cause="manifest_health_not_pass",
        impact="The selected bundle cannot be treated as a healthy evidence generation.",
        next_action="Inspect or regenerate the bundle explicitly; doctor will not mutate it.",
        evidence={
            "manifest_path": selected_manifest,
            "manifest_sha256": health.get("manifest_sha256"),
            "health_status": health.get("health_status"),
            "reasons": health.get("reasons", []),
        },
    )


def _freshness_check(repo_root: Path, selected_manifest: str) -> dict[str, Any]:
    try:
        freshness = evaluate_live_freshness(selected_manifest, repo_root=repo_root)
    except (OSError, RuntimeError, ValueError) as exc:
        freshness = {
            "status": "unknown",
            "reason": "freshness_probe_failed",
            "error_type": type(exc).__name__,
            "error": str(exc)[:240],
        }
    status = freshness.get("status")
    evidence = {
        "status": status,
        "reason": freshness.get("reason"),
        "bundle_manifest": selected_manifest,
        "snapshot_provenance": freshness.get("snapshot_provenance"),
        "current_provenance": freshness.get("current_provenance"),
        "error_type": freshness.get("error_type"),
    }
    if status == "fresh":
        return _check(
            "freshness",
            "available",
            cause=str(freshness.get("reason") or "snapshot_matches_local_checkout"),
            impact="The selected snapshot commit matches the clean explicitly selected local checkout.",
            next_action="No action required.",
            evidence=evidence,
            does_not_establish=["freshness_against_remote"],
        )
    return _check(
        "freshness",
        "degraded",
        cause=str(freshness.get("reason") or "freshness_not_established"),
        impact="The existing snapshot is stale or cannot be proven comparable to the local checkout.",
        next_action="Treat evidence as stale/uncertain or create a new snapshot explicitly outside doctor.",
        evidence=evidence,
        does_not_establish=["freshness_against_remote"],
    )


def _bundle_checks(
    repo_root: Path,
    *,
    bundle_root: str | Path | None,
    manifest: str | Path | None,
) -> list[dict[str, Any]]:
    catalog_check, selected_manifest = _select_bundle_for_doctor(
        repo_root,
        bundle_root=bundle_root,
        manifest=manifest,
    )
    if selected_manifest is None:
        return [
            catalog_check,
            _check(
                "manifest_integrity",
                "degraded",
                cause="manifest_not_selected",
                impact="Manifest-bound artifact integrity was not checked because no bundle was selected.",
                next_action="Provide a unique healthy bundle or an exact --manifest.",
            ),
            _check(
                "freshness",
                "degraded",
                cause="manifest_not_selected",
                impact="Snapshot-vs-checkout freshness is unknown.",
                next_action="Provide a selected manifest and local repository root; doctor will not refresh it.",
            ),
        ]
    return [
        catalog_check,
        _manifest_integrity_check(selected_manifest),
        _freshness_check(repo_root, selected_manifest),
    ]


def _overall_status(checks: list[dict[str, Any]]) -> str:
    required = [check for check in checks if not check.get("optional")]
    if any(check.get("status") == "blocked" for check in required):
        return "blocked"
    if any(check.get("status") == "degraded" for check in required):
        return "degraded"
    return "available"


def build_doctor_report(
    *,
    repo_root: str | Path = ".",
    bundle_root: str | Path | None = None,
    manifest: str | Path | None = None,
    mcp_config: str | Path | None = None,
    mcp_starter: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    checks = [
        check_python_runtime(),
        check_git_runtime(),
        check_sqlite_fts(),
        check_jsonschema_dependency(),
        check_mcp_configuration(
            root,
            config_path=mcp_config,
            starter_path=mcp_starter,
        ),
        check_wrapper(),
        *check_optional_adapters(),
        *_bundle_checks(root, bundle_root=bundle_root, manifest=manifest),
    ]
    overall = _overall_status(checks)
    required_counts = {
        status: sum(
            1
            for check in checks
            if not check.get("optional") and check.get("status") == status
        )
        for status in STATUS_VALUES
    }
    optional_counts = {
        status: sum(
            1
            for check in checks
            if check.get("optional") and check.get("status") == status
        )
        for status in STATUS_VALUES
    }
    return {
        "kind": KIND,
        "version": VERSION,
        "status": overall,
        "repo_root": str(root),
        "checks": checks,
        "summary": {
            "required": required_counts,
            "optional": optional_counts,
            "optional_degradation_affects_core_status": False,
        },
        "mutation_boundary": {
            "read_only": True,
            "network_sync": False,
            "package_install": False,
            "bundle_refresh": False,
            "git_mutation": False,
            "service_mutation": False,
            "secret_read": False,
            "writes": [],
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
