"""Deterministic artifact writing and hashing primitives.

This module is a dependency-free leaf of the bundle pipeline: it must not
import any other RepoGround core module so that artifact writers can depend on
it without creating import cycles.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, List, Optional

_SHA256_READ_CHUNK_BYTES = 65536


def write_text_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via a same-directory temporary file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as tmp_file:
            tmp_file.write(text)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            tmp_path = Path(tmp_file.name)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def compute_file_sha256(path: Path) -> str:
    """Compute SHA256 hash of a file using chunked reading for memory efficiency."""

    sha256 = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(_SHA256_READ_CHUNK_BYTES)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()
    except OSError:
        return "ERROR"


def is_sha256_digest(value: object) -> bool:
    """Return whether ``value`` is exactly one lowercase SHA-256 digest."""

    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def append_unique_path(paths: List[Path], path: Optional[Path]) -> None:
    """Append ``path`` unless it is absent or already recorded."""

    if path is not None and path not in paths:
        paths.append(path)


def json_safe(obj: Any) -> Any:
    """Coerce ``obj`` into deterministic JSON-serialisable data.

    Unknown objects become a stable ``__type__:<module>.<qualname>`` tag rather
    than a ``repr`` so that provenance hashes never depend on memory addresses.
    """

    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, (list, tuple)):
        return [json_safe(x) for x in obj]
    if isinstance(obj, set):
        return sorted([json_safe(x) for x in obj])
    if isinstance(obj, dict):
        return {
            str(k): json_safe(v)
            for k, v in sorted(obj.items(), key=lambda i: str(i[0]))
        }
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "name") and hasattr(obj, "value"):  # Enum-like
        return obj.name

    obj_type = type(obj)
    module = getattr(obj_type, "__module__", "__builtin__")
    qualname = getattr(obj_type, "__qualname__", obj_type.__name__)
    return f"__type__:{module}.{qualname}"


def write_json_lines(path: Path, rows: List[Any]) -> None:
    """Write ``rows`` as deterministic JSONL."""

    write_text_atomic(path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
