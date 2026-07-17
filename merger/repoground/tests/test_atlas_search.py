import json

from merger.repoground.atlas.search import AtlasSearch
from merger.repoground.atlas.registry import AtlasRegistry

def test_atlas_search(tmp_path):
    registry_path = tmp_path / "registry.sqlite"
    registry = AtlasRegistry(registry_path)

    registry.register_machine("m1", "host1")
    registry.register_machine("m2", "host2")
    registry.register_root("r1", "m1", "abs_path", "/tmp/r1")
    registry.register_root("r2", "m2", "abs_path", "/tmp/r2")

    # Create dummy inventory for r1, older snapshot
    inv_path1 = tmp_path / "inv1.jsonl"
    with open(inv_path1, "w") as f:
        f.write(json.dumps({"rel_path": "a/b/c.txt", "name": "c.txt", "ext": ".txt", "size_bytes": 100, "mtime": "2023-01-01T00:00:00Z"}) + "\n")
        f.write(json.dumps({"rel_path": "a/d.md", "name": "d.md", "ext": ".md", "size_bytes": 200, "mtime": "2023-01-02T00:00:00Z"}) + "\n")

    # Create dummy inventory for r1, newer snapshot
    inv_path2 = tmp_path / "inv2.jsonl"
    with open(inv_path2, "w") as f:
        f.write(json.dumps({"rel_path": "a/b/c.txt", "name": "c.txt", "ext": ".txt", "size_bytes": 150, "mtime": "2023-01-03T12:00:00+00:00"}) + "\n")
        f.write(json.dumps({"rel_path": "a/d.md", "name": "d.md", "ext": ".md", "size_bytes": 200, "mtime": "2023-01-02T00:00:00Z"}) + "\n")
        f.write(json.dumps({"rel_path": "a/new.log", "name": "new.log", "ext": ".log", "size_bytes": 50, "mtime": "2023-01-04T00:00:00Z"}) + "\n")

    # Create dummy inventory for r2
    inv_path3 = tmp_path / "inv3.jsonl"
    with open(inv_path3, "w") as f:
        f.write(json.dumps({"rel_path": "other/file.txt", "name": "file.txt", "ext": ".txt", "size_bytes": 300, "mtime": "2023-01-05T00:00:00Z"}) + "\n")

    registry.create_snapshot("s1", "m1", "r1", "hash1", "complete")
    # For test purpose we override the date to make it explicitly older
    registry.conn.execute("UPDATE snapshots SET created_at = '2023-01-01T00:00:00Z' WHERE snapshot_id = 's1'")
    registry.update_snapshot_artifacts("s1", {"inventory": str(inv_path1)})

    registry.create_snapshot("s2", "m1", "r1", "hash2", "complete")
    registry.conn.execute("UPDATE snapshots SET created_at = '2023-01-03T00:00:00Z' WHERE snapshot_id = 's2'")
    registry.update_snapshot_artifacts("s2", {"inventory": str(inv_path2)})

    registry.create_snapshot("s3", "m2", "r2", "hash3", "complete")
    registry.conn.execute("UPDATE snapshots SET created_at = '2023-01-05T00:00:00Z' WHERE snapshot_id = 's3'")
    registry.update_snapshot_artifacts("s3", {"inventory": str(inv_path3)})

    registry.close()

    searcher = AtlasSearch(registry_path)

    # Test basic search - should return latest snapshot for r1 (3 files) and r2 (1 file)
    res = searcher.search()
    assert len(res) == 4

    # Test query
    res = searcher.search(query="c.txt")
    assert len(res) == 1
    assert res[0]["name"] == "c.txt"
    assert res[0]["size_bytes"] == 150 # From latest snapshot s2

    # Test scoping by machine
    res = searcher.search(machine_id="m2")
    assert len(res) == 1
    assert res[0]["name"] == "file.txt"

    # Test scoping by root
    res = searcher.search(root_id="r1")
    assert len(res) == 3

    # Test scoping by snapshot (older snapshot explicitly)
    res = searcher.search(snapshot_id="s1")
    assert len(res) == 2
    for r in res:
        if r["name"] == "c.txt":
            assert r["size_bytes"] == 100

    # Test ext
    res = searcher.search(ext=".md")
    assert len(res) == 1
    assert res[0]["name"] == "d.md"

    # Test ext without dot
    res = searcher.search(ext="md")
    assert len(res) == 1
    assert res[0]["name"] == "d.md"

    # Test size
    res = searcher.search(min_size=150, max_size=250)
    assert len(res) == 2 # c.txt (150) and d.md (200)

    # Test date filtering with Z and +00:00 timezone formats
    # c.txt in s2 is "2023-01-03T12:00:00+00:00"
    res = searcher.search(date_after="2023-01-03T00:00:00Z", root_id="r1")
    assert len(res) == 2 # c.txt and new.log

    res = searcher.search(date_before="2023-01-02T12:00:00Z", root_id="r1")
    assert len(res) == 1 # d.md is exactly 2023-01-02T00:00:00Z

    # Test glob filtering
    res = searcher.search(path_pattern="a/b/*.txt")
    assert len(res) == 1
    assert res[0]["name"] == "c.txt"

    res = searcher.search(name_pattern="*.log")
    assert len(res) == 1
    assert res[0]["name"] == "new.log"

def test_atlas_content_search(tmp_path):
    registry_path = tmp_path / "registry.sqlite"
    registry = AtlasRegistry(registry_path)

    registry.register_machine("m1", "host1")

    # Create an actual file for content search
    root_dir = tmp_path / "test_root"
    root_dir.mkdir()

    file1_path = root_dir / "file1.txt"
    with open(file1_path, "w", encoding="utf-8") as f:
        f.write("Hello world\nThis is a test file for content search.\nGoodbye!")

    file2_path = root_dir / "file2.txt"
    with open(file2_path, "w", encoding="utf-8") as f:
        f.write("Another file\nNo interesting content here.\n")

    # Large file should be skipped
    large_file_path = root_dir / "large.txt"
    # Actually create the large file logic by just adding a smaller file
    # and relying on the metadata size being faked, but let's actually just make sure it exists
    with open(large_file_path, "w", encoding="utf-8") as f:
        f.write("A" * 10)
        f.write("test file")

    # Not a text file according to flag
    not_text_path = root_dir / "not_text.bin"
    with open(not_text_path, "wb") as f:
        f.write(b"\x00\x01\x02")

    registry.register_root("r1", "m1", "abs_path", str(root_dir))

    # Create dummy inventory
    inv_path = tmp_path / "inv_content.jsonl"
    with open(inv_path, "w") as f:
        f.write(json.dumps({"rel_path": "file1.txt", "name": "file1.txt", "size_bytes": 100, "is_text": True}) + "\n")
        f.write(json.dumps({"rel_path": "file2.txt", "name": "file2.txt", "size_bytes": 100, "is_text": True}) + "\n")
        f.write(json.dumps({"rel_path": "large.txt", "name": "large.txt", "size_bytes": 20 * 1024 * 1024 + 1024, "is_text": True}) + "\n")
        f.write(json.dumps({"rel_path": "not_text.bin", "name": "not_text.bin", "size_bytes": 10, "is_text": False}) + "\n")

    registry.create_snapshot("s1", "m1", "r1", "hash1", "complete")
    registry.update_snapshot_artifacts("s1", {"inventory": str(inv_path)})
    registry.close()

    searcher = AtlasSearch(registry_path)

    # Test content search
    res = searcher.search(content_query="test file")
    assert len(res) == 1
    assert res[0]["name"] == "file1.txt"
    assert "This is a test file for content search." in res[0]["content_snippet"]

    res = searcher.search(content_query="interesting")
    assert len(res) == 1
    assert res[0]["name"] == "file2.txt"
    assert "No interesting content here." in res[0]["content_snippet"]

    # Should skip non-text file
    res = searcher.search(content_query="\x00")
    assert len(res) == 0
