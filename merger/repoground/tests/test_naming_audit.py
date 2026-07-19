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


def _former_mcp_script() -> str:
    return _former_product() + "-mcp-stdio.py"


def _former_resource_uri() -> str:
    return _former_product() + "://snapshot/demo/manifest"


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)


def _write_process(proc: Path, pid: int, *argv: str) -> None:
    process = proc / str(pid)
    process.mkdir(parents=True)
    (process / "cmdline").write_bytes(
        b"\0".join(argument.encode() for argument in argv) + b"\0"
    )


def test_process_audit_redacts_concrete_command_alias(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    _write_process(proc, 123, "python3", f"/opt/bin/{_former_mcp_script()}")

    findings = scan_processes(proc)

    assert findings == [
        {
            "pid": 123,
            "executable": "python3",
            "matched_aliases": ["former-command-alias"],
            "matched_names": [_former_product()],
            "argv_sha256": findings[0]["argv_sha256"],
        }
    ]
    serialized = json.dumps(findings)
    assert _former_mcp_script() not in serialized


def test_process_audit_detects_former_executable_basename(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    _write_process(proc, 123, f"/opt/bin/{_former_product()}")

    assert scan_processes(proc)[0]["matched_aliases"] == [
        "former-command-alias"
    ]


def test_process_audit_ignores_prompt_only_name_mentions(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    prompt = (
        "Review the old RepoBrief and rLens naming history, but do not execute "
        "any compatibility command."
    )
    _write_process(proc, 123, "claude", "--prompt", prompt)

    assert scan_processes(proc) == []


def test_process_audit_ignores_prompt_flag_with_uri_only_value(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    _write_process(proc, 123, "claude", "--prompt", _former_resource_uri())

    assert scan_processes(proc) == []


def test_non_agent_text_argument_with_alias_is_still_scanned(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    _write_process(
        proc,
        123,
        "custom-tool",
        "--script",
        "load " + _former_resource_uri(),
    )

    finding = scan_processes(proc)[0]

    assert finding["matched_aliases"] == ["former-resource-scheme"]


def test_non_agent_short_p_does_not_hide_an_alias_value(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    _write_process(proc, 123, "custom-tool", "-p", _former_resource_uri())

    finding = scan_processes(proc)[0]

    assert finding["matched_aliases"] == ["former-resource-scheme"]
    assert finding["matched_names"] == [_former_product()]


def test_python_wrapped_agent_prompt_is_ignored(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    _write_process(
        proc,
        123,
        "python3",
        "/opt/agents/claude.py",
        "--prompt",
        _former_resource_uri(),
    )

    assert scan_processes(proc) == []


def test_process_audit_detects_standalone_uri_env_and_storage_tokens(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    old_env = ("r" + "lens_token").upper() + "=redacted"
    old_store = "/home/alex/repos/merges/." + "r" + "lens-service"
    _write_process(
        proc,
        123,
        "python3",
        _former_resource_uri(),
        old_env,
        old_store,
    )

    findings = scan_processes(proc)

    assert findings[0]["matched_aliases"] == [
        "former-environment",
        "former-resource-scheme",
        "former-runtime-storage",
    ]


def test_process_audit_detects_former_fleet_env_and_storage(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    old_env = ("r" + "b_state_root").upper() + "=/tmp/state"
    old_state = "/home/alex/.local/state/" + "repobrief-publish/fleet"
    old_log = "/home/alex/logs/" + "repobrief-publish"
    old_quarantine = "." + "rb-prune-quarantine"
    _write_process(
        proc,
        123,
        "python3",
        old_env,
        old_state,
        old_log,
        old_quarantine,
    )

    finding = scan_processes(proc)[0]

    assert finding["matched_aliases"] == [
        "former-environment",
        "former-runtime-storage",
    ]


def test_config_audit_is_hash_only_for_concrete_aliases(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"uri": _former_resource_uri()}),
        encoding="utf-8",
    )

    finding = scan_configs([config])[0]

    assert finding["status"] == "scanned"
    assert finding["matched_aliases"] == ["former-resource-scheme"]
    assert finding["matched_names"] == [_former_product()]
    assert "sha256" in finding
    assert "uri" not in finding


def test_config_audit_detects_exact_command_and_args_fields(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    old_store = "/home/alex/repos/merges/." + "r" + "lens-service"
    config.write_text(
        json.dumps({"command": _former_product(), "args": [old_store]}),
        encoding="utf-8",
    )

    finding = scan_configs([config])[0]

    assert finding["matched_aliases"] == [
        "former-command-alias",
        "former-runtime-storage",
    ]
    assert finding["matched_names"] == [_former_product(), "rlens"]


def test_config_audit_ignores_aliases_in_nonsemantic_lists(tmp_path: Path) -> None:
    config = tmp_path / "notes.json"
    config.write_text(
        json.dumps({"notes": [_former_resource_uri(), _former_mcp_script()]}),
        encoding="utf-8",
    )

    finding = scan_configs([config])[0]

    assert finding["matched_aliases"] == []
    assert finding["matched_names"] == []


def test_config_audit_ignores_explanatory_name_mentions(tmp_path: Path) -> None:
    config = tmp_path / "notes.json"
    config.write_text(
        json.dumps(
            {
                "description": (
                    "Migration history mentions RepoBrief, rLens, "
                    + _former_resource_uri()
                    + " and "
                    + _former_mcp_script()
                )
            }
        ),
        encoding="utf-8",
    )

    finding = scan_configs([config])[0]

    assert finding["status"] == "scanned"
    assert finding["matched_aliases"] == []
    assert finding["matched_names"] == []


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
