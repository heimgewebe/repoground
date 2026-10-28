"""MCP discoverability, true JSON-RPC handoff, selector and read-only regression."""
from merger.repoground.cli.mcp_stdio import PROTOCOL_VERSION, RepoGroundMcpStdioServer
from merger.repoground.tests.test_agent_evidence_pack import (
    git, manifest, seeded_repo,
)


def rpc(server, number, method, params=None):
    return server.handle_message({
        "jsonrpc": "2.0", "id": number, "method": method,
        "params": params or {},
    })


def test_mcp_discovery_opt_in_and_real_bounded_tool_call(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    bundle = manifest(tmp_path, base)
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path, repo_root=repo)
    rpc(server, 1, "initialize", {"protocolVersion": PROTOCOL_VERSION})
    advertised = rpc(server, 2, "tools/list")["result"]["tools"]
    tool = next(t for t in advertised if t["name"] == "change_evidence_pack")
    assert tool["annotations"]["readOnlyHint"] is True
    assert tool["annotations"]["destructiveHint"] is False
    assert set(tool["inputSchema"]["required"]) == {"base_revision", "target_revision"}
    args = {
        "name": "change_evidence_pack",
        "arguments": {
            "bundle_manifest": str(bundle),
            "base_revision": base,
            "target_revision": head,
            "use_case": "explain-change",
        },
    }
    first = rpc(server, 3, "tools/call", args)["result"]
    second = rpc(server, 4, "tools/call", args)["result"]
    assert first["isError"] is False
    pack = first["structuredContent"]
    assert pack["kind"] == "repoground.agent_change_evidence"
    assert pack["revision"]["base"] == base
    assert pack["revision"]["target"] == head
    assert pack["response_sha256"] == second["structuredContent"]["response_sha256"]
    assert pack["mutation_boundary"]["writes"] == []
    assert git(repo, "status", "--porcelain") == ""


def test_mcp_tools_hidden_without_git_checkout(tmp_path):
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)
    rpc(server, 1, "initialize", {"protocolVersion": PROTOCOL_VERSION})
    advertised = rpc(server, 2, "tools/list")["result"]["tools"]
    assert "change_evidence_pack" not in {t["name"] for t in advertised}


def test_mcp_manifest_boundary_and_invalid_revision(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    bundle = manifest(tmp_path, base)
    root = tmp_path / "allowed"
    root.mkdir()
    safe = manifest(root, base)
    server = RepoGroundMcpStdioServer(bundle_root=root, repo_root=repo)
    rpc(server, 1, "initialize", {"protocolVersion": PROTOCOL_VERSION})
    outside = rpc(server, 2, "tools/call", {
        "name": "change_evidence_pack",
        "arguments": {
            "bundle_manifest": str(bundle),
            "base_revision": base, "target_revision": head,
        },
    })
    assert outside["error"]["code"] == -32602
    invalid = rpc(server, 3, "tools/call", {
        "name": "change_evidence_pack",
        "arguments": {
            "bundle_manifest": str(safe),
            "base_revision": "--exec", "target_revision": head,
        },
    })
    assert invalid["result"]["structuredContent"]["status"] == "invalid"


def test_mcp_no_healthy_bundle_still_reports_exact_git_diff(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    empty = tmp_path / "no-publications"
    empty.mkdir()
    server = RepoGroundMcpStdioServer(bundle_root=empty, repo_root=repo)
    rpc(server, 1, "initialize", {"protocolVersion": PROTOCOL_VERSION})
    call = rpc(server, 2, "tools/call", {
        "name": "change_evidence_pack",
        "arguments": {"repo": "heimgewebe/demorepo",
                      "base_revision": base, "target_revision": head,
                      "use_case": "find-related-tests"},
    })
    assert call["result"]["isError"] is False
    pack = call["result"]["structuredContent"]
    assert pack["status"] == "warn"
    assert pack["bundle"]["status"] == "unavailable"
    assert pack["revision"]["target"] == head
    assert pack["changed_files"][0]["path"] == "alpha.py"
    assert pack["live_freshness"]["status"] == "not_comparable"
    assert pack["live_freshness"]["implicit_refresh"] is False
    assert not list(empty.iterdir())
    assert git(repo, "status", "--porcelain") == ""
