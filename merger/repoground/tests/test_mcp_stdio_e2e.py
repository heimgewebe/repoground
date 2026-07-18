from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from merger.repoground.cli.mcp_stdio import PROTOCOL_VERSION
from merger.repoground.core.live_freshness import evaluate_live_freshness

REPO_ROOT = Path(__file__).resolve().parents[3]
MCP_LAUNCHER = REPO_ROOT / "scripts/repoground-mcp-stdio.py"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(path: Path, *, repo: Path, commit: str) -> Path:
    manifest = path / "demo.bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "run_id": "demo",
                "artifacts": [],
                "snapshot_provenance": {
                    "version": "v1",
                    "repositories": [
                        {
                            "name": repo.name,
                            "repo_root": str(repo.resolve()),
                            "git_commit": commit,
                            "git_dirty": False,
                            "git_branch": "main",
                            "provenance_status": "present",
                            "freshness_basis": "git_commit_and_working_tree",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_mcp_stdio_launcher_completes_handshake_outside_checkout(tmp_path: Path) -> None:
    client_cwd = tmp_path / "client-cwd"
    bundle_root = tmp_path / "bundles"
    client_cwd.mkdir()
    bundle_root.mkdir()
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1"},
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        },
    ]
    completed = subprocess.run(
        [
            sys.executable,
            str(MCP_LAUNCHER),
            "--bundle-root",
            str(bundle_root),
        ],
        cwd=client_cwd,
        input="".join(json.dumps(request) + "\n" for request in requests),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [response["id"] for response in responses] == [1, 2]
    assert responses[0]["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert {
        tool["name"] for tool in responses[1]["result"]["tools"]
    } == {
        "ask_context",
        "grounding_verify",
        "live_freshness",
        "find_symbol",
        "find_references",
        "get_callers",
        "get_callees",
    }


@pytest.mark.skipif(shutil.which("git") is None, reason="git executable unavailable")
def test_live_freshness_real_git_probe_is_read_only_and_detects_dirtiness(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "user.name", "RepoBrief Test")
    _git(repo, "config", "user.email", "repobrief@example.invalid")
    source = repo / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", "example.py")
    _git(repo, "commit", "-q", "-m", "initial")
    commit = _git(repo, "rev-parse", "HEAD")
    manifest = _manifest(tmp_path, repo=repo, commit=commit)
    index_path = repo / ".git" / "index"
    index_before = _sha256(index_path)

    clean = evaluate_live_freshness(manifest, repo_root=repo)

    assert clean["status"] == "fresh"
    assert clean["current_provenance"]["git_commit"] == commit
    assert _sha256(index_path) == index_before
    assert _git(repo, "rev-parse", "HEAD") == commit

    source.write_text("value = 2\n", encoding="utf-8")
    dirty = evaluate_live_freshness(manifest, repo_root=repo)

    assert dirty["status"] == "stale"
    assert dirty["reason"] == "current_working_tree_is_dirty"
    assert _sha256(index_path) == index_before
    assert _git(repo, "rev-parse", "HEAD") == commit


def _symbol_manifest(bundle_root: Path, *, repo: Path, commit: str) -> Path:
    index = bundle_root / "demo.python_symbol_index.json"
    index.write_text(
        json.dumps(
            {
                "kind": "lenskit.python_symbol_index",
                "version": "1.0",
                "run_id": "demo",
                "canonical_dump_index_sha256": "a" * 64,
                "language": "python",
                "symbol_kinds": ["class", "function", "async_function"],
                "symbols": [
                    # Substring match declared before the exact match, to prove
                    # exact-first ranking over the transport.
                    {
                        "id": "py:pkg:mod.py:function:run_pipeline",
                        "kind": "function",
                        "name": "run_pipeline",
                        "qualified_name": "run_pipeline",
                        "module": "pkg.mod",
                        "path": "pkg/mod.py",
                        "start_line": 3,
                        "end_line": 5,
                        "range_ref": "file:pkg/mod.py#L3-L5",
                    },
                    {
                        "id": "py:pkg:mod.py:function:run",
                        "kind": "function",
                        "name": "run",
                        "qualified_name": "run",
                        "module": "pkg.mod",
                        "path": "pkg/mod.py",
                        "start_line": 8,
                        "end_line": 10,
                        "range_ref": "file:pkg/mod.py#L8-L10",
                    },
                ],
                "skipped_files_count": 0,
                "skipped_errors": [],
                "does_not_establish": ["call_graph_completeness"],
            }
        ),
        encoding="utf-8",
    )
    manifest = bundle_root / "demo.bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "run_id": "demo",
                "artifacts": [
                    {
                        "role": "python_symbol_index_json",
                        "path": index.name,
                        "content_type": "application/json",
                        "bytes": index.stat().st_size,
                        "sha256": _sha256(index),
                    }
                ],
                "snapshot_provenance": {
                    "version": "v1",
                    "repositories": [
                        {
                            "name": repo.name,
                            "repo_root": str(repo.resolve()),
                            "git_commit": commit,
                            "git_dirty": False,
                            "git_branch": "main",
                            "provenance_status": "present",
                            "freshness_basis": "git_commit_and_working_tree",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _run_launcher(bundle_root: Path, repo_root: Path | None, requests: list[dict]) -> list[dict]:
    args = [sys.executable, str(MCP_LAUNCHER), "--bundle-root", str(bundle_root)]
    if repo_root is not None:
        args += ["--repo-root", str(repo_root)]
    completed = subprocess.run(
        args,
        input="".join(json.dumps(request) + "\n" for request in requests),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def _handshake(next_id: int, *calls: dict) -> list[dict]:
    requests: list[dict] = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    ]
    requests.extend(calls)
    return requests


@pytest.mark.skipif(shutil.which("git") is None, reason="git executable unavailable")
def test_find_symbol_tools_call_returns_ranked_location_and_freshness(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "user.name", "RepoBrief Test")
    _git(repo, "config", "user.email", "repobrief@example.invalid")
    (repo / "example.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", "example.py")
    _git(repo, "commit", "-q", "-m", "initial")
    commit = _git(repo, "rev-parse", "HEAD")

    bundle_root = tmp_path / "bundles"
    bundle_root.mkdir()
    manifest = _symbol_manifest(bundle_root, repo=repo, commit=commit)

    requests = _handshake(
        2,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "find_symbol",
                "arguments": {"bundle_manifest": str(manifest), "name": "run"},
            },
        },
    )
    responses = _run_launcher(bundle_root, repo, requests)
    call_response = next(r for r in responses if r.get("id") == 2)
    assert "error" not in call_response, call_response
    payload = json.loads(call_response["result"]["content"][0]["text"])

    assert payload["tool"] == "find_symbol"
    assert payload["status"] == "available"
    hits = payload["result"]["hits"]
    # exact 'run' ranks before the 'run_pipeline' substring match
    assert hits[0]["qualified_name"] == "run"
    assert hits[0]["path"] == "pkg/mod.py"
    assert hits[0]["start_line"] == 8
    assert hits[0]["end_line"] == 10
    assert hits[0]["range_ref"] == "file:pkg/mod.py#L8-L10"
    # navigation results carry the snapshot's live freshness against the checkout
    assert payload["live_freshness"]["status"] == "fresh"
    assert payload["live_freshness"]["current_provenance"]["git_commit"] == commit


def test_find_symbol_tools_call_rejects_empty_name_and_invalid_kind(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundles"
    bundle_root.mkdir()
    manifest = bundle_root / "demo.bundle.manifest.json"
    manifest.write_text(
        json.dumps({"kind": "repolens.bundle.manifest", "run_id": "demo", "artifacts": []}),
        encoding="utf-8",
    )

    requests = _handshake(
        2,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "find_symbol",
                "arguments": {"bundle_manifest": str(manifest), "name": ""},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "find_symbol",
                "arguments": {"bundle_manifest": str(manifest), "name": "run", "kind": "macro"},
            },
        },
    )
    responses = _run_launcher(bundle_root, None, requests)
    by_id = {r.get("id"): r for r in responses}

    # Fail closed: neither request returns a symbol listing; both are rejected.
    assert by_id[2]["error"]["code"] == -32602
    assert "non-empty name" in by_id[2]["error"]["message"]
    assert by_id[3]["error"]["code"] == -32602
    assert "kind" in by_id[3]["error"]["message"]


def _call_navigation_manifest(bundle_root: Path) -> Path:
    canonical = "a" * 64
    caller_id = "py:pkg:caller.py:function:caller"
    target_id = "py:pkg:target.py:function:target"
    symbol_index = bundle_root / "calls.python_symbol_index.json"
    symbol_index.write_text(
        json.dumps(
            {
                "kind": "lenskit.python_symbol_index",
                "version": "1.0",
                "run_id": "demo",
                "canonical_dump_index_sha256": canonical,
                "language": "python",
                "symbol_kinds": ["class", "function", "async_function"],
                "symbols": [
                    {
                        "id": caller_id,
                        "kind": "function",
                        "name": "caller",
                        "qualified_name": "caller",
                        "module": "pkg.caller",
                        "path": "pkg/caller.py",
                        "start_line": 1,
                        "end_line": 4,
                        "range_ref": "file:pkg/caller.py#L1-L4",
                    },
                    {
                        "id": target_id,
                        "kind": "function",
                        "name": "target",
                        "qualified_name": "target",
                        "module": "pkg.target",
                        "path": "pkg/target.py",
                        "start_line": 1,
                        "end_line": 2,
                        "range_ref": "file:pkg/target.py#L1-L2",
                    },
                ],
                "skipped_files_count": 0,
                "skipped_errors": [],
                "does_not_establish": ["call_graph_completeness"],
            }
        ),
        encoding="utf-8",
    )
    calls = [
        {
            "path": "pkg/caller.py",
            "start_line": 2,
            "start_col": 4,
            "end_line": 2,
            "end_col": 12,
            "range_ref": "file:pkg/caller.py#L2-L2",
            "callee_expression": "target",
            "simple_name": "target",
            "caller_scope": "symbol",
            "caller_symbol_id": caller_id,
            "caller_qualified_name": "caller",
            "caller_kind": "function",
            "caller_start_line": 1,
            "caller_end_line": 4,
            "relation_type": "calls",
            "evidence_level": "S1",
            "resolution_status": "resolved",
            "resolution_reason": "imported_internal_name",
            "resolved_target_ids": [target_id],
            "candidate_target_ids": [],
        },
        {
            "path": "pkg/caller.py",
            "start_line": 3,
            "start_col": 4,
            "end_line": 3,
            "end_col": 17,
            "range_ref": "file:pkg/caller.py#L3-L3",
            "callee_expression": "client.send",
            "simple_name": "send",
            "caller_scope": "symbol",
            "caller_symbol_id": caller_id,
            "caller_qualified_name": "caller",
            "caller_kind": "function",
            "caller_start_line": 1,
            "caller_end_line": 4,
            "relation_type": "calls",
            "evidence_level": "S0",
            "resolution_status": "unresolved",
            "resolution_reason": "dynamic_attribute_call",
            "resolved_target_ids": [],
            "candidate_target_ids": [],
        },
    ]
    call_graph = bundle_root / "calls.python_call_graph.json"
    call_graph.write_text(
        json.dumps(
            {
                "kind": "lenskit.python_call_graph",
                "version": "1.0",
                "run_id": "demo",
                "canonical_dump_index_sha256": canonical,
                "language": "python",
                "evidence_model": {
                    "S0": "unresolved static call site",
                    "S1": "one uniquely resolved local target",
                },
                "resolution_statuses": [
                    "resolved",
                    "candidate",
                    "ambiguous",
                    "unresolved",
                ],
                "relation_types": ["calls", "constructs"],
                "call_count": 2,
                "resolution_counts": {
                    "resolved": 1,
                    "candidate": 0,
                    "ambiguous": 0,
                    "unresolved": 1,
                },
                "evidence_counts": {"S0": 1, "S1": 1},
                "relation_counts": {"calls": 2, "constructs": 0},
                "calls": calls,
                "skipped_files_count": 0,
                "skipped_errors": [],
                "does_not_establish": [
                    "complete_call_graph",
                    "runtime_reachability",
                    "dynamic_dispatch_resolution",
                    "dependency_completeness",
                    "import_success",
                    "test_sufficiency",
                    "review_completeness",
                    "merge_readiness",
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = bundle_root / "calls.bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "run_id": "demo",
                "artifacts": [
                    {
                        "role": "python_symbol_index_json",
                        "path": symbol_index.name,
                        "content_type": "application/json",
                        "bytes": symbol_index.stat().st_size,
                        "sha256": _sha256(symbol_index),
                    },
                    {
                        "role": "python_call_graph_json",
                        "path": call_graph.name,
                        "content_type": "application/json",
                        "bytes": call_graph.stat().st_size,
                        "sha256": _sha256(call_graph),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_get_callees_tools_call_round_trips_evidence_over_stdio(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundles"
    bundle_root.mkdir()
    manifest = _call_navigation_manifest(bundle_root)
    responses = _run_launcher(
        bundle_root,
        None,
        _handshake(
            2,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "get_callees",
                    "arguments": {
                        "bundle_manifest": str(manifest),
                        "name": "caller",
                        "path": "pkg/caller.py",
                    },
                },
            },
        ),
    )
    response = next(item for item in responses if item.get("id") == 2)
    assert "error" not in response, response
    payload = json.loads(response["result"]["content"][0]["text"])

    assert payload["tool"] == "get_callees"
    assert payload["status"] == "available"
    result = payload["result"]
    assert result["caller_symbol"]["qualified_name"] == "caller"
    assert result["callees"][0]["callee_symbol"]["qualified_name"] == "target"
    assert result["callees"][0]["call_sites"][0]["evidence_level"] == "S1"
    assert result["unresolved_call_sites"][0]["callee_expression"] == "client.send"
    assert result["unresolved_call_sites"][0]["evidence_level"] == "S0"
    assert payload["live_freshness"]["status"] == "not_comparable"
