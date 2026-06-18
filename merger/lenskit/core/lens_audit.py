from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from merger.lenskit.core.lenses import LENS_IDS, infer_lens

KIND = "lenskit.primary_lens_audit"
VERSION = "1.0"
DOES_NOT_ESTABLISH = (
    "truth",
    "correctness",
    "completeness",
    "runtime_behavior",
    "test_sufficiency",
    "regression_absence",
    "semantic_importance",
    "review_priority",
    "change_impact",
)

_KNOWN_LENS_IDS = frozenset(LENS_IDS)


def _normalize_path(path: str | Path) -> str:
    raw = str(path)
    if not raw.strip():
        raise ValueError("primary lens audit path must not be empty")
    if "\\" in raw:
        raise ValueError("primary lens audit path must use POSIX separators")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise ValueError("primary lens audit path must be repo-relative")
    posix = candidate.as_posix()
    if posix in {"", "."}:
        raise ValueError("primary lens audit path must identify a repo path")
    if ".." in candidate.parts:
        raise ValueError("primary lens audit path must not contain parent traversal")
    return posix


def explain_primary_lens(path: str | Path) -> tuple[str, str]:
    posix = _normalize_path(path)
    candidate = Path(posix)
    lens = infer_lens(candidate)

    parts = candidate.parts
    name = candidate.name.lower()
    path_str = posix.lower()

    matched_rule = "matched by existing infer_lens(path)"

    if (".github" in parts or "wgx" in parts or "guards" in parts) and lens == "guards":
        matched_rule = "guards: path segment .github/wgx/guards"
    elif ("tests" in parts or "test" in parts) and lens == "guards":
        matched_rule = "guards: tests/test path segment"
    elif (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.ts")
        or name.endswith(".spec.ts")
    ) and lens == "guards":
        matched_rule = "guards: test filename marker"
    elif (name.startswith("validate_") or "validation" in path_str) and lens == "guards":
        matched_rule = "guards: validation marker"
    elif (
        "contracts" in parts
        or "schemas" in parts
        or "models" in parts
        or "types" in parts
    ) and lens == "data_models":
        matched_rule = "data_models: contracts/schemas/models/types path segment"
    elif (
        name.endswith(".schema.json")
        or name.endswith(".proto")
        or name.endswith(".thrift")
    ) and lens == "data_models":
        matched_rule = "data_models: schema/proto/thrift suffix"
    elif name in ("structs.rs", "types.ts", "models.py") and lens == "data_models":
        matched_rule = "data_models: canonical model filename"
    elif ("pipelines" in parts or "jobs" in parts or "orchestration" in parts) and lens == "pipelines":
        matched_rule = "pipelines: pipelines/jobs/orchestration path segment"
    elif "workflow" in path_str and lens == "pipelines":
        matched_rule = "pipelines: workflow marker"
    elif ("frontends" in parts or "cli" in parts or "bin" in parts) and lens == "entrypoints":
        matched_rule = "entrypoints: frontends/cli/bin path segment"
    elif name in {"__main__.py", "main.rs", "index.ts", "index.js"} and lens == "entrypoints":
        matched_rule = "entrypoints: canonical entrypoint filename"
    elif (
        name.startswith("run_") or name.startswith("start_") or name == "manage.py"
    ) and lens == "entrypoints":
        matched_rule = "entrypoints: runnable filename marker"
    elif (
        "ui" in parts
        or "app" in parts
        or "web" in parts
        or "frontend" in parts
        or "views" in parts
    ) and lens == "ui":
        matched_rule = "ui: ui/app/web/frontend/views path segment"
    elif (
        "templates" in parts
        or name.endswith(".html")
        or name.endswith(".svelte")
        or name.endswith(".css")
    ) and lens == "ui":
        matched_rule = "ui: template or UI file suffix"
    elif (
        "adapters" in parts
        or "interfaces" in parts
        or "api" in parts
        or "ports" in parts
        or "routes" in parts
    ) and lens == "interfaces":
        matched_rule = "interfaces: adapters/interfaces/api/ports/routes path segment"
    elif "service" in parts and "core" not in parts and lens == "interfaces":
        matched_rule = "interfaces: service path without core"
    elif ("core" in parts or "logic" in parts or "domain" in parts) and lens == "core":
        matched_rule = "core: core/logic/domain path segment"
    elif (
        candidate.suffix in {".py", ".rs", ".ts", ".js", ".go", ".java", ".c", ".cpp"}
        and lens == "core"
    ):
        matched_rule = "core: generic source file suffix fallback"
    elif "docs" in parts and lens == "entrypoints":
        matched_rule = "entrypoints: docs path fallback"
    elif candidate.suffix in {".json", ".yaml", ".yml", ".toml"} and lens == "data_models":
        matched_rule = "data_models: config file suffix fallback"
    elif lens == "core":
        matched_rule = "core: ultimate fallback"

    return lens, matched_rule


def audit_primary_lenses(paths: Iterable[str | Path]) -> dict[str, Any]:
    normalized_paths = sorted({_normalize_path(path) for path in paths})
    items: list[dict[str, Any]] = []
    lens_counts: Counter[str] = Counter()

    for posix_path in normalized_paths:
        primary_lens, matched_rule = explain_primary_lens(posix_path)
        if primary_lens not in _KNOWN_LENS_IDS:
            raise ValueError(
                f"Unknown primary lens {primary_lens!r} for path {posix_path!r}"
            )

        lens_counts[primary_lens] += 1
        items.append(
            {
                "path": posix_path,
                "primary_lens": primary_lens,
                "matched_rule": matched_rule,
                "possible_facets": [],
                "notes": [],
                "does_not_establish": list(DOES_NOT_ESTABLISH),
            }
        )

    return {
        "kind": KIND,
        "version": VERSION,
        "items": items,
        "summary": {
            "item_count": len(items),
            "lens_counts": {
                lens_id: lens_counts[lens_id] for lens_id in sorted(lens_counts)
            },
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
