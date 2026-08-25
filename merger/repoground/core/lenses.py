from __future__ import annotations

from pathlib import Path

# Canonical Lens IDs (Contract: reading.lenses.v1)
LENS_IDS = [
    "entrypoints",
    "core",
    "interfaces",
    "data_models",
    "pipelines",
    "ui",
    "guards",
]

_GUARD_PARTS = frozenset({".github", "wgx", "guards", "tests", "test"})
_DATA_MODEL_PARTS = frozenset({"contracts", "schemas", "models", "types"})
_PIPELINE_PARTS = frozenset({"pipelines", "jobs", "orchestration"})
_ENTRYPOINT_PARTS = frozenset({"frontends", "cli", "bin"})
_UI_PARTS = frozenset({"ui", "app", "web", "frontend", "views", "templates"})
_INTERFACE_PARTS = frozenset({"adapters", "interfaces", "api", "ports", "routes"})
_CORE_PARTS = frozenset({"core", "logic", "domain"})
_CODE_SUFFIXES = (".py", ".rs", ".ts", ".js", ".go", ".java", ".c", ".cpp")
_CONFIG_SUFFIXES = (".json", ".yaml", ".yml", ".toml")


def _has_any_part(parts: tuple[str, ...], markers: frozenset[str]) -> bool:
    return not markers.isdisjoint(parts)


def _is_guard(parts: tuple[str, ...], name: str, path_str: str) -> bool:
    return (
        _has_any_part(parts, _GUARD_PARTS)
        or name.startswith("test_")
        or name.endswith(("_test.py", ".test.ts", ".spec.ts"))
        or name.startswith("validate_")
        or "validation" in path_str
    )


def _is_data_model(parts: tuple[str, ...], name: str) -> bool:
    return (
        _has_any_part(parts, _DATA_MODEL_PARTS)
        or name.endswith((".schema.json", ".proto", ".thrift"))
        or name in ("structs.rs", "types.ts", "models.py")
    )


def _is_pipeline(parts: tuple[str, ...], path_str: str) -> bool:
    return _has_any_part(parts, _PIPELINE_PARTS) or "workflow" in path_str


def _is_entrypoint(parts: tuple[str, ...], name: str) -> bool:
    return (
        _has_any_part(parts, _ENTRYPOINT_PARTS)
        or name in ("__main__.py", "main.rs", "index.ts", "index.js")
        or name.startswith(("run_", "start_"))
        or name == "manage.py"
    )


def _is_ui(parts: tuple[str, ...], name: str) -> bool:
    return _has_any_part(parts, _UI_PARTS) or name.endswith((".html", ".svelte", ".css"))


def _is_interface(parts: tuple[str, ...]) -> bool:
    return _has_any_part(parts, _INTERFACE_PARTS) or (
        "service" in parts and "core" not in parts
    )


def _fallback_lens(parts: tuple[str, ...], suffix: str) -> str:
    if _has_any_part(parts, _CORE_PARTS) or suffix in _CODE_SUFFIXES:
        return "core"
    if "docs" in parts:
        return "entrypoints"
    if suffix in _CONFIG_SUFFIXES:
        return "data_models"
    return "core"


def infer_lens(path: Path) -> str:
    """
    Infers the reading lens for a given file path based on heuristics.
    Returns one of the 7 canonical lens IDs.

    Heuristics are 'focus overlay' only, not exclusion.
    """
    parts = path.parts
    name = path.name.lower()
    path_str = str(path).lower()

    if _is_guard(parts, name, path_str):
        return "guards"
    if _is_data_model(parts, name):
        return "data_models"
    if _is_pipeline(parts, path_str):
        return "pipelines"
    if _is_entrypoint(parts, name):
        return "entrypoints"
    if _is_ui(parts, name):
        return "ui"
    if _is_interface(parts):
        return "interfaces"
    return _fallback_lens(parts, path.suffix)
