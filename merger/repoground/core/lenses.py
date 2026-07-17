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
    "guards"
]

def infer_lens(path: Path) -> str:
    """
    Infers the reading lens for a given file path based on heuristics.
    Returns one of the 7 canonical lens IDs.

    Heuristics are 'focus overlay' only, not exclusion.
    """
    parts = path.parts
    name = path.name.lower()
    path_str = str(path).lower()

    # 1. Guards (Validation, Safety, CI)
    # High priority to catch verification logic early
    if ".github" in parts or "wgx" in parts or "guards" in parts:
        return "guards"
    if "tests" in parts or "test" in parts:
        return "guards"
    if name.startswith("test_") or name.endswith("_test.py") or name.endswith(".test.ts") or name.endswith(".spec.ts"):
        return "guards"
    if name.startswith("validate_") or "validation" in path_str:
        return "guards"

    # 2. Data Models (Truth, Schema, Types)
    if "contracts" in parts or "schemas" in parts or "models" in parts or "types" in parts:
        return "data_models"
    if name.endswith(".schema.json") or name.endswith(".proto") or name.endswith(".thrift"):
        return "data_models"
    if name in ("structs.rs", "types.ts", "models.py"):
        return "data_models"

    # 3. Pipelines (Flow, Orchestration)
    if "pipelines" in parts or "jobs" in parts or "orchestration" in parts:
        return "pipelines"
    if "workflow" in path_str: # e.g. airflow/workflows
        return "pipelines"

    # 4. Entrypoints (Start, CLI, Public)
    if "frontends" in parts or "cli" in parts or "bin" in parts:
        return "entrypoints"
    if name == "__main__.py" or name == "main.rs" or name == "index.ts" or name == "index.js":
        return "entrypoints"
    if name.startswith("run_") or name.startswith("start_") or name == "manage.py":
        return "entrypoints"

    # 5. UI (Interaction, View)
    if "ui" in parts or "app" in parts or "web" in parts or "frontend" in parts or "views" in parts:
        return "ui"
    if "templates" in parts or name.endswith(".html") or name.endswith(".svelte") or name.endswith(".css"):
        return "ui"

    # 6. Interfaces (Adapters, API, IO)
    if "adapters" in parts or "interfaces" in parts or "api" in parts or "ports" in parts or "routes" in parts:
        return "interfaces"
    if "service" in parts and not "core" in parts:
        return "interfaces"

    # 7. Core (Logic, Domain) - Default for code
    # If we haven't matched yet, and it looks like code, it's likely core logic.
    if "core" in parts or "logic" in parts or "domain" in parts:
        return "core"

    # Fallback for generic source files not caught above
    if path.suffix in (".py", ".rs", ".ts", ".js", ".go", ".java", ".c", ".cpp"):
        return "core"

    # Fallback for docs/configs not caught above
    if "docs" in parts:
        return "entrypoints" # Docs are often entrypoints for understanding

    if path.suffix in (".json", ".yaml", ".yml", ".toml"):
        return "data_models" # Configs often define structure/data

    return "core" # Ultimate fallback
