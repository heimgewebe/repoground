from __future__ import annotations

import json
from pathlib import Path

import pytest

from merger.repoground.core import mcp_resources
from merger.repoground.core.naming_audit import scan_repository

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/contracts/repoground-naming-hard-cut.v1.json"


def _former_product() -> str:
    return "repo" + "brief"


def test_contract_is_immediate_and_fail_closed() -> None:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert data["schema"] == "repoground.naming_hard_cut.v1"
    assert data["product"] == "RepoGround"
    assert data["policy"]["zero_usage_grace_period_days"] == 0
    assert data["policy"]["unknown_active_usage_blocks_closeout"] is True
    assert all(
        data["policy"][key] is False
        for key in (
            "active_command_aliases_allowed",
            "active_environment_aliases_allowed",
            "active_runtime_storage_aliases_allowed",
            "active_symbol_aliases_allowed",
        )
    )
    assert data["audit"]["schema"] == "repoground.naming_audit.v1"


def test_runtime_identity_is_canonical() -> None:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert data["canonical_runtime"] == {
        "repository": "heimgewebe/repoground",
        "python_namespace": "merger.repoground",
        "command": "repoground",
        "service_unit": "repoground.service",
        "mcp_resource_scheme": "repoground",
        "environment_prefix": "REPOGROUND_",
        "service_state_directory": ".repoground-service",
        "source_snapshot_directory": ".repoground-source-snapshots",
        "pythonista_state_file": ".repoground-state.json",
        "pr_workspace_directory": ".repoground/pr-schau",
        "generator_name": "repoground",
        "fleet_state_directory": "~/.local/state/repoground-publish/fleet",
        "fleet_log_directory": "~/logs/repoground-publish",
        "retention_quarantine_directory": ".repoground-prune-quarantine",
    }


def test_historical_runtime_archives_are_bounded_and_not_defaults() -> None:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    evidence = data["historical_evidence"]
    read_only = evidence["read_only_state_and_log_archives"]
    prune_only = evidence["explicit_prune_only_publication_archives"]

    assert evidence["runtime_archives_not_default_storage"] is True
    assert evidence["publication_archive_mutation_requires_explicit_prune"] is True
    assert "/home/alex/logs/repobrief-publish" in read_only
    assert "/home/alex/repos/merges/repobrief-auto" in prune_only
    assert "/home/alex/repos/manifest-publications/repobrief-auto" in prune_only


def test_versioned_data_ids_are_not_reinterpreted_as_aliases() -> None:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    policy = data["versioned_data_contracts"]
    assert policy["not_public_aliases"] is True
    assert policy["not_reinterpreted_by_branding"] is True
    assert policy["policy"].startswith("retained_exactly")


def test_project_mcp_configuration_is_canonical() -> None:
    data = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    assert data == {
        "mcpServers": {
            "repoground": {
                "command": "python3",
                "args": ["scripts/repoground-mcp-project.py"],
            }
        }
    }


def test_former_resource_scheme_is_rejected() -> None:
    uri = _former_product() + "://snapshot/demo/manifest"
    with pytest.raises(mcp_resources.RepoGroundMcpResourceError):
        mcp_resources.read_mcp_resource(uri, bundle_root=ROOT)


def test_active_repository_has_no_runtime_aliases() -> None:
    assert scan_repository(ROOT) == []



def test_protected_compatibility_contract_is_terminal_only() -> None:
    path = ROOT / "docs/contracts/repoground-compatibility-exit.v1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == "repoground.compatibility_exit.v1"
    assert data["status"] == "closed-hard-cut"
    assert data["successor_contract"] == "docs/contracts/repoground-naming-hard-cut.v1.json"
    assert data["runtime_authority"] is False
    assert data["active_aliases"] == []
    assert data["policy"]["zero_usage_window_days"] == 0
    assert data["policy"]["active_aliases_may_be_restored"] is False

def test_removed_entrypoint_files_are_absent() -> None:
    former = _former_product()
    removed = [
        ROOT / "scripts" / f"{former}-mcp-stdio.py",
        ROOT / "merger" / "repoground" / "cli" / f"cmd_{former}.py",
        ROOT / "merger" / ("lens" + "kit"),
    ]
    assert all(not path.exists() for path in removed)
