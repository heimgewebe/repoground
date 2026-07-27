import hashlib
import json
import sqlite3
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
from merger.repoground.core.manifest_snapshot import active_manifest_snapshot
from merger.repoground.tests.test_answer_grounding_verifier import (
    _bundle as _grounding_bundle,
)
from merger.repoground.tests.test_answer_grounding_verifier import (
    _declaration as _grounding_declaration,
)
from merger.repoground.tests.test_ask_context_cli import _complete_basic_bundle


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
            "selected": {
                "manifest_path": str(manifest),
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "run_id": "demo",
            },
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


def test_mcp_stdio_fails_closed_when_selected_manifest_is_atomically_replaced(
    tmp_path, monkeypatch
):
    manifest = _manifest(tmp_path)
    selected_bytes = manifest.read_bytes()
    selected_sha256 = hashlib.sha256(selected_bytes).hexdigest()
    replacement = tmp_path / "replacement.bundle.manifest.json"
    replacement.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "run_id": "replacement",
                "artifacts": [],
                "snapshot_provenance": {"version": "v1", "repositories": []},
            }
        ),
        encoding="utf-8",
    )
    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)
    _initialize(server)

    from merger.repoground.core import bundle_catalog

    def select_then_replace(*_args, **_kwargs):
        selected = {
            "manifest_path": str(manifest),
            "manifest_sha256": selected_sha256,
            "run_id": "demo",
        }
        replacement.replace(manifest)
        return {"status": "available", "selected": selected}

    monkeypatch.setattr(
        bundle_catalog,
        "select_bundle_manifest",
        select_then_replace,
    )
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {
                "name": "snapshot_status",
                "arguments": {"repo": "heimgewebe/repoground"},
            },
        }
    )

    assert response["error"]["code"] == -32001
    assert response["error"]["data"]["status"] == "manifest_binding_failed"
    assert "digest" in response["error"]["data"]["reason"]


def test_mcp_stdio_fails_closed_when_manifest_remains_replaced_during_handler(
    tmp_path, monkeypatch
):
    manifest = _manifest(tmp_path)
    replacement = tmp_path / "replacement.bundle.manifest.json"
    replacement.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "run_id": "replacement",
                "artifacts": [],
                "snapshot_provenance": {"version": "v1", "repositories": []},
            }
        ),
        encoding="utf-8",
    )
    server = RepoGroundMcpStdioServer(bundle_root=manifest)
    _initialize(server)

    from merger.repoground.core import bundle_access

    def replace_during_handler(**arguments):
        replacement.replace(manifest)
        snapshot = bundle_access.snapshot_status(arguments["bundle_manifest"])
        return {
            "status": "available",
            "selected_run_id": snapshot["bundle_run_id"],
        }

    monkeypatch.setattr(mcp_tools, "snapshot_status", replace_during_handler)
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 15,
            "method": "tools/call",
            "params": {
                "name": "snapshot_status",
                "arguments": {"bundle_manifest": str(manifest)},
            },
        }
    )

    assert response["error"]["code"] == -32001
    assert response["error"]["data"]["status"] == "manifest_binding_failed"


def test_mcp_stdio_consumes_bound_bytes_across_exchange_and_restore(
    tmp_path, monkeypatch
):
    manifest = _manifest(tmp_path)
    original_document = json.loads(manifest.read_text(encoding="utf-8"))
    original_document["artifacts"] = [
        {"role": "selected_marker", "path": "selected.txt"}
    ]
    manifest.write_text(json.dumps(original_document), encoding="utf-8")
    (tmp_path / "selected.txt").write_text("selected\n", encoding="utf-8")
    original_bytes = manifest.read_bytes()
    replacement_bytes = json.dumps(
        {
            "kind": "repolens.bundle.manifest",
            "run_id": "replacement",
            "artifacts": [{"role": "selected_marker", "path": "replacement.txt"}],
            "snapshot_provenance": {"version": "v1", "repositories": []},
        }
    ).encode("utf-8")
    (tmp_path / "replacement.txt").write_text("replacement\n", encoding="utf-8")
    server = RepoGroundMcpStdioServer(bundle_root=manifest)
    _initialize(server)

    from merger.repoground.core import bundle_access

    def exchange_and_restore(**arguments):
        replacement = tmp_path / "replacement.bundle.manifest.json"
        replacement.write_bytes(replacement_bytes)
        replacement.replace(manifest)
        snapshot = bundle_access.snapshot_status(arguments["bundle_manifest"])
        artifact = bundle_access.get_artifact(
            arguments["bundle_manifest"],
            "selected_marker",
        )
        restored = tmp_path / "restored.bundle.manifest.json"
        restored.write_bytes(original_bytes)
        restored.replace(manifest)
        return {
            "status": "available",
            "selected_run_id": snapshot["bundle_run_id"],
            "selected_artifact_path": artifact["artifact"]["path"],
        }

    monkeypatch.setattr(mcp_tools, "snapshot_status", exchange_and_restore)
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 16,
            "method": "tools/call",
            "params": {
                "name": "snapshot_status",
                "arguments": {"bundle_manifest": str(manifest)},
            },
        }
    )

    assert response["result"]["isError"] is False
    assert response["result"]["structuredContent"]["selected_run_id"] == "demo"
    assert (
        response["result"]["structuredContent"]["selected_artifact_path"]
        == "selected.txt"
    )


@pytest.mark.parametrize("replacement_outside_bundle_root", [False, True])
def test_mcp_stdio_symlink_exchange_and_restore_uses_selected_manifest_bytes(
    tmp_path,
    monkeypatch,
    replacement_outside_bundle_root,
):
    bundle_root = tmp_path / "bundles"
    bundle_root.mkdir()
    selected = _manifest(bundle_root)
    selected_bytes = selected.read_bytes()
    selected_sha256 = hashlib.sha256(selected_bytes).hexdigest()

    replacement_root = (
        tmp_path / "outside" if replacement_outside_bundle_root else bundle_root
    )
    replacement_root.mkdir(exist_ok=True)
    replacement = replacement_root / "replacement.bundle.manifest.json"
    replacement.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "run_id": "replacement",
                "artifacts": [],
                "snapshot_provenance": {"version": "v1", "repositories": []},
            }
        ),
        encoding="utf-8",
    )
    selected_link = bundle_root / "active.bundle.manifest.json"
    selected_link.symlink_to(selected)

    def point_link_at(target):
        staged = bundle_root / ".active.bundle.manifest.json.next"
        staged.symlink_to(target)
        staged.replace(selected_link)

    server = RepoGroundMcpStdioServer(bundle_root=bundle_root)
    _initialize(server)

    original_snapshot_status = mcp_tools.snapshot_status

    def exchange_read_and_restore(**arguments):
        point_link_at(replacement)
        try:
            bound = active_manifest_snapshot(arguments["bundle_manifest"])
            payload = original_snapshot_status(**arguments)
        finally:
            point_link_at(selected)
        assert bound is not None
        payload.update(
            {
                "bound_selected_path": str(bound.selected_path),
                "bound_resolved_path": str(bound.resolved_path),
                "bound_sha256": hashlib.sha256(bound.raw).hexdigest(),
                "selected_run_id": payload["snapshot"]["bundle_run_id"],
            }
        )
        return payload

    monkeypatch.setattr(mcp_tools, "snapshot_status", exchange_read_and_restore)
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 19,
            "method": "tools/call",
            "params": {
                "name": "snapshot_status",
                "arguments": {"bundle_manifest": str(selected_link)},
            },
        }
    )

    assert response["result"]["isError"] is False
    result = response["result"]["structuredContent"]
    assert result["bound_selected_path"] == str(selected_link.absolute())
    assert result["bound_resolved_path"] == str(selected.resolve())
    assert result["bound_sha256"] == selected_sha256
    assert result["selected_run_id"] == "demo"
    assert selected_link.resolve() == selected.resolve()


def test_mcp_stdio_grounding_verify_pins_selected_symlink_target_during_exchange(
    tmp_path,
    monkeypatch,
):
    selected_root = tmp_path / "selected"
    replacement_root = tmp_path / "replacement"
    selected_root.mkdir()
    replacement_root.mkdir()
    selected_manifest, citation_map, range_ref = _grounding_bundle(
        selected_root,
        content=b"Line 1\nselected\nLine 3\n",
    )
    replacement_manifest, _, _ = _grounding_bundle(
        replacement_root,
        content=b"Line 1\nreplaced\nLine 3\n",
    )
    selected_link = tmp_path / "active.bundle.manifest.json"
    selected_link.symlink_to(selected_manifest)
    declaration = _grounding_declaration(range_ref)
    declaration.pop("snapshot_ref")
    declaration["declared_artifacts"] = [
        "agent_reading_pack",
        "canonical_md",
        "citation_map_jsonl",
        "snapshot_plan_json",
    ]

    def point_link_at(target):
        staged = tmp_path / ".active.bundle.manifest.json.next"
        staged.symlink_to(target)
        staged.replace(selected_link)

    server = RepoGroundMcpStdioServer(bundle_root=tmp_path)
    _initialize(server)
    original_grounding_verify = mcp_tools.grounding_verify

    def exchange_verify_and_restore(**arguments):
        point_link_at(replacement_manifest)
        try:
            return original_grounding_verify(**arguments)
        finally:
            point_link_at(selected_manifest)

    monkeypatch.setattr(
        mcp_tools,
        "grounding_verify",
        exchange_verify_and_restore,
    )
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/call",
            "params": {
                "name": "grounding_verify",
                "arguments": {
                    "bundle_manifest": str(selected_link),
                    "citation_map": str(citation_map),
                    "declaration": declaration,
                    "task_profile": "basic_repo_question",
                },
            },
        }
    )

    assert response["result"]["isError"] is False
    result = response["result"]["structuredContent"]
    assert result["status"] == "pass"
    assert result["verdict"]["status"] == "pass"
    assert {check["status"] for check in result["verdict"]["citation_checks"]} == {
        "resolved"
    }
    assert result["verdict"]["range_checks"][0]["status"] == "resolved"
    assert result["verdict"]["snapshot_ref"]["manifest_path"] == str(
        selected_link.absolute()
    )
    assert selected_link.resolve() == selected_manifest.resolve()


def test_mcp_stdio_ask_context_keeps_selected_manifest_metadata_across_exchange(
    tmp_path, monkeypatch
):
    bundle = _complete_basic_bundle(tmp_path)
    manifest = bundle["manifest"].resolve()
    selected_bytes = manifest.read_bytes()
    selected_document = json.loads(selected_bytes)
    selected_sha256 = hashlib.sha256(selected_bytes).hexdigest()
    replacement_document = dict(selected_document)
    replacement_document["run_id"] = "replacement-run"
    replacement_bytes = json.dumps(replacement_document).encode("utf-8")
    replacement_sha256 = hashlib.sha256(replacement_bytes).hexdigest()
    server = RepoGroundMcpStdioServer(bundle_root=manifest)
    _initialize(server)

    from merger.repoground.core import ask_context as ask_context_module

    original_snapshot_status = ask_context_module.snapshot_status
    original_ask_context = mcp_tools.ask_context
    observed_run_ids = []

    def exchange_before_snapshot_status(bundle_manifest):
        replacement = tmp_path / "replacement.bundle.manifest.json"
        replacement.write_bytes(replacement_bytes)
        replacement.replace(manifest)
        status = original_snapshot_status(bundle_manifest)
        observed_run_ids.append(status["bundle_run_id"])
        return status

    def ask_then_restore(**arguments):
        try:
            return original_ask_context(**arguments)
        finally:
            restored = tmp_path / "restored.bundle.manifest.json"
            restored.write_bytes(selected_bytes)
            restored.replace(manifest)

    monkeypatch.setattr(
        ask_context_module,
        "snapshot_status",
        exchange_before_snapshot_status,
    )
    monkeypatch.setattr(mcp_tools, "ask_context", ask_then_restore)

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 17,
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

    context_pack = response["result"]["structuredContent"]["context_pack"]
    assert response["result"]["isError"] is False
    assert context_pack["resolved_ranges"][0]["status"] == "resolved"
    assert context_pack["snapshot_ref"]["manifest_sha256"] == selected_sha256
    assert context_pack["snapshot_ref"]["manifest_sha256"] != replacement_sha256
    assert observed_run_ids == [selected_document["run_id"]]
    assert observed_run_ids != [replacement_document["run_id"]]


def test_mcp_stdio_query_rejects_sqlite_from_exchanged_generation(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "selected").mkdir()
    (tmp_path / "replacement").mkdir()
    selected = _complete_basic_bundle(tmp_path / "selected")
    replacement = _complete_basic_bundle(tmp_path / "replacement")
    selected_manifest = selected["manifest"].resolve()
    selected_index = selected["index_path"].resolve()
    replacement_manifest = replacement["manifest"].resolve()
    replacement_index = replacement["index_path"].resolve()

    with sqlite3.connect(replacement_index) as connection:
        connection.execute(
            "UPDATE chunks_fts SET content = ?",
            ("generation_b_only",),
        )
    replacement_document = json.loads(replacement_manifest.read_text(encoding="utf-8"))
    replacement_sqlite = next(
        artifact
        for artifact in replacement_document["artifacts"]
        if artifact["role"] == "sqlite_index"
    )
    replacement_sqlite["bytes"] = replacement_index.stat().st_size
    replacement_sqlite["sha256"] = hashlib.sha256(
        replacement_index.read_bytes()
    ).hexdigest()
    replacement_document["run_id"] = "generation-b"
    replacement_manifest.write_text(
        json.dumps(replacement_document, sort_keys=True),
        encoding="utf-8",
    )
    generation_b = mcp_tools.query_existing_index(
        bundle_manifest=replacement_manifest,
        query="generation_b_only",
    )
    assert generation_b["retrieval"]["match_count"] == 1

    selected_manifest_bytes = selected_manifest.read_bytes()
    selected_index_sha256 = hashlib.sha256(selected_index.read_bytes()).hexdigest()
    replacement_manifest_bytes = replacement_manifest.read_bytes()
    replacement_index_bytes = replacement_index.read_bytes()
    replacement_index_sha256 = hashlib.sha256(replacement_index_bytes).hexdigest()
    assert replacement_index_sha256 != selected_index_sha256

    server = RepoGroundMcpStdioServer(bundle_root=selected_manifest)
    _initialize(server)

    from merger.repoground.core import ask_context as ask_context_module

    original_snapshot_status = ask_context_module.snapshot_status
    original_query = ask_context_module.query_existing_index
    original_tool = mcp_tools.query_existing_index
    observed_queries = []
    exchanged = False

    def exchange_before_query(bundle_manifest):
        nonlocal exchanged
        if not exchanged:
            sqlite_replacement = selected_index.with_name("generation-b.index.sqlite")
            sqlite_replacement.write_bytes(replacement_index_bytes)
            sqlite_replacement.replace(selected_index)
            manifest_replacement = selected_manifest.with_name(
                "generation-b.bundle.manifest.json"
            )
            manifest_replacement.write_bytes(replacement_manifest_bytes)
            manifest_replacement.replace(selected_manifest)
            exchanged = True
        return original_snapshot_status(bundle_manifest)

    def record_query(*args, **kwargs):
        result = original_query(*args, **kwargs)
        observed_queries.append(result)
        return result

    def query_then_restore_manifest(**arguments):
        try:
            return original_tool(**arguments)
        finally:
            restored = selected_manifest.with_name(
                "generation-a-restored.bundle.manifest.json"
            )
            restored.write_bytes(selected_manifest_bytes)
            restored.replace(selected_manifest)

    monkeypatch.setattr(
        ask_context_module,
        "snapshot_status",
        exchange_before_query,
    )
    monkeypatch.setattr(
        ask_context_module,
        "query_existing_index",
        record_query,
    )
    monkeypatch.setattr(
        mcp_tools,
        "query_existing_index",
        query_then_restore_manifest,
    )

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 18,
            "method": "tools/call",
            "params": {
                "name": "query_existing_index",
                "arguments": {
                    "bundle_manifest": str(selected_manifest),
                    "query": "generation_b_only",
                },
            },
        }
    )

    assert response["result"]["isError"] is False
    assert len(observed_queries) == 1
    assert observed_queries[0]["status"] == "invalid"
    assert observed_queries[0]["error_code"] == "sqlite_index_integrity_mismatch"
    assert observed_queries[0]["query_result"] is None
    result = response["result"]["structuredContent"]
    assert result["retrieval"]["match_count"] == 0
    assert result["retrieval_hits"] == []
    assert result["resolved_ranges"] == []
    assert any(
        "sqlite_index" in caveat["detail"] for caveat in result["answer_caveats"]
    )
    assert selected_manifest.read_bytes() == selected_manifest_bytes
    assert hashlib.sha256(selected_index.read_bytes()).hexdigest() == (
        replacement_index_sha256
    )


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
