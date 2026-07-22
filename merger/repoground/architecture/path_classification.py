"""Shared repository-path classification for graph and entrypoint projections."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

Projection = Literal["product", "test", "fixture", "script"]

_PRODUCT_LAYER_BY_SEGMENT = {
    "adapters": "adapter",
    "architecture": "architecture",
    "atlas": "atlas",
    "cli": "cli",
    "contracts": "contract",
    "core": "core",
    "frontends": "frontend",
    "retrieval": "retrieval",
    "service": "service",
}
_SCRIPT_SEGMENTS = {"scripts", "tools"}
_TEST_SEGMENTS = {"test", "tests"}
_TEST_NAME_SUFFIXES = {".js", ".jsx", ".py", ".rs", ".svelte", ".ts", ".tsx"}


def _path(path: str) -> PurePosixPath:
    return PurePosixPath(path.replace("\\", "/"))


def is_test_path(path: str) -> bool:
    parsed = _path(path)
    name = parsed.name.lower()
    suffix = parsed.suffix.lower()
    marked_test_name = suffix in _TEST_NAME_SUFFIXES and (
        ".test." in name or ".spec." in name or "_test." in name
    )
    return (
        name.startswith("test_")
        or marked_test_name
        or bool(set(parsed.parts).intersection(_TEST_SEGMENTS))
    )


def path_projection(path: str) -> Projection:
    """Classify one repository-relative path by maintenance responsibility."""

    parsed = _path(path)
    parts = set(parsed.parts)
    if "fixtures" in parts:
        return "fixture"
    if is_test_path(path):
        return "test"
    if parts.intersection(_SCRIPT_SEGMENTS):
        return "script"
    return "product"


def infer_architecture_layer(path: str) -> str:
    """Infer a bounded architecture layer without mixing external modules in."""

    parsed = _path(path)
    projection = path_projection(path)
    if projection in {"test", "fixture"}:
        return "test"

    parts = parsed.parts
    if parsed.name.startswith("benchmark_") or "benchmarks" in parts:
        return "benchmark"
    if len(parts) >= 3 and parts[:2] in {("merger", "repoground"), ("merger", "lenskit")}:
        segment = parts[2]
        return _PRODUCT_LAYER_BY_SEGMENT.get(segment, "product")
    for segment in parts:
        layer = _PRODUCT_LAYER_BY_SEGMENT.get(segment)
        if layer is not None:
            return layer
    if projection == "script":
        return "infra"
    if parts and parts[0] in {"merger", "repoground"}:
        return "product"
    return "unknown"
