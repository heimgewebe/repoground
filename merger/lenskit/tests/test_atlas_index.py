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


def _build_content_index(tmp_path, files):
    """Build a content-mode snapshot from {rel_path: text} and index it.

    Returns (searcher, registry_path). All files are treated as text.
    """
    registry_path = _make_registry(tmp_path)
    registry = AtlasRegistry(registry_path)
    registry.register_machine("m1", "host1")

    root_dir = tmp_path / "content_root"
    root_dir.mkdir()
    records = []
    for rel_path, text in files.items():
        fpath = root_dir / rel_path
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(text, encoding="utf-8")
        records.append({
            "rel_path": rel_path,
            "name": fpath.name,
            "ext": fpath.suffix,
            "size_bytes": len(text.encode("utf-8")),
            "is_text": True,
        })

    registry.register_root("r1", "m1", "abs_path", str(root_dir))
    inv = tmp_path / "inv_content.jsonl"
    _write_inv(inv, records)
    registry.create_snapshot("s1", "m1", "r1", "hash1", "complete")
    registry.update_snapshot_artifacts("s1", {"inventory": str(inv), "content": "content.json"})

    atlas_base = resolve_atlas_base_dir(registry_path)
    index_path = resolve_index_db_path(registry_path)
    with AtlasFTSIndex(index_path) as idx:
        idx.index_snapshot(
            registry.get_snapshot("s1"), atlas_base,
            root_value=str(root_dir), index_content=True,
        )
    registry.close()
    return AtlasSearch(registry_path), registry_path


def _content_keys(rows):
    return sorted((r["snapshot_id"], r["rel_path"]) for r in rows)


# --- Regression: the index-backed content search must never lose a hit that
# --- the linear (live-filesystem substring) path would find (ADR-009 invariant).

def test_content_subtoken_substring_not_lost(tmp_path):
    """'oob' is a substring of 'foobar' but not an FTS token of it.

    FTS token-narrowing must NOT drop this hit before live confirmation.
    """
    searcher, _ = _build_content_index(tmp_path, {"a.txt": "foobar baz"})

    via_linear = searcher.search(use_index=False, content_query="oob")
    via_index = searcher.search(use_index=True, content_query="oob")

    assert _content_keys(via_linear) == [("s1", "a.txt")]
    assert _content_keys(via_index) == _content_keys(via_linear)


def test_content_unicode_query_not_lost(tmp_path):
    """ASCII tokenisation must not destroy a Unicode substring hit."""
    searcher, _ = _build_content_index(
        tmp_path, {"u.txt": "Überraschung für Müller heute"}
    )

    via_linear = searcher.search(use_index=False, content_query="für Müller")
    via_index = searcher.search(use_index=True, content_query="für Müller")

    assert _content_keys(via_linear) == [("s1", "u.txt")]
    assert _content_keys(via_index) == _content_keys(via_linear)


def test_content_punctuation_query_not_lost(tmp_path):
    """Punctuation-heavy / operator-like queries stay equivalent across paths."""
    searcher, _ = _build_content_index(
        tmp_path,
        {
            "code.txt": "C++ parser uses foo-bar paths",
            "noise.txt": "completely unrelated content",
        },
    )

    for q in ("C++", "foo-bar", "foo-bar paths"):
        via_linear = searcher.search(use_index=False, content_query=q)
        via_index = searcher.search(use_index=True, content_query=q)
        assert _content_keys(via_index) == _content_keys(via_linear), f"mismatch for {q!r}"
    # sanity: the queries above actually hit code.txt and nobody else
    assert _content_keys(searcher.search(content_query="foo-bar")) == [("s1", "code.txt")]


def test_content_index_linear_equivalence_matrix(tmp_path):
    """Broad equivalence sweep of index vs. linear content search."""
    searcher, _ = _build_content_index(
        tmp_path,
        {
            "doc1.txt": "the quick brown fox jumps over the lazy dog",
            "doc2.md": "uninteresting prefixes: interesting is inside uninteresting",
            "doc3.log": "snapshot foobar token boundaries: foo_bar fooBar",
        },
    )
    queries = [
        "quick brown",       # interior token narrowable
        "interesting",       # substring of 'uninteresting' -> must not be lost
        "oob",               # subtoken
        "FOO",               # case-insensitive subtoken of foobar/fooBar
        "lazy dog",
        "boundaries:",
        "nonexistent",       # genuinely absent -> both empty
        "fooBar",            # mixed case exact
    ]
    for q in queries:
        via_linear = searcher.search(use_index=False, content_query=q)
        via_index = searcher.search(use_index=True, content_query=q)
        assert _content_keys(via_index) == _content_keys(via_linear), f"mismatch for {q!r}"


def test_fts_content_candidates_safety_contract(tmp_path):
    """Direct contract check on the narrowing primitive.

    - Unsafe queries (no left-bounded ASCII token) must return None so the
      caller live-scans every candidate (never a hard [] that hides matches).
    - A genuinely absent-but-safe query may return [] (provably no match).
    """
    searcher, registry_path = _build_content_index(tmp_path, {"a.txt": "foobar baz"})
    index_path = resolve_index_db_path(registry_path)
    with AtlasFTSIndex(index_path) as idx:
        snaps = ["s1"]
        # subtoken: not safely narrowable -> None (force live scan)
        assert idx.fts_content_candidates(snaps, "oob") is None
        # single bare word (could be a suffix of a larger token) -> None
        assert idx.fts_content_candidates(snaps, "foobar") is None
        # non-ASCII -> None
        assert idx.fts_content_candidates(snaps, "Müller") is None
        # leading punctuation only / operator-like single run -> None
        assert idx.fts_content_candidates(snaps, "C++") is None
        # has an interior/left-bounded token 'baz' -> may narrow (list, not None)
        narrowed = idx.fts_content_candidates(snaps, "foobar baz")
        assert narrowed is not None
        assert isinstance(narrowed, list)


def test_content_live_mutation_after_index_does_not_create_false_negative(tmp_path):
    """Live file changes after indexing must not create false negatives.

    The FTS content column is frozen at index time. If the live file mutates
    afterwards, an FTS-narrowed content search could miss the new content
    entirely — `fts_content_candidates` returns [] (no FTS match against stale
    content) and `_content_match` is never invoked for the file. The search
    layer MUST NOT use FTS content as a hard pre-filter; all
    metadata-filtered candidates must go through live `_content_match`.
    """
    searcher, _ = _build_content_index(tmp_path, {"a.txt": "alpha beta"})

    # Mutate the live file after the index was built.
    root_dir = tmp_path / "content_root"
    (root_dir / "a.txt").write_text("alpha gamma", encoding="utf-8")

    via_linear = searcher.search(use_index=False, content_query="alpha gamma")
    via_index = searcher.search(use_index=True, content_query="alpha gamma")

    assert _content_keys(via_linear) == [("s1", "a.txt")]
    assert _content_keys(via_index) == _content_keys(via_linear)


def test_index_path_does_not_fall_back_when_index_is_covered(tmp_path, monkeypatch):
    """The index path must actually be used when the index fully covers all snapshots.

    This is a diagnosis gate to catch silent fallback to linear search due to
    bugs in the index path (e.g. undefined variables, exceptions). If the index
    is marked complete for all snapshots, the index path must be taken and
    succeed; if it fails, the caller should see an exception, not a silent
    fallback.
    """
    registry_path = _build_search_fixture(tmp_path)
    searcher = AtlasSearch(registry_path)

    def fail_linear(*args, **kwargs):
        raise AssertionError("linear fallback was used — index path did not actually run")

    monkeypatch.setattr(searcher, "_search_linear", fail_linear)

    # Query that should work via index. If index path fails, linear will be called
    # and this assertion will raise.
    res = searcher.search(use_index=True, query="c.txt")

    assert len(res) == 1
    assert res[0]["name"] == "c.txt"


def test_query_metadata_result_order_is_deterministic(tmp_path):
    """query_metadata must return rows in a stable, reproducible order.

    Without ORDER BY, SQLite returns rows in arbitrary heap order, which makes
    search results non-deterministic across runs. This test checks that
    repeated calls to query_metadata return rows in the same order and that
    within a single snapshot rows are ordered by file_uid ascending.
    """
    registry_path = _build_search_fixture(tmp_path)
    index_path = resolve_index_db_path(registry_path)

    with AtlasFTSIndex(index_path) as idx:
        # s2 has 3 files; call twice — order must be identical.
        first = idx.query_metadata(["s2"])
        second = idx.query_metadata(["s2"])
        first_uids = [r["file_uid"] for r in first]
        second_uids = [r["file_uid"] for r in second]
        assert first_uids == second_uids, "query_metadata is not deterministic"
        # Within a single snapshot, file_uid should be ascending.
        assert first_uids == sorted(first_uids), "rows not in file_uid ASC order"

    # Multi-snapshot calls must be stable across repeated invocations.
    with AtlasFTSIndex(index_path) as idx:
        a = [r["file_uid"] for r in idx.query_metadata(["s1", "s2"])]
        b = [r["file_uid"] for r in idx.query_metadata(["s1", "s2"])]
        assert a == b, "multi-snapshot query_metadata is not deterministic"


def test_query_metadata_orders_newest_snapshot_first_by_created_at(tmp_path):
    """Cross-snapshot ordering must be chronological (newest created_at first),
    NOT lexicographic by snapshot_id.

    snapshot_id is `snap_{machine}__{root}__{timestamp}__{hash}` — the timestamp
    is in the middle, so lexicographic order is machine/root-first, not
    time-first. This test deliberately makes lexicographic and chronological
    order diverge: `z_old` is lexicographically greater than `a_new` but
    chronologically older. The newer snapshot (`a_new`) must come first,
    matching the registry's `created_at DESC` semantics used by the linear path.
    """
    registry_path = _make_registry(tmp_path)
    registry = AtlasRegistry(registry_path)
    registry.register_machine("m1", "host1")
    registry.register_root("r1", "m1", "abs_path", "/tmp/r1")

    inv_old = tmp_path / "inv_old.jsonl"
    _write_inv(inv_old, [
        {"rel_path": "old.txt", "name": "old.txt", "ext": ".txt", "size_bytes": 10, "mtime": "2023-01-01T00:00:00Z"},
    ])
    inv_new = tmp_path / "inv_new.jsonl"
    _write_inv(inv_new, [
        {"rel_path": "new.txt", "name": "new.txt", "ext": ".txt", "size_bytes": 20, "mtime": "2023-01-03T00:00:00Z"},
    ])

    # z_old: lexicographically LARGER snapshot_id, but OLDER created_at.
    registry.create_snapshot("z_old", "m1", "r1", "hash_old", "complete")
    registry.conn.execute("UPDATE snapshots SET created_at = '2023-01-01T00:00:00Z' WHERE snapshot_id = 'z_old'")
    registry.update_snapshot_artifacts("z_old", {"inventory": str(inv_old)})

    # a_new: lexicographically SMALLER snapshot_id, but NEWER created_at.
    registry.create_snapshot("a_new", "m1", "r1", "hash_new", "complete")
    registry.conn.execute("UPDATE snapshots SET created_at = '2023-01-03T00:00:00Z' WHERE snapshot_id = 'a_new'")
    registry.update_snapshot_artifacts("a_new", {"inventory": str(inv_new)})

    atlas_base = resolve_atlas_base_dir(registry_path)
    index_path = resolve_index_db_path(registry_path)
    with AtlasFTSIndex(index_path) as idx:
        for sid in ("z_old", "a_new"):
            idx.index_snapshot(registry.get_snapshot(sid), atlas_base)
    registry.close()

    with AtlasFTSIndex(index_path) as idx:
        rows = idx.query_metadata(["z_old", "a_new"])
        snap_order = [r["snapshot_id"] for r in rows]

    # Newest created_at first: a_new (2023-01-03) before z_old (2023-01-01),
    # despite "z_old" > "a_new" lexicographically.
    assert snap_order == ["a_new", "z_old"], (
        f"expected newest-first by created_at, got {snap_order}"
    )


