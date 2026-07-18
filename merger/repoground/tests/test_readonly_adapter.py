from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from merger.repoground.cli.main import main
from merger.repoground.core import readonly_adapter as adapter_module
from merger.repoground.core.readonly_adapter import (
    RepoGroundReadonlyAdapter,
    RepoGroundReadonlyAdapterError,
)
from merger.repoground.tests.test_resolved_evidence_query import (
    _build_resolved_bundle,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "merger/repoground/contracts/repobrief-readonly-adapter-config.v1.schema.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seal_existing_artifact(bundle: dict, role: str) -> None:
    manifest = bundle["manifest"]
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for artifact in data["artifacts"]:
        if artifact.get("role") != role:
            continue
        path = manifest.parent / artifact["path"]
        artifact["bytes"] = path.stat().st_size
        artifact["sha256"] = _sha(path)
        manifest.write_text(json.dumps(data), encoding="utf-8")
        return
    raise AssertionError(f"fixture artifact missing: {role}")


def _add_artifact(bundle: dict, role: str, filename: str, content: str) -> Path:
    manifest = bundle["manifest"]
    path = manifest.parent / filename
    path.write_text(content, encoding="utf-8")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["artifacts"].append(
        {
            "role": role,
            "path": filename,
            "content_type": "application/json" if filename.endswith(".json") else "text/markdown",
            "bytes": path.stat().st_size,
            "sha256": _sha(path),
        }
    )
    manifest.write_text(json.dumps(data), encoding="utf-8")
    return path


def _adapter(tmp_path: Path) -> tuple[RepoGroundReadonlyAdapter, dict, Path]:
    bundle = _build_resolved_bundle(tmp_path)
    _seal_existing_artifact(bundle, "sqlite_index")
    _add_artifact(
        bundle,
        "agent_reading_pack",
        "demo.agent_reading_pack.md",
        "# Reading pack\n\nThe canonical hello lives in brief.md.\n",
    )
    _add_artifact(
        bundle,
        "python_symbol_index_json",
        "demo.python_symbol_index.json",
        json.dumps(
            {
                "kind": "lenskit.python_symbol_index",
                "language": "python",
                "symbols": [
                    {
                        "id": "sym-1",
                        "kind": "function",
                        "name": "hello_adapter",
                        "qualified_name": "demo.hello_adapter",
                        "module": "demo",
                        "path": "src/demo.py",
                        "start_line": 3,
                        "end_line": 5,
                        "range_ref": None,
                        "decorators": [],
                    }
                ],
            }
        )
        + "\n",
    )
    _add_artifact(
        bundle,
        "post_emit_health",
        "demo.bundle_health.post.json",
        '{"status":"pass"}\n',
    )
    config = tmp_path / "adapter.json"
    config_data = {
        "kind": "repobrief.readonly_adapter_config",
        "version": "1.0",
        "allowed_roots": ["."],
        "snapshots": [{"id": "demo", "manifest": bundle["manifest"].name}],
    }
    config.write_text(json.dumps(config_data), encoding="utf-8")
    return RepoGroundReadonlyAdapter.from_config(config), bundle, config


def test_config_matches_schema(tmp_path: Path) -> None:
    _adapter_instance, _bundle, config = _adapter(tmp_path)
    jsonschema.validate(
        json.loads(config.read_text(encoding="utf-8")),
        json.loads(SCHEMA.read_text(encoding="utf-8")),
    )


def test_adapter_exposes_only_registered_manifest_identity(tmp_path: Path) -> None:
    adapter, bundle, _config = _adapter(tmp_path)

    assert adapter.manifest_for("demo") == bundle["manifest"].resolve()
    with pytest.raises(RepoGroundReadonlyAdapterError, match="not registered"):
        adapter.manifest_for("missing")


def test_adapter_lists_only_explicit_snapshots(tmp_path: Path) -> None:
    adapter, bundle, _config = _adapter(tmp_path)
    other = tmp_path / "unregistered.bundle.manifest.json"
    other.write_text(bundle["manifest"].read_text(encoding="utf-8"), encoding="utf-8")

    result = adapter.snapshot_list()

    assert result["status"] == "available"
    assert result["snapshot_count"] == 1
    assert result["snapshots"][0]["snapshot_id"] == "demo"
    assert result["discovery"] == "explicit_config_only"
    assert str(other) not in json.dumps(result)


def test_adapter_rejects_manifest_outside_allowed_root(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside.bundle.manifest.json"
    outside.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "run_id": "outside",
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )
    config = root / "adapter.json"
    config.write_text(
        json.dumps(
            {
                "kind": "repobrief.readonly_adapter_config",
                "version": "1.0",
                "allowed_roots": ["."],
                "snapshots": [{"id": "outside", "manifest": "../outside.bundle.manifest.json"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RepoGroundReadonlyAdapterError, match="escapes allowed roots"):
        RepoGroundReadonlyAdapter.from_config(config)


def test_adapter_reads_integrity_checked_artifact_and_synthetic_availability(
    tmp_path: Path,
) -> None:
    adapter, _bundle, _config = _adapter(tmp_path)

    pack = adapter.workbench_artifact_get("demo", "agent_reading_pack")
    availability = adapter.runtime_artifact_get("demo", "availability_model")

    assert pack["status"] == "available"
    assert "canonical hello" in pack["content_text"]
    assert pack["content_sha256"] == pack["artifact"]["sha256"]
    assert availability["status"] == "available"
    assert availability["synthetic_projection"] is True
    assert availability["content_json"]["kind"] == "repobrief.snapshot_availability"


def test_adapter_blocks_integrity_drift(tmp_path: Path) -> None:
    adapter, bundle, _config = _adapter(tmp_path)
    pack_path = bundle["manifest"].parent / "demo.agent_reading_pack.md"
    pack_path.write_text("tampered\n", encoding="utf-8")

    result = adapter.artifact_get("demo", "agent_reading_pack")

    assert result["status"] == "blocked"
    assert result["error_code"] == "artifact_integrity_mismatch"


def test_adapter_queries_prebuilt_index_and_symbol_index_without_writes(
    tmp_path: Path,
) -> None:
    adapter, bundle, _config = _adapter(tmp_path)
    before = {path.name: _sha(path) for path in tmp_path.iterdir() if path.is_file()}

    query = adapter.query_existing_index("demo", "hello", k=5)
    symbols = adapter.symbol_search("demo", "hello_adapter", k=5)

    after = {path.name: _sha(path) for path in tmp_path.iterdir() if path.is_file()}
    assert query["status"] == "available"
    assert query["query"]["query_result"]["count"] == 1
    assert symbols["status"] == "available"
    assert symbols["symbol_search"]["hits"][0]["path"] == "src/demo.py"
    assert before == after
    assert not any(
        path.exists()
        for suffix in ("-wal", "-shm", "-journal")
        for path in [bundle["index_path"].with_name(bundle["index_path"].name + suffix)]
    )


def test_adapter_blocks_tampered_sqlite_index_before_query(tmp_path: Path) -> None:
    adapter, bundle, _config = _adapter(tmp_path)
    with bundle["index_path"].open("ab") as handle:
        handle.write(b"tampered")

    result = adapter.query_existing_index("demo", "hello", k=5)

    assert result["status"] == "blocked"
    assert result["error_code"] == "artifact_integrity_mismatch"
    assert "query" not in result


def test_adapter_blocks_index_changed_during_delegated_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, bundle, _config = _adapter(tmp_path)
    original = adapter_module.bundle_access.query_existing_index

    def mutate_after_query(*args, **kwargs):
        result = original(*args, **kwargs)
        with bundle["index_path"].open("ab") as handle:
            handle.write(b"changed-after-read")
        return result

    monkeypatch.setattr(
        adapter_module.bundle_access,
        "query_existing_index",
        mutate_after_query,
    )

    result = adapter.query_existing_index("demo", "hello", k=5)

    assert result["status"] == "blocked"
    assert result["error_code"] == "artifact_integrity_mismatch"
    assert "query" not in result
    assert result["index_integrity_preflight"]["status"] == "available"
    assert result["index_integrity_postflight"]["status"] == "blocked"


def test_adapter_blocks_tampered_symbol_index_before_search(tmp_path: Path) -> None:
    adapter, bundle, _config = _adapter(tmp_path)
    symbol_path = bundle["manifest"].parent / "demo.python_symbol_index.json"
    symbol_path.write_text(json.dumps({"symbols": []}) + "\n", encoding="utf-8")

    result = adapter.symbol_search("demo", "hello_adapter", k=5)

    assert result["status"] == "blocked"
    assert result["error_code"] == "artifact_integrity_mismatch"
    assert "symbol_search" not in result

def test_adapter_dispatch_fails_closed_for_unknown_action(tmp_path: Path) -> None:
    adapter, _bundle, _config = _adapter(tmp_path)

    result = adapter.dispatch({"action": "git_fetch", "snapshot_id": "demo"})

    assert result["status"] == "invalid"
    assert result["error_code"] == "adapter_request_invalid"
    assert "git_fetch" in result["error"]
    assert "git_fetch" in result["mutation_boundary"]["forbidden_operations"]


def test_adapter_cli_list_and_call(tmp_path: Path, capsys) -> None:
    _adapter_instance, _bundle, config = _adapter(tmp_path)
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"action": "symbol_search", "snapshot_id": "demo", "query": "hello_adapter"}),
        encoding="utf-8",
    )

    assert main(["repobrief", "adapter", "list", "--config", str(config)]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["snapshot_count"] == 1

    assert main(
        [
            "repobrief",
            "adapter",
            "call",
            "--config",
            str(config),
            "--request",
            str(request),
        ]
    ) == 0
    called = json.loads(capsys.readouterr().out)
    assert called["symbol_search"]["hits"][0]["name"] == "hello_adapter"
