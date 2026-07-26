import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from merger.repoground.cli.mcp_stdio import (
    PROTOCOL_VERSION,
    RepoGroundMcpStdioServer,
    serve_stdio,
)
from merger.repoground.core import mcp_resources, mcp_tools


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


def _initialize(server: RepoGroundMcpStdioServer):
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


def _tools(server: RepoGroundMcpStdioServer) -> list[dict]:
    response = server.handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    )
    return response["result"]["tools"]


def test_mcp_stdio_handshake_defers_handler_modules():
    root = Path(__file__).resolve().parents[3]
    probe = """
import json
import sys
import tempfile

from merger.repoground.cli.mcp_stdio import PROTOCOL_VERSION, RepoGroundMcpStdioServer

with tempfile.TemporaryDirectory() as bundle_root:
    server = RepoGroundMcpStdioServer(bundle_root=bundle_root)
    server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION},
        }
    )
    server.handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    )

names = (
    "merger.repoground.core.mcp_resources",
    "merger.repoground.core.mcp_tools",
)
print(json.dumps([name for name in names if name in sys.modules]))
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == []


def test_canonical_mcp_server_identity(tmp_path):
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)
    initialized = _initialize(server)
    assert initialized["result"]["serverInfo"]["name"] == "repoground"
    assert initialized["result"]["serverInfo"]["title"] == "RepoGround"


def test_mcp_stdio_requires_initialization(tmp_path):
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)

    response = server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )

    assert response["error"]["code"] == -32002


def test_initialized_notification_does_not_replace_initialize(tmp_path):
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)

    notification = server.handle_message(
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    )
    response = server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )

    assert notification is None
    assert response["error"]["code"] == -32002


def test_mcp_stdio_lists_read_tools_and_hides_snapshot_create_by_default(tmp_path):
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)
    initialized = _initialize(server)

    assert initialized["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert initialized["result"]["capabilities"]["tools"]["listChanged"] is False
    assert {tool["name"] for tool in _tools(server)} == {
        "bundle_discover",
        "snapshot_status",
        "ask_context",
        "query_existing_index",
        "range_get",
        "grounding_verify",
        "live_freshness",
        "find_symbol",
        "find_references",
        "get_callers",
        "get_callees",
    }


def test_snapshot_create_enable_requires_explicit_repo_root(tmp_path):
    with pytest.raises(ValueError, match="requires an explicit --repo-root"):
        RepoGroundMcpStdioServer(
            bundle_root=tmp_path,
            enable_snapshot_create=True,
        )


def test_mcp_stdio_exposes_startup_bound_snapshot_create_schema(tmp_path):
    repo = tmp_path / "repo"
    bundles = tmp_path / "bundles"
    repo.mkdir()
    bundles.mkdir()
    server = RepoGroundMcpStdioServer(
        bundle_root=bundles,
        repo_root=repo,
        enable_snapshot_create=True,
    )
    _initialize(server)

    definition = next(
        tool for tool in _tools(server) if tool["name"] == "snapshot_create"
    )
    properties = definition["inputSchema"]["properties"]

    assert definition["inputSchema"]["required"] == ["profile"]
    assert "repo" not in properties
    assert "output_root" not in properties


def test_snapshot_create_injects_startup_roots_and_rejects_overrides(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    bundles = tmp_path / "bundles"
    repo.mkdir()
    bundles.mkdir()
    server = RepoGroundMcpStdioServer(
        bundle_root=bundles,
        repo_root=repo,
        enable_snapshot_create=True,
    )
    _initialize(server)
    seen = {}

    def fake_snapshot_create(**arguments):
        seen.update(arguments)
        return {"status": "ok"}

    monkeypatch.setattr(mcp_tools, "snapshot_create", fake_snapshot_create)
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
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)
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
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)
    _initialize(server)
    seen = {}

    def fake_ask_context(**arguments):
        seen.update(arguments)
        return {"kind": "repoground.mcp.read_only_frontdoor", "status": "ok"}

    monkeypatch.setattr(mcp_tools, "ask_context", fake_ask_context)
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


def test_mcp_stdio_resource_read_preserves_content_and_adds_metadata(
    tmp_path, monkeypatch
):
    manifest = _manifest(tmp_path)
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path, repo_root=tmp_path)
    _initialize(server)
    uri = "repoground://snapshot/demo/canonical"

    monkeypatch.setattr(
        mcp_resources,
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
    assert result["_meta"]["repoground"]["liveFreshness"]["status"] == "stale"
    assert result["_meta"]["repoground"]["implicitRefresh"] is False


def test_mcp_stdio_without_configured_repo_reports_not_comparable(tmp_path):
    manifest = _manifest(tmp_path)
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)
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
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)
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
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)
    target = StringIO()

    serve_stdio(server, StringIO("{bad json\n"), target)

    response = json.loads(target.getvalue())
    assert response["error"] == {"code": -32700, "message": "parse error"}


def test_mcp_stdio_rejects_invalid_call_navigation_params_at_transport(tmp_path):
    manifest = _manifest(tmp_path)
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)
    _initialize(server)

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "find_references",
                "arguments": {
                    "bundle_manifest": str(manifest),
                    "name": "",
                    "path": "pkg/a.py",
                    "k": 25,
                },
            },
        }
    )

    assert response["error"] == {
        "code": -32602,
        "message": "find_references requires a non-empty name",
    }


def test_mcp_stdio_dispatches_get_callees_and_adds_freshness(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path)
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)
    _initialize(server)
    seen = {}

    def fake_get_callees(**arguments):
        seen.update(arguments)
        return {
            "kind": "repoground.mcp.read_only_frontdoor",
            "tool": "get_callees",
            "status": "available",
            "result": {"callees": [], "unresolved_call_sites": []},
        }

    monkeypatch.setattr(mcp_tools, "get_callees", fake_get_callees)
    monkeypatch.setattr(
        server,
        "_safe_live_freshness",
        lambda *_args, **_kwargs: {"status": "fresh", "implicit_refresh": False},
    )

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "get_callees",
                "arguments": {
                    "bundle_manifest": str(manifest),
                    "name": "caller_one",
                    "path": "pkg/a.py",
                    "k": 7,
                },
            },
        }
    )

    assert response["result"]["isError"] is False
    payload = response["result"]["structuredContent"]
    assert payload["tool"] == "get_callees"
    assert payload["live_freshness"]["status"] == "fresh"
    assert seen == {
        "bundle_manifest": str(manifest.resolve()),
        "name": "caller_one",
        "path": "pkg/a.py",
        "k": 7,
    }


def test_mcp_stdio_repo_selector_resolves_manifest_without_exposing_host_path(
    tmp_path, monkeypatch
):
    manifest = _manifest(tmp_path)
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)
    _initialize(server)
    seen = {}

    from merger.repoground.core import bundle_catalog

    monkeypatch.setattr(
        bundle_catalog,
        "select_bundle_manifest",
        lambda *_args, **_kwargs: {
            "status": "available",
            "selected": {"manifest_path": str(manifest)},
        },
    )

    def fake_snapshot_status(**arguments):
        seen.update(arguments)
        return {"status": "available", "tool": "snapshot_status"}

    monkeypatch.setattr(mcp_tools, "snapshot_status", fake_snapshot_status)
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "snapshot_status",
                "arguments": {"repo": "heimgewebe/repoground"},
            },
        }
    )

    assert response["result"]["isError"] is False
    assert seen == {"bundle_manifest": str(manifest.resolve())}


def test_mcp_stdio_exposes_bundle_discovery_as_read_only_tool(tmp_path, monkeypatch):
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)
    _initialize(server)

    from merger.repoground.core import bundle_catalog

    monkeypatch.setattr(
        bundle_catalog,
        "discover_bundle_catalog",
        lambda root: {
            "status": "available",
            "bundle_root": str(root),
            "candidate_count": 1,
        },
    )
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "bundle_discover", "arguments": {}},
        }
    )

    assert response["result"]["structuredContent"]["candidate_count"] == 1
    assert response["result"]["isError"] is False


def test_mcp_stdio_dispatches_bounded_query_and_range_read(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path)
    server = RepoGroundMcpStdioServer(bundle_root=manifest)
    _initialize(server)
    seen = []

    def fake_query(**arguments):
        seen.append(("query", arguments))
        return {
            "status": "available",
            "retrieval": {"strategy": "or_relaxed", "match_count": 2},
        }

    def fake_range(**arguments):
        seen.append(("range", arguments))
        return {"status": "resolved", "result": {"text": "demo"}}

    monkeypatch.setattr(mcp_tools, "query_existing_index", fake_query)
    monkeypatch.setattr(mcp_tools, "range_get", fake_range)

    query = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "query_existing_index",
                "arguments": {
                    "bundle_manifest": str(manifest),
                    "query": "natural language",
                    "max_context_tokens": 500,
                },
            },
        }
    )
    range_result = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "range_get",
                "arguments": {
                    "bundle_manifest": str(manifest),
                    "range_ref": {"ref": "demo"},
                },
            },
        }
    )

    assert query["result"]["structuredContent"]["retrieval"]["strategy"] == "or_relaxed"
    assert range_result["result"]["structuredContent"]["status"] == "resolved"
    assert seen == [
        (
            "query",
            {
                "query": "natural language",
                "max_context_tokens": 500,
                "bundle_manifest": str(manifest.resolve()),
            },
        ),
        (
            "range",
            {
                "range_ref": {"ref": "demo"},
                "bundle_manifest": str(manifest.resolve()),
            },
        ),
    ]


def test_mcp_stdio_text_summary_does_not_duplicate_structured_payload(
    tmp_path, monkeypatch
):
    manifest = _manifest(tmp_path)
    server = RepoGroundMcpStdioServer(bundle_root=manifest)
    _initialize(server)

    monkeypatch.setattr(
        mcp_tools,
        "ask_context",
        lambda **_arguments: {"status": "ok", "blob": "x" * 10000},
    )
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "ask_context",
                "arguments": {
                    "bundle_manifest": str(manifest),
                    "query": "hello",
                },
            },
        }
    )

    result = response["result"]
    text = result["content"][0]["text"]
    assert len(text.encode("utf-8")) < 300
    assert result["structuredContent"]["blob"] == "x" * 10000
    assert json.loads(text)["details"].startswith("Use structuredContent")


def test_mcp_stdio_legacy_protocol_keeps_full_payload_in_text(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path)
    server = RepoGroundMcpStdioServer(bundle_root=manifest)
    initialized = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "legacy-test", "version": "1"},
            },
        }
    )
    assert initialized["result"]["protocolVersion"] == "2025-03-26"
    monkeypatch.setattr(
        mcp_tools,
        "ask_context",
        lambda **_arguments: {"status": "ok", "blob": "x" * 10000},
    )

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "ask_context",
                "arguments": {
                    "bundle_manifest": str(manifest),
                    "query": "hello",
                },
            },
        }
    )

    result = response["result"]
    assert json.loads(result["content"][0]["text"])["blob"] == "x" * 10000
    assert result["structuredContent"]["blob"] == "x" * 10000
