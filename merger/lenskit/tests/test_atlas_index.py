import json

from merger.lenskit.atlas.registry import AtlasRegistry
from merger.lenskit.atlas.index import AtlasFTSIndex
from merger.lenskit.atlas.search import AtlasSearch
from merger.lenskit.atlas.paths import resolve_index_db_path, resolve_atlas_base_dir


def _make_registry(tmp_path):
    """Create a registry under a canonical-ish atlas layout so index/base paths align."""
    registry_path = tmp_path / "atlas" / "registry" / "atlas_registry.sqlite"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    return registry_path


def _write_inv(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _build_search_fixture(tmp_path):
    """Replicates the legacy search fixture and additionally builds an FTS index."""
    registry_path = _make_registry(tmp_path)
    registry = AtlasRegistry(registry_path)

    registry.register_machine("m1", "host1")
    registry.register_machine("m2", "host2")
    registry.register_root("r1", "m1", "abs_path", "/tmp/r1")
    registry.register_root("r2", "m2", "abs_path", "/tmp/r2")

    inv1 = tmp_path / "inv1.jsonl"
    _write_inv(inv1, [
        {"rel_path": "a/b/c.txt", "name": "c.txt", "ext": ".txt", "size_bytes": 100, "mtime": "2023-01-01T00:00:00Z"},
        {"rel_path": "a/d.md", "name": "d.md", "ext": ".md", "size_bytes": 200, "mtime": "2023-01-02T00:00:00Z"},
    ])
    inv2 = tmp_path / "inv2.jsonl"
    _write_inv(inv2, [
        {"rel_path": "a/b/c.txt", "name": "c.txt", "ext": ".txt", "size_bytes": 150, "mtime": "2023-01-03T12:00:00+00:00"},
        {"rel_path": "a/d.md", "name": "d.md", "ext": ".md", "size_bytes": 200, "mtime": "2023-01-02T00:00:00Z"},
        {"rel_path": "a/new.log", "name": "new.log", "ext": ".log", "size_bytes": 50, "mtime": "2023-01-04T00:00:00Z"},
    ])
    inv3 = tmp_path / "inv3.jsonl"
    _write_inv(inv3, [
        {"rel_path": "other/file.txt", "name": "file.txt", "ext": ".txt", "size_bytes": 300, "mtime": "2023-01-05T00:00:00Z"},
    ])

    registry.create_snapshot("s1", "m1", "r1", "hash1", "complete")
    registry.conn.execute("UPDATE snapshots SET created_at = '2023-01-01T00:00:00Z' WHERE snapshot_id = 's1'")
    registry.update_snapshot_artifacts("s1", {"inventory": str(inv1)})

    registry.create_snapshot("s2", "m1", "r1", "hash2", "complete")
    registry.conn.execute("UPDATE snapshots SET created_at = '2023-01-03T00:00:00Z' WHERE snapshot_id = 's2'")
    registry.update_snapshot_artifacts("s2", {"inventory": str(inv2)})

    registry.create_snapshot("s3", "m2", "r2", "hash3", "complete")
    registry.conn.execute("UPDATE snapshots SET created_at = '2023-01-05T00:00:00Z' WHERE snapshot_id = 's3'")
    registry.update_snapshot_artifacts("s3", {"inventory": str(inv3)})

    atlas_base = resolve_atlas_base_dir(registry_path)
    index_path = resolve_index_db_path(registry_path)
    with AtlasFTSIndex(index_path) as idx:
        for sid in ("s1", "s2", "s3"):
            idx.index_snapshot(registry.get_snapshot(sid), atlas_base)
    registry.close()
    return registry_path


def test_search_via_index_matches_legacy_semantics(tmp_path):
    registry_path = _build_search_fixture(tmp_path)
    searcher = AtlasSearch(registry_path)

    # The index exists and covers all snapshots, so these run through the index.
    assert len(searcher.search()) == 4

    res = searcher.search(query="c.txt")
    assert len(res) == 1
    assert res[0]["name"] == "c.txt"
    assert res[0]["size_bytes"] == 150  # latest snapshot s2

    assert len(searcher.search(machine_id="m2")) == 1
    assert len(searcher.search(root_id="r1")) == 3

    res = searcher.search(snapshot_id="s1")
    assert len(res) == 2
    for r in res:
        if r["name"] == "c.txt":
            assert r["size_bytes"] == 100

    assert len(searcher.search(ext=".md")) == 1
    assert len(searcher.search(ext="md")) == 1
    assert len(searcher.search(min_size=150, max_size=250)) == 2

    res = searcher.search(date_after="2023-01-03T00:00:00Z", root_id="r1")
    assert len(res) == 2
    res = searcher.search(date_before="2023-01-02T12:00:00Z", root_id="r1")
    assert len(res) == 1

    res = searcher.search(path_pattern="a/b/*.txt")
    assert len(res) == 1
    assert res[0]["name"] == "c.txt"

    res = searcher.search(name_pattern="*.log")
    assert len(res) == 1
    assert res[0]["name"] == "new.log"


def test_index_and_legacy_agree(tmp_path):
    """The index-backed and linear paths must produce identical result sets."""
    registry_path = _build_search_fixture(tmp_path)
    searcher = AtlasSearch(registry_path)

    def _key(rows):
        return sorted((r["snapshot_id"], r["rel_path"], r["size_bytes"]) for r in rows)

    for kwargs in [
        {},
        {"root_id": "r1"},
        {"ext": ".txt"},
        {"min_size": 150},
        {"query": "d"},
        {"path_pattern": "a/*"},
        {"all_snapshots": True},
    ]:
        via_index = searcher.search(use_index=True, **kwargs)
        via_linear = searcher.search(use_index=False, **kwargs)
        assert _key(via_index) == _key(via_linear), f"mismatch for {kwargs}"


def test_all_snapshots_returns_history(tmp_path):
    registry_path = _build_search_fixture(tmp_path)
    searcher = AtlasSearch(registry_path)

    # latest-only: r1 -> s2 (3 files), r2 -> s3 (1) = 4
    assert len(searcher.search()) == 4
    # historical: s1(2) + s2(3) + s3(1) = 6
    assert len(searcher.search(all_snapshots=True)) == 6


def test_latest_resolution(tmp_path):
    registry_path = _build_search_fixture(tmp_path)
    index_path = resolve_index_db_path(registry_path)
    with AtlasFTSIndex(index_path) as idx:
        latest = set(idx.latest_snapshot_ids())
        assert latest == {"s2", "s3"}
        latest_r1 = idx.latest_snapshot_ids(root_id="r1")
        assert latest_r1 == ["s2"]


def test_reindex_is_idempotent(tmp_path):
    registry_path = _build_search_fixture(tmp_path)
    index_path = resolve_index_db_path(registry_path)
    atlas_base = resolve_atlas_base_dir(registry_path)
    with AtlasRegistry(registry_path) as registry:
        snap = registry.get_snapshot("s2")
        with AtlasFTSIndex(index_path) as idx:
            before = idx.stats()["indexed_files"]
            idx.index_snapshot(snap, atlas_base)  # re-index
            idx.index_snapshot(snap, atlas_base)  # again
            after = idx.stats()["indexed_files"]
            assert before == after  # no duplicate rows


def test_remove_snapshot(tmp_path):
    registry_path = _build_search_fixture(tmp_path)
    index_path = resolve_index_db_path(registry_path)
    with AtlasFTSIndex(index_path) as idx:
        assert idx.is_snapshot_indexed("s1")
        idx.remove_snapshot("s1")
        assert not idx.is_snapshot_indexed("s1")
        # s1's rows are gone, but the others remain.
        assert idx.is_snapshot_indexed("s2")


def test_rebuild_from_registry(tmp_path):
    registry_path = _build_search_fixture(tmp_path)
    index_path = resolve_index_db_path(registry_path)
    atlas_base = resolve_atlas_base_dir(registry_path)
    with AtlasRegistry(registry_path) as registry:
        with AtlasFTSIndex(index_path) as idx:
            # Corrupt the index, then rebuild.
            idx.remove_snapshot("s2")
            idx.remove_snapshot("s3")
            totals = idx.rebuild_from_registry(registry, atlas_base)
            assert totals["snapshots"] == 3
            assert idx.is_snapshot_indexed("s2")
            assert idx.is_snapshot_indexed("s3")
            assert idx.stats()["indexed_files"] == 2 + 3 + 1


def test_content_search_via_index(tmp_path):
    registry_path = _make_registry(tmp_path)
    registry = AtlasRegistry(registry_path)
    registry.register_machine("m1", "host1")

    root_dir = tmp_path / "test_root"
    root_dir.mkdir()
    (root_dir / "file1.txt").write_text(
        "Hello world\nThis is a test file for content search.\nGoodbye!", encoding="utf-8"
    )
    (root_dir / "file2.txt").write_text(
        "Another file\nNo interesting content here.\n", encoding="utf-8"
    )
    (root_dir / "not_text.bin").write_bytes(b"\x00\x01\x02")

    registry.register_root("r1", "m1", "abs_path", str(root_dir))

    inv = tmp_path / "inv_content.jsonl"
    _write_inv(inv, [
        {"rel_path": "file1.txt", "name": "file1.txt", "size_bytes": 100, "is_text": True},
        {"rel_path": "file2.txt", "name": "file2.txt", "size_bytes": 100, "is_text": True},
        {"rel_path": "not_text.bin", "name": "not_text.bin", "size_bytes": 10, "is_text": False},
    ])

    registry.create_snapshot("s1", "m1", "r1", "hash1", "complete")
    registry.update_snapshot_artifacts("s1", {"inventory": str(inv), "content": "content.json"})

    atlas_base = resolve_atlas_base_dir(registry_path)
    index_path = resolve_index_db_path(registry_path)
    with AtlasFTSIndex(index_path) as idx:
        stats = idx.index_snapshot(
            registry.get_snapshot("s1"), atlas_base,
            root_value=str(root_dir), index_content=True,
        )
        assert stats["content_indexed"] == 2  # the two text files
        assert idx.snapshot_has_content("s1")
    registry.close()

    searcher = AtlasSearch(registry_path)

    res = searcher.search(content_query="test file")
    assert len(res) == 1
    assert res[0]["name"] == "file1.txt"
    assert "This is a test file for content search." in res[0]["content_snippet"]

    res = searcher.search(content_query="interesting")
    assert len(res) == 1
    assert res[0]["name"] == "file2.txt"

    # Token that does not appear -> no matches.
    res = searcher.search(content_query="nonexistentword")
    assert len(res) == 0
