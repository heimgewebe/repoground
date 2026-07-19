from __future__ import annotations

import json
import subprocess
from pathlib import Path

from merger.repoground.core.naming_audit import (
    build_audit,
    dumps_audit,
    scan_configs,
    scan_processes,
    scan_repository,
)


def _former_product() -> str:
    return "repo" + "brief"


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)


def test_process_audit_redacts_raw_argv(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    process = proc / "123"
    process.mkdir(parents=True)
    raw = f"python3\0{_former_product()}-mcp.py\0".encode()
    (process / "cmdline").write_bytes(raw)

    findings = scan_processes(proc)

    assert len(findings) == 1
    assert findings[0]["pid"] == 123
    assert _former_product() in findings[0]["matched_names"]
    assert "argv_sha256" in findings[0]
    assert _former_product() + "-mcp.py" not in json.dumps(findings)


def test_config_audit_is_hash_only(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"command": _former_product()}), encoding="utf-8")

    finding = scan_configs([config])[0]

    assert finding["status"] == "scanned"
    assert _former_product() in finding["matched_names"]
    assert "sha256" in finding
    assert "command" not in finding


def test_repository_audit_detects_runtime_alias_but_not_versioned_kind(tmp_path: Path) -> None:
    source = tmp_path / "merger" / "repoground" / "core"
    source.mkdir(parents=True)
    old_env = ("lens" + "kit_repo" + "brief_cache_validation").upper()
    (source / "runtime.py").write_text(f'ENV = "{old_env}"\n', encoding="utf-8")
    (source / "contract.py").write_text(
        f'KIND = "{_former_product()}.snapshot_status"\n', encoding="utf-8"
    )
    _init_repo(tmp_path)

    assert scan_repository(tmp_path) == [
        {
            "path": "merger/repoground/core/runtime.py",
            "matched_aliases": ["former-cache-environment"],
        }
    ]


def test_audit_can_skip_services(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    proc.mkdir()
    audit = build_audit(proc_root=proc, include_services=False)
    assert audit["schema"] == "repoground.naming_audit.v1"
    assert audit["active_aliases_zero"] is True
    assert audit["service_states"] == []
    assert json.loads(dumps_audit(audit))["schema"] == audit["schema"]


def test_current_repository_has_no_active_aliases() -> None:
    root = Path(__file__).resolve().parents[3]
    audit = build_audit(repo_root=root, include_services=False)
    assert audit["repository_alias_findings"] == []
    assert audit["active_aliases_zero"] is True
