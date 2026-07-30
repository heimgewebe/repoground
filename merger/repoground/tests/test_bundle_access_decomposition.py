from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import typing

import pytest

from merger.repoground.core import artifact_source_access
from merger.repoground.core import bundle_access
from merger.repoground.core import symbol_index_access
from merger.repoground.core.bounded_artifact_read import (
    MAX_REGISTERED_ARTIFACT_BYTES,
    _descriptor_read_size,
    read_stable_regular_file_bytes,
)
from merger.repoground.core.manifest_snapshot import MAX_MANIFEST_BYTES


def test_symbol_index_source_type_hints_resolve() -> None:
    hints = typing.get_type_hints(symbol_index_access._load_symbol_index_source)

    assert "return" in hints


def test_descriptor_read_size_tracks_observed_file_not_hard_cap() -> None:
    assert _descriptor_read_size(128, 4 * 1024 * 1024) == 129
    assert _descriptor_read_size(4 * 1024 * 1024, 4 * 1024 * 1024) == (4 * 1024 * 1024) + 1


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_manifest(
    path: Path,
    artifacts: list[dict[str, object]],
    *,
    run_id: object = "run-1",
) -> Path:
    path.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "version": "1.0",
                "run_id": run_id,
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )
    return path


def _call_graph_record(
    path: str,
    *,
    raw: bytes | None = None,
    **metadata: object,
) -> dict[str, object]:
    record: dict[str, object] = {
        "role": "python_call_graph_json",
        "path": path,
    }
    if raw is not None:
        record.update({"bytes": len(raw), "sha256": _sha256(raw)})
    record.update(metadata)
    return record


@pytest.mark.parametrize(
    "metadata",
    [
        {"bytes": 2},
        {"sha256": "0" * 64},
        {"bytes": True, "sha256": "0" * 64},
        {"bytes": -1, "sha256": "0" * 64},
        {"bytes": 2, "sha256": "A" * 64},
    ],
)
def test_partial_or_malformed_integrity_metadata_fails_closed(
    tmp_path: Path,
    metadata: dict[str, object],
) -> None:
    artifact = tmp_path / "calls.json"
    artifact.write_bytes(b"{}")
    manifest = _write_manifest(
        tmp_path / "demo.bundle.manifest.json",
        [_call_graph_record(artifact.name, **metadata)],
    )

    result = bundle_access.find_references(manifest, "target")

    assert result["status"] == "invalid"
    assert result["error_code"] == "python_call_graph_json_integrity_unavailable"


def test_legacy_absent_integrity_pair_is_bounded_and_pinned_to_actual_hash(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "calls.json"
    artifact.write_bytes(b"{}")
    manifest = _write_manifest(
        tmp_path / "demo.bundle.manifest.json",
        [_call_graph_record(artifact.name)],
    )

    source, _artifact, failure, detail = (
        bundle_access._read_registered_artifact_source(
            manifest,
            "python_call_graph_json",
        )
    )

    assert failure is None
    assert detail is None
    assert source is not None
    assert source.fingerprint.size == 2
    assert source.fingerprint.artifact_sha256 == _sha256(b"{}")


def test_declared_oversize_is_rejected_before_artifact_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _write_manifest(
        tmp_path / "demo.bundle.manifest.json",
        [
            _call_graph_record(
                "not-created.json",
                bytes=MAX_REGISTERED_ARTIFACT_BYTES + 1,
                sha256="0" * 64,
            )
        ],
    )

    def forbidden_read(_path: Path):
        raise AssertionError("oversized declared artifact must not be opened")

    monkeypatch.setattr(
        artifact_source_access,
        "_read_stable_artifact_bytes",
        forbidden_read,
    )

    result = bundle_access.find_references(manifest, "target")

    assert result["status"] == "invalid"
    assert result["error_code"] == "python_call_graph_json_too_large"


def test_descriptor_reader_stops_at_explicit_byte_bound(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"12345")

    raw, metadata, failure, detail = read_stable_regular_file_bytes(
        artifact,
        max_bytes=4,
    )

    assert raw is None
    assert metadata is None
    assert failure == "too_large"
    assert detail is None


def test_descriptor_reader_rejects_symbolic_link(tmp_path: Path) -> None:
    target = tmp_path / "target.bin"
    linked = tmp_path / "linked.bin"
    target.write_bytes(b"outside")
    try:
        linked.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    raw, metadata, failure, detail = read_stable_regular_file_bytes(
        linked,
        max_bytes=1024,
    )

    assert raw is None
    assert metadata is None
    assert failure == "unreadable"
    assert detail


@pytest.mark.parametrize("path_value", ["../outside.json", "/outside.json"])
def test_registered_artifact_traversal_is_reported_precisely(
    tmp_path: Path,
    path_value: str,
) -> None:
    manifest = _write_manifest(
        tmp_path / "demo.bundle.manifest.json",
        [_call_graph_record(path_value, raw=b"{}")],
    )

    result = bundle_access.find_references(manifest, "target")

    assert result["status"] == "invalid"
    assert result["error_code"] == "python_call_graph_json_path_invalid"


def test_registered_artifact_symlink_escape_is_reported_precisely(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_bytes(b"{}")
    linked = tmp_path / "linked.json"
    try:
        linked.symlink_to(outside)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    manifest = _write_manifest(
        tmp_path / "demo.bundle.manifest.json",
        [_call_graph_record(linked.name, raw=b"{}")],
    )

    result = bundle_access.find_references(manifest, "target")

    assert result["status"] == "invalid"
    assert result["error_code"] == "python_call_graph_json_path_invalid"


def test_duplicate_registered_role_is_not_selected_by_order(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_bytes(b"{}")
    second.write_bytes(b"{}")
    manifest = _write_manifest(
        tmp_path / "demo.bundle.manifest.json",
        [
            _call_graph_record(first.name, raw=b"{}"),
            _call_graph_record(second.name, raw=b"{}"),
        ],
    )

    result = bundle_access.find_references(manifest, "target")

    assert result["status"] == "invalid"
    assert result["error_code"] == "python_call_graph_json_role_ambiguous"


@pytest.mark.parametrize("run_id", [None, "", 7])
def test_invalid_manifest_run_id_fails_before_artifact_selection(
    tmp_path: Path,
    run_id: object,
) -> None:
    manifest = _write_manifest(
        tmp_path / "demo.bundle.manifest.json",
        [],
        run_id=run_id,
    )

    result = bundle_access.find_references(manifest, "target")

    assert result["status"] == "invalid"
    assert result["error_code"] == "bundle_manifest_invalid"


def test_oversized_manifest_is_not_parsed_or_role_resolved(tmp_path: Path) -> None:
    manifest = tmp_path / "demo.bundle.manifest.json"
    prefix = (
        b'{"kind":"repolens.bundle.manifest","version":"1.0",'
        b'"run_id":"run-1","artifacts":[],"padding":"'
    )
    manifest.write_bytes(prefix + (b"x" * MAX_MANIFEST_BYTES) + b'"}')

    result = bundle_access.find_references(manifest, "target")

    assert result["status"] == "invalid"
    assert result["error_code"] == "bundle_manifest_too_large"


def test_citation_map_hash_drift_is_not_projected_as_evidence(
    tmp_path: Path,
) -> None:
    citation_map = tmp_path / "citation-map.jsonl"
    original = b'{"citation_id":"cit_0000000000000000"}\n'
    citation_map.write_bytes(original)
    manifest = _write_manifest(
        tmp_path / "demo.bundle.manifest.json",
        [
            {
                "role": "citation_map_jsonl",
                "path": citation_map.name,
                "bytes": len(original),
                "sha256": _sha256(original),
            }
        ],
    )
    replacement = b'{"citation_id":"cit_1111111111111111"}\n'
    assert len(replacement) == len(original)
    citation_map.write_bytes(replacement)

    by_chunk, by_range, status = bundle_access._load_citation_lookup(manifest)

    assert by_chunk == {}
    assert by_range == {}
    assert status["status"] == "invalid"
    assert status["error_code"] == "citation_map_jsonl_sha256_mismatch"


def test_path_exchange_after_descriptor_read_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "artifact.json"
    replacement = tmp_path / "replacement.json"
    artifact.write_bytes(b"generation-one")
    replacement.write_bytes(b"generation-two")
    original_lstat = os.lstat
    artifact_lstat_calls = 0
    exchanged = False

    def exchanging_lstat(path: object, *args: object, **kwargs: object):
        nonlocal artifact_lstat_calls, exchanged
        if os.fspath(path) == os.fspath(artifact):
            artifact_lstat_calls += 1
            if artifact_lstat_calls == 2:
                os.replace(replacement, artifact)
                exchanged = True
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", exchanging_lstat)

    raw, metadata, failure, _detail = read_stable_regular_file_bytes(
        artifact,
        max_bytes=1024,
    )

    assert exchanged is True
    assert raw is None
    assert metadata is None
    assert failure == "source_changed"


def test_manifest_hash_is_rechecked_after_artifact_read_when_metadata_is_spoofed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "calls.json"
    raw = b"{}"
    artifact.write_bytes(raw)
    manifest = _write_manifest(
        tmp_path / "demo.bundle.manifest.json",
        [_call_graph_record(artifact.name, raw=raw)],
    )
    original_manifest_stat = manifest.stat()
    original_manifest_reader = artifact_source_access._read_stable_regular_file_bytes
    original_artifact_reader = artifact_source_access._read_stable_artifact_bytes
    original_path_stat = Path.stat
    changed = False

    def changing_artifact_reader(path: Path):
        nonlocal changed
        result = original_artifact_reader(path)
        manifest.write_bytes(
            manifest.read_bytes().replace(b"run-1", b"run-2")
        )
        changed = True
        return result

    def spoofed_manifest_reader(path: Path, *, max_bytes: int = MAX_MANIFEST_BYTES):
        if path == manifest and changed:
            return manifest.read_bytes(), original_manifest_stat, None, None
        return original_manifest_reader(path, max_bytes=max_bytes)

    def spoofed_path_stat(path: Path, *args: object, **kwargs: object):
        if path == manifest and changed:
            return original_manifest_stat
        return original_path_stat(path, *args, **kwargs)

    monkeypatch.setattr(
        artifact_source_access,
        "_read_stable_artifact_bytes",
        changing_artifact_reader,
    )
    monkeypatch.setattr(
        artifact_source_access,
        "_read_stable_regular_file_bytes",
        spoofed_manifest_reader,
    )
    monkeypatch.setattr(Path, "stat", spoofed_path_stat)

    source, _artifact, failure, detail = (
        bundle_access._read_registered_artifact_source(
            manifest,
            "python_call_graph_json",
        )
    )

    assert changed is True
    assert source is None
    assert failure == "source_changed"
    assert detail is None
