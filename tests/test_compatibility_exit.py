from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/contracts/repoground-compatibility-exit.v1.json"


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_compatibility_exit_contract_is_bounded_and_owned() -> None:
    data = _contract()

    assert data["schema"] == "repoground.compatibility_exit.v1"
    assert data["policy"]["unknown_usage_blocks_removal"] is True
    assert data["policy"]["zero_usage_window_days"] == 30
    assert data["inventory"]["schema"] == "repoground.compatibility_inventory.v1"
    assert data["inventory"]["privacy"] == {
        "raw_command_lines_included": False,
        "raw_config_contents_included": False,
    }
    surfaces = data["surfaces"]
    assert len({item["id"] for item in surfaces}) == len(surfaces)

    for surface in surfaces:
        assert surface["owner"].strip()
        assert surface["canonical"].strip()
        assert surface["removal_criteria"]
        assert all(item.strip() for item in surface["removal_criteria"])
        if surface["category"] != "persisted-data-contract":
            assert surface["review_by"]


def test_persisted_identity_is_not_treated_as_cosmetic_branding() -> None:
    surface = next(
        item for item in _contract()["surfaces"] if item["id"] == "persisted-legacy-identities"
    )

    assert surface["status"] == "retained-versioned-contract"
    assert surface["review_by"] is None
    criteria = " ".join(surface["removal_criteria"])
    assert "new versioned producer and schema" in criteria
    assert "semantics rather than branding" in criteria


def test_project_mcp_configuration_uses_only_canonical_entrypoints() -> None:
    data = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))

    assert set(data["mcpServers"]) == {"repoground"}
    server = data["mcpServers"]["repoground"]
    assert server == {
        "command": "python3",
        "args": ["scripts/repoground-mcp-project.py"],
    }
    serialized = json.dumps(data, sort_keys=True)
    assert "lenskit" not in serialized
    assert "repobrief" not in serialized
    assert "rlens" not in serialized


def test_project_mcp_launcher_uses_canonical_storage_and_checkout() -> None:
    text = (ROOT / "scripts/repoground-mcp-project.py").read_text(encoding="utf-8")

    assert "~/.local/share/repoground/bundles" in text
    assert '"--repo-root"' in text
    assert "REPOGROUND_BUNDLE_ROOT" in text
    assert "REPOGROUND_MCP_ENABLE_SNAPSHOT_CREATE" in text
    assert "lenskit" not in text
    assert "repobrief" not in text


def test_active_mcp_and_service_client_modules_are_canonical() -> None:
    main = (ROOT / "merger/repoground/cli/main.py").read_text(encoding="utf-8")
    mcp = (ROOT / "merger/repoground/cli/mcp_stdio.py").read_text(encoding="utf-8")

    assert "from .cmd_service_client import" in main
    assert "from .cmd_rlens_client import" not in main
    assert "from merger.repoground.core import mcp_resources, mcp_tools" in mcp
    assert "from merger.repoground.core import repobrief_mcp" not in mcp


def test_legacy_python_modules_are_small_identity_adapters() -> None:
    adapters = {
        "merger/repoground/cli/cmd_repobrief.py": "cmd_ground",
        "merger/repoground/cli/cmd_rlens_client.py": "cmd_service_client",
        "merger/repoground/core/repobrief_access.py": "bundle_access",
        "merger/repoground/core/repobrief_agent_impact_adapter.py": "agent_impact_adapter",
        "merger/repoground/core/repobrief_ask.py": "ask_context",
        "merger/repoground/core/repobrief_ask_eval.py": "ask_evaluation",
        "merger/repoground/core/repobrief_availability.py": "availability",
        "merger/repoground/core/repobrief_context_compiler.py": "context_compiler",
        "merger/repoground/core/repobrief_delta_context.py": "delta_context",
        "merger/repoground/core/repobrief_latest_complete.py": "latest_complete",
        "merger/repoground/core/repobrief_live_freshness.py": "live_freshness",
        "merger/repoground/core/repobrief_mcp_resources.py": "mcp_resources",
        "merger/repoground/core/repobrief_mcp_tools.py": "mcp_tools",
        "merger/repoground/core/repobrief_memory.py": "memory",
        "merger/repoground/core/repobrief_preflight.py": "snapshot_preflight",
        "merger/repoground/core/repobrief_profiles.py": "snapshot_profiles",
        "merger/repoground/core/repobrief_publication_policy.py": "publication_policy",
        "merger/repoground/core/repobrief_readonly_adapter.py": "readonly_adapter",
        "merger/repoground/core/repobrief_review_coverage.py": "review_coverage",
        "merger/repoground/core/repobrief_workbench_usefulness.py": "workbench_usefulness",
    }

    for relative, canonical in adapters.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 15
        assert "deprecated" in text.lower()
        assert canonical in text
        assert "sys.modules[__name__] = _module" in text
        assert "compatibility review:" in text


def test_current_service_template_has_no_legacy_unit_or_environment_path() -> None:
    text = (ROOT / "docs/systemd/repoground.service").read_text(encoding="utf-8")

    assert "REPOGROUND_SERVICE_UNIT=repoground" in text
    assert "%h/.config/repoground/env" in text
    assert "rlens" not in text.lower()
    assert not (ROOT / "docs/systemd/rlens.service").exists()


def test_current_mcp_documentation_prefers_canonical_resources() -> None:
    text = (ROOT / "docs/usage/repoground-mcp-stdio.md").read_text(encoding="utf-8")

    assert "repoground://snapshot/{stem}/manifest" in text
    assert "identity.legacy_prefix_used=true" in text
    assert "2026-10-01" in text
    assert "repoground-compatibility-exit.v1.json" in text
