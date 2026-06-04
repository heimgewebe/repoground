"""Functional tests for `atlas index rebuild` and `atlas index stats`.

These tests call `run_atlas_index` directly (no subprocess) so they work
without a full CLI subprocess harness. The function resolves its registry path
from CWD via `Path("atlas/registry/atlas_registry.sqlite").resolve()`, so each
test uses `monkeypatch.chdir(tmp_path)` and creates the atlas layout there.
"""

import argparse
import json
from pathlib import Path

from merger.lenskit.atlas.registry import AtlasRegistry
from merger.lenskit.cli.cmd_atlas import run_atlas_index


def _make_args(**kwargs) -> argparse.Namespace:
    ns = argparse.Namespace()
    ns.index_command = kwargs.get("index_command", None)
    return ns


def _setup_atlas_with_snapshot(tmp_path: Path, files: dict) -> Path:
    """Create an atlas layout under tmp_path with one complete snapshot."""
    registry_path = tmp_path / "atlas" / "registry" / "atlas_registry.sqlite"
    registry_path.parent.mkdir(parents=True, exist_ok=True)

    inv_path = tmp_path / "atlas" / "inventory.jsonl"
    with open(inv_path, "w", encoding="utf-8") as f:
        for rel_path, size in files.items():
            f.write(json.dumps({
                "rel_path": rel_path,
                "name": Path(rel_path).name,
                "ext": Path(rel_path).suffix,
                "size_bytes": size,
            }) + "\n")

    with AtlasRegistry(registry_path) as reg:
        reg.register_machine("m1", "host1")
        reg.register_root("r1", "m1", "abs_path", str(tmp_path / "root"))
        reg.create_snapshot("s1", "m1", "r1", "hash1", "complete")
        reg.update_snapshot_artifacts("s1", {"inventory": "inventory.jsonl"})

    return registry_path


def test_atlas_index_stats_no_index(tmp_path, monkeypatch, capsys):
    """stats without an existing index exits 0 and reports that no index was found."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "atlas" / "registry").mkdir(parents=True)

    exit_code = run_atlas_index(_make_args(index_command="stats"))

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No Atlas FTS index found" in captured.out
    assert "atlas index rebuild" in captured.out


def test_atlas_index_rebuild_creates_index_and_counts_correctly(tmp_path, monkeypatch, capsys):
    """rebuild with a complete snapshot creates fts.sqlite and counts files correctly."""
    _setup_atlas_with_snapshot(tmp_path, {
        "a.txt": 100,
        "b/c.md": 200,
        "d.log": 50,
    })
    monkeypatch.chdir(tmp_path)

    exit_code = run_atlas_index(_make_args(index_command="rebuild"))

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "snapshots indexed: 1" in captured.out
    assert "files indexed:     3" in captured.out

    index_path = tmp_path / "atlas" / "indexes" / "fts.sqlite"
    assert index_path.exists(), "fts.sqlite was not created"


def test_atlas_index_stats_after_rebuild(tmp_path, monkeypatch, capsys):
    """stats after rebuild shows correct snapshot and file counts."""
    _setup_atlas_with_snapshot(tmp_path, {
        "file1.txt": 10,
        "file2.txt": 20,
    })
    monkeypatch.chdir(tmp_path)

    # Rebuild first.
    run_atlas_index(_make_args(index_command="rebuild"))
    capsys.readouterr()  # discard rebuild output

    exit_code = run_atlas_index(_make_args(index_command="stats"))

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Atlas FTS index statistics" in captured.out
    assert "indexed snapshots:  1" in captured.out
    assert "indexed files:      2" in captured.out


def test_atlas_index_unknown_command_returns_nonzero(tmp_path, monkeypatch, capsys):
    """An unknown index subcommand exits with code 1."""
    monkeypatch.chdir(tmp_path)
    exit_code = run_atlas_index(_make_args(index_command="frobnicate"))
    assert exit_code == 1
