from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from merger.repoground.core import call_graph_impact_index as impact_index
from merger.repoground.core.readonly_adapter import MAX_ARTIFACT_BYTES
from merger.repoground.tests.test_agent_impact_adapter import _impact_adapter


def _artifact_path(manifest_path: Path, role: str) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for artifact in manifest["artifacts"]:
        if artifact.get("role") == role:
            return manifest_path.parent / artifact["path"]
    raise AssertionError(f"missing role: {role}")


def _target_symbols() -> list[dict[str, str]]:
    return [
        {
            "id": "sym-demo",
            "name": "hello_adapter",
            "qualified_name": "demo.hello_adapter",
        }
    ]


def _refresh_manifest_artifact(manifest_path: Path, role: str, artifact_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = artifact_path.read_bytes()
    for artifact in manifest["artifacts"]:
        if artifact.get("role") == role:
            artifact["bytes"] = len(payload)
            artifact["sha256"] = hashlib.sha256(payload).hexdigest()
            break
    else:  # pragma: no cover - fixture contract guard
        raise AssertionError(f"missing role: {role}")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_large_call_graph_projects_without_widening_generic_payload_limit(
    tmp_path: Path,
) -> None:
    adapter, bundle, _config = _impact_adapter(tmp_path)
    manifest_path = Path(bundle["manifest"])
    call_graph_path = _artifact_path(manifest_path, "python_call_graph_json")
    call_graph = json.loads(call_graph_path.read_text(encoding="utf-8"))
    call_graph["padding"] = "x" * (MAX_ARTIFACT_BYTES + 1024)
    call_graph_path.write_text(
        json.dumps(call_graph, separators=(",", ":")),
        encoding="utf-8",
    )
    _refresh_manifest_artifact(
        manifest_path,
        "python_call_graph_json",
        call_graph_path,
    )
    impact_index.clear_call_graph_impact_index_cache()

    generic = adapter.artifact_get("demo", "python_call_graph_json")
    assert generic["status"] == "blocked"
    assert generic["error_code"] == "artifact_too_large"

    result = adapter.agent_impact_context(
        "demo",
        target_symbol="demo.hello_adapter",
        mode="impact",
        max_items=10,
        include_query_context=False,
    )
    statuses = {
        item["source"]: item for item in result.get("source_statuses", [])
    }
    assert statuses["python_call_graph_json"]["status"] == "available"
    assert result["call_graph_projection"]["source_call_count"] == 2
    assert result["call_graph_projection"]["selected_call_count"] == 2
    assert not any(
        gap.get("reason") == "source_unavailable"
        and gap.get("source") == "python_call_graph_json"
        for gap in result.get("gaps", [])
    )


def test_projection_cache_reuses_verified_offset_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _adapter, bundle, _config = _impact_adapter(tmp_path)
    impact_index.clear_call_graph_impact_index_cache()
    monkeypatch.delenv("REPOGROUND_CACHE_VALIDATION", raising=False)

    first = impact_index.project_call_graph_for_impact(
        bundle["manifest"],
        _target_symbols(),
    )
    assert first["status"] == "available"

    def unexpected_rehash(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("warm projection cache unexpectedly rehashed full artifact")

    monkeypatch.setattr(impact_index, "_hash_stable_artifact", unexpected_rehash)
    second = impact_index.project_call_graph_for_impact(
        bundle["manifest"],
        _target_symbols(),
    )
    assert second["status"] == "available"
    assert second["projection"]["selected_call_count"] == 2


def test_projection_cache_invalidates_after_artifact_tamper(tmp_path: Path) -> None:
    _adapter, bundle, _config = _impact_adapter(tmp_path)
    impact_index.clear_call_graph_impact_index_cache()
    first = impact_index.project_call_graph_for_impact(
        bundle["manifest"],
        _target_symbols(),
    )
    assert first["status"] == "available"

    manifest_path = Path(bundle["manifest"])
    call_graph_path = _artifact_path(manifest_path, "python_call_graph_json")
    call_graph_path.write_bytes(call_graph_path.read_bytes() + b" ")

    second = impact_index.project_call_graph_for_impact(
        bundle["manifest"],
        _target_symbols(),
    )
    assert second["status"] == "blocked"
    assert second["error_code"] == "python_call_graph_impact_projection_blocked"
    assert "does not match the bundle manifest" in second["error"]


def test_projection_blocks_same_size_hash_tamper(tmp_path: Path) -> None:
    _adapter, bundle, _config = _impact_adapter(tmp_path)
    impact_index.clear_call_graph_impact_index_cache()
    manifest_path = Path(bundle["manifest"])
    call_graph_path = _artifact_path(manifest_path, "python_call_graph_json")
    payload = bytearray(call_graph_path.read_bytes())
    assert payload[-1:] == b"\n"
    payload[-1:] = b" "
    call_graph_path.write_bytes(payload)

    result = impact_index.project_call_graph_for_impact(
        bundle["manifest"],
        _target_symbols(),
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "python_call_graph_impact_projection_blocked"
    assert "content hash does not match" in result["error"]


def test_projection_candidate_limit_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _adapter, bundle, _config = _impact_adapter(tmp_path)
    impact_index.clear_call_graph_impact_index_cache()
    monkeypatch.setattr(impact_index, "MAX_PROJECTED_CALLS", 1)

    result = impact_index.project_call_graph_for_impact(
        bundle["manifest"],
        _target_symbols(),
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "python_call_graph_impact_projection_blocked"
    assert "bounded candidate call count" in result["error"]


def test_projection_byte_limit_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _adapter, bundle, _config = _impact_adapter(tmp_path)
    impact_index.clear_call_graph_impact_index_cache()
    monkeypatch.setattr(impact_index, "MAX_PROJECTED_BYTES", 1)

    result = impact_index.project_call_graph_for_impact(
        bundle["manifest"],
        _target_symbols(),
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "python_call_graph_impact_projection_blocked"
    assert "bounded projected byte count" in result["error"]


def test_manifest_limit_fails_closed(tmp_path: Path) -> None:
    _adapter, bundle, _config = _impact_adapter(tmp_path)
    manifest_path = Path(bundle["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["padding"] = "x" * impact_index.MAX_MANIFEST_BYTES
    manifest_path.write_text(
        json.dumps(manifest, separators=(",", ":")),
        encoding="utf-8",
    )
    impact_index.clear_call_graph_impact_index_cache()

    result = impact_index.project_call_graph_for_impact(
        manifest_path,
        _target_symbols(),
    )
    assert result["status"] == "blocked"
    assert result["error_code"] == "python_call_graph_impact_projection_blocked"
    assert "manifest exceeds bounded size" in result["error"]
