import hashlib
import json
from pathlib import Path

from merger.lenskit.cli.main import main
from merger.lenskit.core.repobrief_access import search_symbol_index


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_symbol_bundle(tmp_path: Path) -> Path:
    symbol_index = tmp_path / "demo.python_symbol_index.json"
    symbol_index.write_text(
        json.dumps(
            {
                "kind": "lenskit.python_symbol_index",
                "version": "1.0",
                "run_id": "run-1",
                "canonical_dump_index_sha256": "a" * 64,
                "language": "python",
                "symbol_kinds": ["class", "function", "async_function"],
                "symbols": [
                    {
                        "id": "py:pkg:mod.py:function:build_context",
                        "kind": "function",
                        "name": "build_context",
                        "qualified_name": "build_context",
                        "module": "pkg.mod",
                        "path": "pkg/mod.py",
                        "start_line": 3,
                        "end_line": 5,
                        "range_ref": "file:pkg/mod.py#L3-L5",
                    },
                    {
                        "id": "py:pkg:mod.py:class:ContextPlan",
                        "kind": "class",
                        "name": "ContextPlan",
                        "qualified_name": "ContextPlan",
                        "module": "pkg.mod",
                        "path": "pkg/mod.py",
                        "start_line": 8,
                        "end_line": 12,
                        "range_ref": "file:pkg/mod.py#L8-L12",
                    },
                ],
                "skipped_files_count": 0,
                "skipped_errors": [],
                "does_not_establish": [
                    "call_graph_completeness",
                    "dependency_completeness",
                    "runtime_behavior",
                    "import_success",
                    "test_sufficiency",
                    "review_impact",
                    "merge_readiness",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "version": "1.0",
                "run_id": "run-1",
                "created_at": "2026-07-08T10:00:00Z",
                "generator": {"name": "test", "version": "1", "config_sha256": "b" * 64},
                "artifacts": [
                    {
                        "role": "python_symbol_index_json",
                        "path": symbol_index.name,
                        "content_type": "application/json",
                        "bytes": symbol_index.stat().st_size,
                        "sha256": _sha(symbol_index),
                        "contract": {"id": "python-symbol-index", "version": "v1"},
                        "interpretation": {"mode": "contract"},
                        "authority": "navigation_index",
                        "canonicality": "derived",
                        "risk_class": "navigation",
                        "regenerable": True,
                        "staleness_sensitive": True,
                    }
                ],
                "links": {},
                "capabilities": {"repobrief_profile": "agent-portable"},
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_symbol_search_reads_existing_artifact_without_workspace_execution(tmp_path):
    manifest = _write_symbol_bundle(tmp_path)
    before_files = {path.name for path in tmp_path.iterdir()}
    before_manifest_hash = _sha(manifest)

    result = search_symbol_index(manifest, "context", k=5)

    assert result["kind"] == "repobrief.symbol_search"
    assert result["status"] == "available"
    assert result["hit_count"] == 2
    assert [hit["qualified_name"] for hit in result["hits"]] == ["build_context", "ContextPlan"]
    assert result["hits"][0]["source_range"] == {
        "path": "pkg/mod.py",
        "start_line": 3,
        "end_line": 5,
        "range_ref": "file:pkg/mod.py#L3-L5",
        "coordinate_basis": "source_lines",
    }
    assert result["mutation_boundary"]["writes"] == []
    assert result["mutation_boundary"]["read_paths_do_not_refresh"] is True
    assert "runtime_behavior" in result["does_not_establish"]
    assert "call_graph_completeness" in result["does_not_establish"]
    assert {path.name for path in tmp_path.iterdir()} == before_files
    assert _sha(manifest) == before_manifest_hash


def test_symbol_search_filters_by_kind_and_path(tmp_path):
    manifest = _write_symbol_bundle(tmp_path)

    result = search_symbol_index(manifest, "context", k=5, kind="class", path="pkg/mod")

    assert result["status"] == "available"
    assert result["hit_count"] == 1
    assert result["hits"][0]["qualified_name"] == "ContextPlan"
    assert result["hits"][0]["kind"] == "class"


def test_symbol_search_reports_missing_artifact_without_creating_it(tmp_path):
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "version": "1.0",
                "run_id": "run-1",
                "artifacts": [],
                "links": {},
                "capabilities": {},
            }
        ),
        encoding="utf-8",
    )

    result = search_symbol_index(manifest, "context")

    assert result["status"] == "missing"
    assert result["error_code"] == "python_symbol_index_json_missing"
    assert result["hits"] == []
    assert result["mutation_boundary"]["writes"] == []
    assert not (tmp_path / "demo.python_symbol_index.json").exists()


def test_symbol_search_cli_returns_symbol_hits(tmp_path, capsys):
    manifest = _write_symbol_bundle(tmp_path)

    rc = main([
        "repobrief",
        "symbol",
        "search",
        "--bundle-manifest",
        str(manifest),
        "--q",
        "ContextPlan",
        "--kind",
        "class",
    ])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["status"] == "available"
    assert out["hit_count"] == 1
    assert out["hits"][0]["source_range"]["range_ref"] == "file:pkg/mod.py#L8-L12"


def test_public_share_snapshot_excludes_python_symbol_index(tmp_path, capsys):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("def hidden_symbol():\n    return None\n", encoding="utf-8")
    out = tmp_path / "out"

    rc = main([
        "repobrief",
        "snapshot",
        "create",
        "--repo",
        str(repo),
        "--out",
        str(out),
        "--profile",
        "public-share",
        "--redact-secrets",
    ])

    emitted = json.loads(capsys.readouterr().out)
    manifest = json.loads(Path(emitted["bundle_manifest"]).read_text(encoding="utf-8"))
    roles = {artifact["role"] for artifact in manifest["artifacts"]}
    assert rc == 0
    assert "python_symbol_index_json" not in roles
    assert any(
        path.endswith(".python_symbol_index.json")
        for path in emitted["removed_profile_excluded_artifacts"]
    )
    assert not list(out.glob("*.python_symbol_index.json"))
