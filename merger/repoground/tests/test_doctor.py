from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from merger.repoground.cli import cmd_doctor
from merger.repoground.cli.main import main
from merger.repoground.core import doctor


def _by_id(checks: list[dict], check_id: str) -> dict:
    return next(check for check in checks if check["id"] == check_id)


def _available(check_id: str, *, optional: bool = False) -> dict:
    return doctor._check(
        check_id,
        "available",
        cause="fixture_available",
        impact="fixture",
        next_action="No action required.",
        optional=optional,
    )


def test_python_runtime_distinguishes_core_support_from_release_baseline(monkeypatch) -> None:
    monkeypatch.setattr(doctor.sys, "version_info", (3, 10, 12))

    check = doctor.check_python_runtime()

    assert check["status"] == "available"
    assert check["cause"] == "python_version_outside_ci_release_baseline"
    assert check["evidence"]["core_minimum"] == "3.10"
    assert check["evidence"]["core_runtime_supported"] is True
    assert check["evidence"]["ci_release_baseline"] == "3.12"
    assert check["evidence"]["ci_release_baseline_matches"] is False
    assert check["evidence"]["ci_release_baseline_role"] == "reproducible_validation"
    assert "ci_release_equivalence" in check["does_not_establish"]


def test_python_runtime_below_core_minimum_is_blocked(monkeypatch) -> None:
    monkeypatch.setattr(doctor.sys, "version_info", (3, 9, 19))

    check = doctor.check_python_runtime()

    assert check["status"] == "blocked"
    assert check["cause"] == "python_version_too_old"
    assert check["evidence"]["core_runtime_supported"] is False
    assert check["evidence"]["ci_release_baseline_matches"] is False


def test_python_runtime_ci_release_baseline_match_stays_available(monkeypatch) -> None:
    monkeypatch.setattr(doctor.sys, "version_info", (3, 12, 4))

    check = doctor.check_python_runtime()

    assert check["status"] == "available"
    assert check["cause"] == "python_ci_release_baseline_matches"
    assert check["evidence"]["core_runtime_supported"] is True
    assert check["evidence"]["ci_release_baseline"] == "3.12"
    assert check["evidence"]["ci_release_baseline_matches"] is True


def _wrapper_fixture(tmp_path: Path, *, installed: str, canonical: str) -> tuple[Path, Path]:
    source = tmp_path / "scripts" / "ops" / "repoground-cli-wrapper"
    source.parent.mkdir(parents=True)
    source.write_text(canonical, encoding="utf-8")
    source.chmod(0o755)
    wrapper = tmp_path / "bin" / "repoground"
    wrapper.parent.mkdir()
    wrapper.write_text(installed, encoding="utf-8")
    wrapper.chmod(0o755)
    return source, wrapper


def test_missing_wrapper_is_optional_degradation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)

    check = doctor.check_wrapper(tmp_path)

    assert check["status"] == "degraded"
    assert check["cause"] == "repoground_wrapper_not_on_path"
    assert check["optional"] is True


def test_canonical_wrapper_delegate_is_available(monkeypatch, tmp_path: Path) -> None:
    canonical = "#!/usr/bin/env bash\nexec python3 -m repoground \"$@\"\n"
    source, wrapper = _wrapper_fixture(
        tmp_path, installed=canonical, canonical=canonical
    )
    monkeypatch.setattr(doctor, "_canonical_wrapper_source", lambda: source)
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: str(wrapper))

    check = doctor.check_wrapper(tmp_path)

    assert check["status"] == "available"
    assert check["cause"] == "repoground_wrapper_canonical_delegate"
    assert check["evidence"]["installed_sha256"] == check["evidence"]["canonical_sha256"]


def test_historical_service_browser_wrapper_is_degraded(monkeypatch, tmp_path: Path) -> None:
    canonical = "#!/usr/bin/env bash\nexec python3 -m repoground \"$@\"\n"
    historical = (
        "#!/usr/bin/env bash\n"
        "systemctl --user start repoground.service\n"
        "curl -fsS http://127.0.0.1:8787/api/health\n"
        "xdg-open http://127.0.0.1:8787\n"
    )
    source, wrapper = _wrapper_fixture(
        tmp_path, installed=historical, canonical=canonical
    )
    monkeypatch.setattr(doctor, "_canonical_wrapper_source", lambda: source)
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: str(wrapper))

    check = doctor.check_wrapper(tmp_path)

    assert check["status"] == "degraded"
    assert check["cause"] == "repoground_wrapper_historical_service_launcher"
    assert "repoground.service" in check["evidence"]["historical_markers"]


def test_foreign_executable_named_repoground_is_degraded(monkeypatch, tmp_path: Path) -> None:
    canonical = "#!/usr/bin/env bash\nexec python3 -m repoground \"$@\"\n"
    source, wrapper = _wrapper_fixture(
        tmp_path,
        installed="#!/usr/bin/env bash\necho foreign-tool\n",
        canonical=canonical,
    )
    monkeypatch.setattr(doctor, "_canonical_wrapper_source", lambda: source)
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: str(wrapper))

    check = doctor.check_wrapper(tmp_path)

    assert check["status"] == "degraded"
    assert check["cause"] == "repoground_wrapper_identity_mismatch"
    assert check["evidence"]["installed_sha256"] != check["evidence"]["canonical_sha256"]


def test_wrapper_identity_uses_running_source_not_inspected_repo(monkeypatch, tmp_path: Path) -> None:
    canonical = "#!/usr/bin/env bash\nexec python3 -m repoground \"$@\"\n"
    source_root = tmp_path / "repoground-source"
    source, wrapper = _wrapper_fixture(
        source_root, installed=canonical, canonical=canonical
    )
    inspected = tmp_path / "application-repo"
    inspected.mkdir()
    monkeypatch.setattr(doctor, "_canonical_wrapper_source", lambda: source)
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: str(wrapper))

    check = doctor.check_wrapper(inspected)

    assert check["status"] == "available"
    assert check["evidence"]["canonical_source"] == str(source)
    assert str(inspected) not in check["evidence"]["canonical_source"]


def test_tracked_wrapper_does_not_import_repoground_from_cwd(tmp_path: Path) -> None:
    source_root = tmp_path / "canonical"
    package = source_root / "repoground"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text(
        "import json, os\n"
        "def main(argv=None):\n"
        "    print(json.dumps({'marker': 'canonical', 'cwd': os.getcwd(), 'args': list(argv or [])}))\n"
        "    return 0\n",
        encoding="utf-8",
    )
    hostile_cwd = tmp_path / "hostile"
    hostile_package = hostile_cwd / "repoground"
    hostile_package.mkdir(parents=True)
    marker = tmp_path / "shadowed.txt"
    (hostile_package / "__init__.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('shadowed', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (hostile_package / "cli.py").write_text(
        "def main(argv=None):\n    print('hostile')\n    return 0\n",
        encoding="utf-8",
    )
    wrapper = Path(__file__).resolve().parents[3] / "scripts" / "ops" / "repoground-cli-wrapper"
    env = os.environ.copy()
    env.update({"REPOGROUND_ROOT": str(source_root), "REPOGROUND_PYTHON": sys.executable})

    completed = subprocess.run(
        [str(wrapper), "probe"],
        cwd=hostile_cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload == {"marker": "canonical", "cwd": str(hostile_cwd), "args": ["probe"]}
    assert not marker.exists()


def test_missing_jsonschema_is_degraded_without_core_block(monkeypatch) -> None:
    monkeypatch.setattr(
        doctor,
        "_module_available",
        lambda module: False if module == "jsonschema" else True,
    )

    check = doctor.check_jsonschema_dependency()

    assert check["status"] == "degraded"
    assert check["cause"] == "jsonschema_dependency_missing"
    assert check["optional"] is False
    assert "will not install" in check["next_action"]


def test_broken_fts_blocks_lexical_retrieval_without_file_write() -> None:
    def broken_connect(_database: str):
        raise sqlite3.OperationalError("no such module: fts5")

    check = doctor.check_sqlite_fts(connect=broken_connect)

    assert check["status"] == "blocked"
    assert check["cause"] == "sqlite_fts5_unavailable"
    assert check["evidence"]["error_type"] == "OperationalError"
    assert "will not modify SQLite" in check["next_action"]


def test_ambiguous_bundle_catalog_fails_closed(monkeypatch, tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundles"
    bundle_root.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr(doctor, "checkout_repo_identity", lambda _root: "heimgewebe/demo")
    monkeypatch.setattr(
        doctor,
        "select_bundle_manifest",
        lambda *_args, **_kwargs: {
            "status": "ambiguous",
            "reason": "newest_bundle_identity_ambiguous",
            "selected": None,
        },
    )

    checks = doctor._bundle_checks(
        repo_root,
        bundle_root=bundle_root,
        manifest=None,
    )

    catalog = _by_id(checks, "bundle_catalog")
    assert catalog["status"] == "blocked"
    assert catalog["cause"] == "newest_bundle_identity_ambiguous"
    assert _by_id(checks, "manifest_integrity")["status"] == "degraded"
    assert _by_id(checks, "freshness")["status"] == "degraded"


def test_stale_bundle_is_visible_degradation(monkeypatch, tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundles"
    bundle_root.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    manifest = bundle_root / "demo.bundle.manifest.json"
    monkeypatch.setattr(doctor, "checkout_repo_identity", lambda _root: "heimgewebe/demo")
    monkeypatch.setattr(
        doctor,
        "select_bundle_manifest",
        lambda *_args, **_kwargs: {
            "status": "available",
            "selected": {
                "manifest_path": str(manifest),
                "manifest_sha256": "a" * 64,
            },
        },
    )
    monkeypatch.setattr(
        doctor,
        "inspect_bundle_health",
        lambda _manifest: {
            "status": "available",
            "health_status": "pass",
            "manifest_sha256": "a" * 64,
            "reasons": [],
        },
    )
    monkeypatch.setattr(
        doctor,
        "evaluate_live_freshness",
        lambda *_args, **_kwargs: {
            "status": "stale",
            "reason": "git_head_mismatch",
            "snapshot_provenance": {"git_commit": "a" * 40},
            "current_provenance": {"git_commit": "b" * 40},
        },
    )

    checks = doctor._bundle_checks(
        repo_root,
        bundle_root=bundle_root,
        manifest=None,
    )

    assert _by_id(checks, "bundle_catalog")["status"] == "available"
    assert _by_id(checks, "manifest_integrity")["status"] == "available"
    freshness = _by_id(checks, "freshness")
    assert freshness["status"] == "degraded"
    assert freshness["cause"] == "git_head_mismatch"
    assert "outside doctor" in freshness["next_action"]


def test_missing_mcp_starter_degrades_only_mcp(monkeypatch, tmp_path: Path) -> None:
    config = tmp_path / ".mcp.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "repoground": {
                        "command": "python3",
                        "args": ["scripts/repoground-mcp-project.py"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(doctor, "_regular_file", lambda _path: (False, "FileNotFoundError"))

    check = doctor.check_mcp_configuration(tmp_path)

    assert check["status"] == "degraded"
    assert check["cause"] == "mcp_project_starter_unavailable"
    assert "core_cli_failure" in check["does_not_establish"]


def test_explicit_mcp_config_symlink_is_rejected(tmp_path: Path) -> None:
    starter = tmp_path / "scripts" / "repoground-mcp-project.py"
    starter.parent.mkdir()
    starter.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    target = tmp_path / "real-mcp.json"
    target.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "repoground": {
                        "command": "python3",
                        "args": ["scripts/repoground-mcp-project.py"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    link = tmp_path / "mcp-link.json"
    link.symlink_to(target.name)

    check = doctor.check_mcp_configuration(tmp_path, config_path=link)

    assert check["status"] == "degraded"
    assert check["cause"] == "mcp_project_configuration_invalid"
    assert "symbolic" in check["evidence"]["error"].lower() or "symlink" in check["evidence"]["error"].lower()


def test_mcp_config_is_bound_to_existing_project_starter(tmp_path: Path) -> None:
    starter = tmp_path / "scripts" / "repoground-mcp-project.py"
    starter.parent.mkdir()
    starter.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    config = tmp_path / ".mcp.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "repoground": {
                        "command": "python3",
                        "args": ["scripts/repoground-mcp-project.py"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    check = doctor.check_mcp_configuration(tmp_path)

    assert check["status"] == "available"
    assert check["evidence"]["starter_argument"] == "scripts/repoground-mcp-project.py"


def test_optional_language_adapters_do_not_block_python_core(monkeypatch) -> None:
    available = {
        "merger.repoground.core.call_graph_navigation",
        "merger.repoground.core.scip_adapter",
    }
    monkeypatch.setattr(doctor, "_module_available", lambda module: module in available)

    checks = doctor.check_optional_adapters()

    assert _by_id(checks, "adapter:python_call_graph")["status"] == "available"
    assert _by_id(checks, "adapter:scip_graph")["status"] == "available"
    assert _by_id(checks, "adapter:rust_structure")["status"] == "degraded"
    assert _by_id(checks, "adapter:bash_structure")["status"] == "degraded"
    assert all(check["optional"] is True for check in checks)
    assert doctor._overall_status(checks) == "available"


def test_doctor_summary_ignores_optional_degradation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doctor, "check_python_runtime", lambda: _available("python"))
    monkeypatch.setattr(doctor, "check_git_runtime", lambda: _available("git"))
    monkeypatch.setattr(doctor, "check_sqlite_fts", lambda: _available("sqlite_fts"))
    monkeypatch.setattr(
        doctor, "check_jsonschema_dependency", lambda: _available("jsonschema")
    )
    monkeypatch.setattr(
        doctor,
        "check_mcp_configuration",
        lambda *_args, **_kwargs: _available("mcp_configuration"),
    )
    monkeypatch.setattr(
        doctor,
        "check_wrapper",
        lambda: doctor._check(
            "wrapper",
            "degraded",
            cause="fixture_optional_missing",
            impact="fixture",
            next_action="fixture",
            optional=True,
        ),
    )
    monkeypatch.setattr(
        doctor,
        "check_optional_adapters",
        lambda: [
            doctor._check(
                "adapter:rust_structure",
                "degraded",
                cause="fixture_optional_missing",
                impact="fixture",
                next_action="fixture",
                optional=True,
            )
        ],
    )
    monkeypatch.setattr(
        doctor,
        "_bundle_checks",
        lambda *_args, **_kwargs: [
            _available("bundle_catalog"),
            _available("manifest_integrity"),
            _available("freshness"),
        ],
    )

    report = doctor.build_doctor_report(repo_root=tmp_path)

    assert report["status"] == "available"
    assert report["summary"]["optional"]["degraded"] == 2
    assert report["summary"]["optional_degradation_affects_core_status"] is False
    assert report["mutation_boundary"] == {
        "read_only": True,
        "network_sync": False,
        "package_install": False,
        "bundle_refresh": False,
        "git_mutation": False,
        "service_mutation": False,
        "secret_read": False,
        "writes": [],
    }


def test_doctor_cli_json_and_exit_codes(monkeypatch, capsys) -> None:
    blocked_report = {
        "kind": "repoground.doctor",
        "version": "1.0",
        "status": "blocked",
        "checks": [],
        "mutation_boundary": {"read_only": True, "writes": []},
    }
    monkeypatch.setattr(cmd_doctor, "build_doctor_report", lambda **_kwargs: blocked_report)

    assert main(["doctor", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"

    degraded_report = {**blocked_report, "status": "degraded"}
    monkeypatch.setattr(cmd_doctor, "build_doctor_report", lambda **_kwargs: degraded_report)
    assert main(["doctor"]) == 0
    capsys.readouterr()
    assert main(["doctor", "--strict"]) == 1
    human = capsys.readouterr().out
    assert "RepoGround doctor: degraded" in human
    assert "Read-only:" in human
