"""Preserve exact Agent Reading Pack spans with a local newline offset index."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from merger.repoground.core import agent_reading_pack as pack
from merger.repoground.core.citation_map import byte_range_to_line_range


class NoPrefixCounting(bytes):
    """A canonical Markdown buffer that rejects repeated full-prefix scans."""

    def count(self, *_args: object, **_kwargs: object) -> int:
        raise AssertionError("full-prefix newline counting is not permitted")


def _write_chunks(tmp_path: Path, data: bytes) -> Path:
    specs = (
        ("one-a", "src/one.py", 0, 2),
        ("two", "src/two.py", 2, 4),
        ("one-b", "src/one.py", 4, len(data)),
    )
    chunks = []
    for chunk_id, path, start, end in specs:
        chunks.append(
            {
                "chunk_id": chunk_id,
                "path": path,
                "repo": "demo",
                "canonical_range": {
                    "artifact_role": "canonical_md",
                    "repo_id": "demo",
                    "file_path": "canonical.md",
                    "start_byte": start,
                    "end_byte": end,
                    "content_sha256": hashlib.sha256(data[start:end]).hexdigest(),
                },
            }
        )
    output = tmp_path / "canonical.chunk_index.jsonl"
    output.write_text(
        "\n".join(json.dumps(chunk) for chunk in chunks) + "\n",
        encoding="utf-8",
    )
    return output


@pytest.mark.parametrize(
    "content",
    [
        b"a\nbc\nd\n",
        b"ab\r\ncd\n",
        "ä\nβ💡\n".encode("utf-8"),
        b"\n\n\nlast\n",
    ],
)
def test_top_file_spans_preserve_historical_line_semantics(
    tmp_path: Path, content: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_chunks(tmp_path, content)
    calls = []
    build = pack._canonical_newline_offsets

    def trace(data: bytes):
        result = build(data)
        calls.append(result)
        return result

    monkeypatch.setattr(pack, "_canonical_newline_offsets", trace)
    top_files, repo_ids, chunk_count = pack.compute_top_files(
        path, NoPrefixCounting(content), "canonical.md"
    )
    assert len(calls) == 1
    assert repo_ids == ["demo"]
    assert chunk_count == 3
    assert len(top_files) == 2
    observed = {top.path: top for top in top_files}
    expected = {
        "src/one.py": (0, len(content), 2),
        "src/two.py": (2, 4, 1),
    }
    for source_path, (start, end, chunks) in expected.items():
        top = observed[source_path]
        assert (top.start_byte, top.end_byte, top.chunk_count) == (start, end, chunks)
        assert (top.start_line, top.end_line) == byte_range_to_line_range(
            content, start, end
        )


def test_empty_chunk_index_avoids_canonical_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_path = tmp_path / "empty.chunk_index.jsonl"
    index_path.write_bytes(b"")

    def reject(_data: bytes):
        raise AssertionError("no spans means no newline index should be built")

    monkeypatch.setattr(pack, "_canonical_newline_offsets", reject)
    assert pack.compute_top_files(
        index_path, NoPrefixCounting(b"many\nlines\n"), "x.md"
    ) == (
        [],
        [],
        0,
    )


def test_one_local_index_per_independent_pack_iteration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"ab\ncde\n"
    path = _write_chunks(tmp_path, data)
    offsets = []
    build = pack._canonical_newline_offsets

    def track(source: bytes):
        value = build(source)
        offsets.append(value)
        return value

    monkeypatch.setattr(pack, "_canonical_newline_offsets", track)
    first = pack.compute_top_files(path, NoPrefixCounting(data), "canonical.md")
    second = pack.compute_top_files(path, NoPrefixCounting(data), "canonical.md")
    assert first == second
    assert len(offsets) == 2
    assert offsets[0] is not offsets[1]
    assert list(offsets[0]) == [2, 6]
