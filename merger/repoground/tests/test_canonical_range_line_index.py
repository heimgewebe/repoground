"""Preserve byte-accurate canonical citations while indexing line offsets once."""

from __future__ import annotations

from copy import deepcopy

import pytest

from merger.repoground.core import merge


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\n",
        b"a\n",
        b"a\r\nb\n",
        "ä💡\nsecond\nlast".encode("utf-8"),
        b"no newline",
        b"\n\n\nlast\n",
    ],
)
def test_indexed_lines_match_historical_bytes_count_at_all_offsets(data: bytes) -> None:
    positions = merge._canonical_newline_offsets(data)
    for offset in range(-len(data) - 2, len(data) + 3):
        assert merge._line_for_byte(
            data,
            offset,
            newline_offsets=positions,
        ) == merge._line_for_byte(data, offset)


def test_newline_index_is_snapshot_local_and_compact() -> None:
    a = b"one\nsecond\n"
    b = b"no breaks"
    a_positions = merge._canonical_newline_offsets(a)
    b_positions = merge._canonical_newline_offsets(b)
    assert a_positions.typecode == "I"
    assert b_positions.typecode == "I"
    assert list(a_positions) == [3, 10]
    assert list(b_positions) == []
    assert a_positions is not b_positions
    assert merge._line_for_byte(a, 4, newline_offsets=a_positions) == 2
    assert merge._line_for_byte(b, 4, newline_offsets=b_positions) == 1


def test_large_byte_offsets_choose_64_bit_index_without_allocating_gigabytes() -> None:
    class VirtualLargeBytes:
        def __len__(self) -> int:
            return 2**32

        def find(self, needle: bytes, start: int = 0) -> int:
            assert needle == b"\n"
            return 4 if start <= 4 else -1

    offsets = merge._canonical_newline_offsets(VirtualLargeBytes())
    assert offsets.typecode == "Q"
    assert list(offsets) == [4]


@pytest.mark.parametrize("data", [b"", b"head\nsecond\nlast", "Ä\nB".encode("utf-8")])
def test_full_canonical_range_references_remain_identical(data: bytes) -> None:
    offsets = merge._canonical_newline_offsets(data)
    for start, end in [
        (0, 0),
        (0, min(4, len(data))),
        (max(0, len(data) - 3), len(data)),
    ]:
        original = {
            "start_byte": start,
            "end_byte": end,
            "start_line": 19,
            "end_line": 19,
            "sha256": "f" * 64,
        }
        before = deepcopy(original)
        after = deepcopy(original)
        kwargs = {
            "repo_label": "demo",
            "md_file_name": "canonical.md",
            "md_start_byte": 0,
            "canonical_md_bytes": data,
        }
        merge._attach_canonical_range(before, **kwargs)
        merge._attach_canonical_range(
            after, **kwargs, canonical_newline_offsets=offsets
        )
        assert after == before
        assert (
            after["canonical_range"]["content_sha256"]
            == before["content_range_ref"]["content_sha256"]
        )


def test_noncanonical_missing_bytes_preserves_historical_source_fallback() -> None:
    source = {
        "start_byte": 1,
        "end_byte": 2,
        "start_line": 4,
        "end_line": 4,
        "sha256": "a" * 64,
    }
    kwargs = {
        "repo_label": "demo",
        "md_file_name": "canonical.md",
        "md_start_byte": 3,
        "canonical_md_bytes": None,
    }
    copy = deepcopy(source)
    merge._attach_canonical_range(source, **kwargs)
    merge._attach_canonical_range(
        copy,
        **kwargs,
        canonical_newline_offsets=None,
    )
    assert source == copy
    assert "canonical_range" not in source
    assert source["content_range_ref"]["start_line"] == 4
