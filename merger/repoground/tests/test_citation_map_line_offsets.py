"""Byte-exact, snapshot-local canonical Markdown line offset indexing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from merger.repoground.core import citation_map as cm


@pytest.mark.parametrize(
    "data",
    [
        b"a",
        b"a\n",
        b"\n\n",
        b"one\r\ntwo\nthree",
        "ä💡\nzweite Zeile\n".encode("utf-8"),
        b"without a newline",
    ],
)
def test_indexed_line_ranges_match_original_at_every_valid_boundary(
    data: bytes,
) -> None:
    offsets = cm._canonical_newline_offsets(data)
    assert offsets.typecode == "I"
    for start in range(len(data)):
        for end in range(start + 1, len(data) + 1):
            assert cm.byte_range_to_line_range(
                data, start, end, newline_offsets=offsets
            ) == cm.byte_range_to_line_range(data, start, end)


def test_large_canonical_files_use_unsigned_64_bit_offsets() -> None:
    class VirtualLargeBytes:
        def __len__(self) -> int:
            return 2**32

        def find(self, needle: bytes, start: int = 0) -> int:
            assert needle == b"\n"
            return 4 if start <= 4 else -1

    offsets = cm._canonical_newline_offsets(VirtualLargeBytes())
    assert offsets.typecode == "Q"
    assert list(offsets) == [4]


def test_chunk_iterator_uses_single_index_with_no_prefix_scans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PrefixCountForbidden(bytes):
        def count(self, *args: object, **kwargs: object) -> int:
            raise AssertionError(
                "prefix newline scan must not occur inside chunk iterator"
            )

    canonical = PrefixCountForbidden(b"alpha\nbeta\nlast")
    chunks = []
    for chunk_id, start, end in [("first", 0, 5), ("second", 6, 10)]:
        chunks.append(
            {
                "chunk_id": chunk_id,
                "repo": "testrepo",
                "canonical_range": {
                    "artifact_role": "canonical_md",
                    "repo_id": "testrepo",
                    "file_path": "canonical.md",
                    "start_byte": start,
                    "end_byte": end,
                    "content_sha256": hashlib.sha256(canonical[start:end]).hexdigest(),
                },
            }
        )
    chunk_index = tmp_path / "canonical.chunk_index.jsonl"
    chunk_index.write_text(
        "\n".join(json.dumps(chunk) for chunk in chunks) + "\n",
        encoding="utf-8",
    )

    build_calls = 0
    real_build = cm._canonical_newline_offsets

    def count_builds(data: bytes):
        nonlocal build_calls
        build_calls += 1
        return real_build(data)

    monkeypatch.setattr(cm, "_canonical_newline_offsets", count_builds)
    rows = list(
        cm.iter_chunk_results(
            chunk_index,
            canonical,
            "canonical.md",
            hashlib.sha256(canonical).hexdigest(),
            "run-one",
        )
    )
    assert build_calls == 1
    assert len(rows) == 2
    assert all(result.error is None for result in rows)
    assert [result.row["canonical_range"]["start_line"] for result in rows] == [1, 2]
    assert [result.row["canonical_range"]["end_line"] for result in rows] == [1, 2]
    for row in rows:
        assert row.row["range_ref"]["content_sha256"] == next(
            chunk["canonical_range"]["content_sha256"]
            for chunk in chunks
            if chunk["chunk_id"] == row.row["chunk_id"]
        )


def test_empty_chunk_index_does_not_build_unneeded_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_path = tmp_path / "empty.chunk_index.jsonl"
    index_path.write_bytes(b"")

    def forbid_build(_: bytes) -> None:
        raise AssertionError("no valid chunk requires a newline index")

    monkeypatch.setattr(cm, "_canonical_newline_offsets", forbid_build)
    assert (
        list(
            cm.iter_chunk_results(
                index_path, b"big\ncontent", "canonical.md", "a" * 64, "run"
            )
        )
        == []
    )


def test_index_is_local_to_each_chunk_iteration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"one\ntwo\n"
    index_path = tmp_path / "one.chunk_index.jsonl"
    index_path.write_text(
        json.dumps(
            {
                "chunk_id": "one",
                "repo": "demo",
                "canonical_range": {
                    "artifact_role": "canonical_md",
                    "repo_id": "demo",
                    "file_path": "canonical.md",
                    "start_byte": 0,
                    "end_byte": 3,
                    "content_sha256": hashlib.sha256(data[:3]).hexdigest(),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    builds = []
    original = cm._canonical_newline_offsets

    def track(data: bytes):
        offsets = original(data)
        builds.append(offsets)
        return offsets

    monkeypatch.setattr(cm, "_canonical_newline_offsets", track)
    for _ in range(2):
        results = list(
            cm.iter_chunk_results(
                index_path,
                data,
                "canonical.md",
                hashlib.sha256(data).hexdigest(),
                "run",
            )
        )
        assert len(results) == 1 and results[0].error is None
    assert len(builds) == 2
    assert builds[0] is not builds[1]
