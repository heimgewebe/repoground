import json
from pathlib import Path

from merger.repoground.core import repobrief_mcp_resources
from merger.repoground.core.readonly_adapter import (
    RepoBriefReadonlyAdapter,
    RepoGroundReadonlyAdapter,
)

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs/contracts/repobrief-readonly-adapter-compatibility.v1.json"


def test_compatibility_contract_binds_every_adapter_action() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    actions = contract["actions"]
    assert len(actions) == 9
    assert len({item["action"] for item in actions}) == len(actions)
    for item in actions:
        assert item["action"] == item["library_method"]
        assert callable(getattr(RepoGroundReadonlyAdapter, item["library_method"]))
        assert item["parity_class"] in {
            "analogous_inventory_only",
            "shared_access_semantics",
            "not_bound",
            "role_bounded_analogous_read",
        }


def test_contract_names_real_mcp_analogues_without_claiming_server_parity() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert callable(repobrief_mcp_resources.list_mcp_resources)
    assert callable(repobrief_mcp_resources.read_mcp_resource)
    assert any("not an MCP protocol server" in item for item in contract["non_parity"])
    assert any(item["mcp_surface"] is None for item in contract["actions"])


def test_legacy_readonly_class_alias_is_identical() -> None:
    assert RepoBriefReadonlyAdapter is RepoGroundReadonlyAdapter
