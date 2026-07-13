import json
from io import StringIO
from pathlib import Path

import pytest

from merger.lenskit.cli.repobrief_mcp_stdio import (
    PROTOCOL_VERSION,
    RepoBriefMcpStdioServer,
    serve_stdio,
)
from merger.lenskit.core import repobrief_mcp_resources, repobrief_mcp_tools


def _manifest(tmp_path: Path) -> Path:
    path = tmp_path / "demo.bundle.manifest.json"
    path.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "run_id": "demo",
                "artifacts": [],
                "snapshot_provenance": {"version": "v1", "repositories": []},
            }
        ),
        encoding="utf-8",
    )
    return path


def _initialize(server: RepoBriefMcpStdioServer):
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
    )
    assert response is not None
    return response


def _tools(server: RepoBriefMcpStdioServer) -> list[dict]:
    response = server.handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    )
    return response["result"]["tools"]


def test_mcp_stdio_requires_initialization(tmp_path):
    server = RepoBriefMcpStdioServer(bundle_root=tmp_path)

    response = server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )

    assert response["error"]["code"] == -32002


def test_initialized_notification_does_not_replace_initialize(tmp_path):
    server = RepoBriefMcpStdioServer(bundle_root=tmp_path)

    notification = server.handle_message(
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    )
    response = server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )

    assert notification is None
    assert response["error"]["code"] == -32002


def test_mcp_stdio_lists_read_tools_and_hides_snapshot_create_by_default(tmp_path):
    server = RepoBriefMcpStdioServer(bundle_root=tmp_path)
    initialized = _initialize(server)

    assert initialized["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert initialized["result"]["capabilities"]["tools"]["listChanged"] is False
    assert {tool["name"] for tool in _tools(server)} == {
        "ask_context",
        "grounding_verify",
        "live_freshness",
    }


def test_snapshot_create_enable_requires_explicit_repo_root(tmp_path):
    with pytest.raises(ValueError, match="requires an explicit --repo-root"):
        RepoBriefMcpStdioServer(
            bundle_root=tmp_path,
            enable_snapshot_create=True,
        )


def test_mcp_stdio_exposes_startup_bound_snapshot_create_schema(tmp_path):
    repo = tmp_path / "repo"
    bundles = tmp_path / "bundles"
    repo.mkdir()
    bundles.mkdir()
    server = RepoBriefMcpStdioServer(
        bundle_root=bundles,
        repo_root=repo,
        enable_snapshot_create=True,
    )
    _initialize(server)

    definition = next(tool for tool in _tools(server) if tool["name"] == "snapshot_create")
    properties = definition["inputSchema"]["properties"]

    assert definition["inputSchema"]["required"] == ["profile"]
    assert "repo" not in properties
    assert "output_root" not in properties


def test_snapshot_create_injects_startup_roots_and_rejects_overrides(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    bundles = tmp_path / "bundles"
    repo.mkdir()
    bundles.mkdir()
    server = RepoBriefMcpStdioServer(
        bundle_root=bundles,
        repo_root=repo,
        enable_snapshot_create=True,
    )
    _initialize(server)
    seen = {}

    def fake_snapshot_create(**arguments):
        seen.update(arguments)
        return {"status": "ok"}

    monkeypatch.setattr(repobrief_mcp_tools, "snapshot_create", fake_snapshot_create)
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "snapshot_create",
                "arguments": {"profile": "agent-review", "output_subdir": "demo"},
            },
        }
    )

    assert response["result"]["isError"] is False
    assert seen["repo"] == str(repo.resolve())
    assert seen["output_root"] == str(bundles.resolve())
    assert seen["profile"] == "agent-review"

    rejected = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "snapshot_create",
                "arguments": {
                    "profile": "agent-review",
                    "repo": str(tmp_path / "other"),
                    "output_root": str(tmp_path / "outside"),
                },
            },
        }
    )

    assert rejected["error"]["code"] == -32602
    assert rejected["error"]["data"]["forbidden_arguments"] == ["output_root", "repo"]


def test_mcp_stdio_tool_call_is_bundle_root_bound(tmp_path):
    manifest = _manifest(tmp_path)
    outside = tmp_path.parent / "outside.bundle.manifest.json"
    outside.write_text(manifest.read_text(encoding="utf-8"), encoding="utf-8")
    server = RepoBriefMcpStdioServer(bundle_root=tmp_path)
    _initialize(server)

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "ask_context",
                "arguments": {"bundle_manifest": str(outside), "query": "hello"},
            },
        }
    )

    assert response["error"]["code"] == -32602
    assert "outside the configured bundle root" in response["error"]["message"]


def test_mcp_stdio_calls_existing_ask_handler_and_adds_freshness(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path)
    server = RepoBriefMcpStdioServer(bundle_root=tmp_path)
    _initialize(server)
    seen = {}

    def fake_ask_context(**arguments):
        seen.update(arguments)
        return {"kind": "repobrief.mcp.read_only_frontdoor", "status": "ok"}

    monkeypatch.setattr(repobrief_mcp_tools, "ask_context", fake_ask_context)
    monkeypatch.setattr(
        server,
        "_safe_live_freshness",
        lambda *_args, **_kwargs: {"status": "fresh", "implicit_refresh": False},
    )

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "ask_context",
                "arguments": {"bundle_manifest": str(manifest), "query": "hello"},
            },
        }
    )

    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["live_freshness"]["status"] == "fresh"
    assert seen["bundle_manifest"] == str(manifest.resolve())


def test_mcp_stdio_resource_read_preserves_content_and_adds_metadata(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path)
    server = RepoBriefMcpStdioServer(bundle_root=tmp_path, repo_root=tmp_path)
    _initialize(server)
    uri = "repobrief://snapshot/demo/canonical"

    monkeypatch.setattr(
        repobrief_mcp_resources,
        "read_mcp_resource",
        lambda *_args, **_kwargs: {
            "status": "available",
            "bundle_manifest": str(manifest),
            "content_type": "text/markdown",
            "content_text": "# Demo\n",
            "snapshot_context": {"freshness": {"status": "not_comparable"}},
        },
    )
    monkeypatch.setattr(
        server,
        "_safe_live_freshness",
        lambda *_args, **_kwargs: {"status": "stale", "implicit_refresh": False},
    )

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": uri},
        }
    )

    result = response["result"]
    assert result["contents"] == [
        {"uri": uri, "mimeType": "text/markdown", "text": "# Demo\n"}
    ]
    assert result["_meta"]["repobrief"]["liveFreshness"]["status"] == "stale"
    assert result["_meta"]["repobrief"]["implicitRefresh"] is False


def test_mcp_stdio_without_configured_repo_reports_not_comparable(tmp_path):
    manifest = _manifest(tmp_path)
    server = RepoBriefMcpStdioServer(bundle_root=tmp_path)
    _initialize(server)

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "live_freshness",
                "arguments": {"bundle_manifest": str(manifest)},
            },
        }
    )

    freshness = response["result"]["structuredContent"]
    assert freshness["status"] == "not_comparable"
    assert freshness["reason"] == "repo_root_not_configured"
    assert freshness["read_only_git_probe"] is False


def test_serve_stdio_uses_one_json_object_per_line(tmp_path):
    server = RepoBriefMcpStdioServer(bundle_root=tmp_path)
    source = StringIO(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": PROTOCOL_VERSION},
            }
        )
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}})
        + "\n"
    )
    target = StringIO()

    assert serve_stdio(server, source, target) == 0

    lines = target.getvalue().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["id"] for line in lines] == [1, 2]


def test_serve_stdio_returns_parse_error_without_traceback(tmp_path):
    server = RepoBriefMcpStdioServer(bundle_root=tmp_path)
    target = StringIO()

    serve_stdio(server, StringIO("{bad json\n"), target)

    response = json.loads(target.getvalue())
    assert response["error"] == {"code": -32700, "message": "parse error"}
