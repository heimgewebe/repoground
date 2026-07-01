"""
PR-Schau Bundle Loader (Strict v1).

Goal:
  - One canonical way to load a bundle safely.
  - Default strict behavior: v1-only, reject legacy flat bundles.

Etymology note:
  "contract" (lat. contractus/contrahere) = "pulled together into binding form".
  This loader enforces that binding form on the consumer side.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Dict, Tuple

try:
    import jsonschema  # type: ignore
except ImportError:
    jsonschema = None


BUNDLE_FILENAME = "bundle.json"
SCHEMA_PATH = Path(__file__).parents[1] / "contracts" / "pr-schau.v1.schema.json"

# Legacy keys that must never appear at top-level in v1 bundle.json
LEGACY_TOP_LEVEL_KEYS = {
    "repo",
    "source",
    "created_at",
    "hub_rel",
    "old_tree_hint",
    "new_tree_hint",
    "note",
}


class PRSchauBundleError(RuntimeError):
    pass


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _require_jsonschema() -> Any:
    if jsonschema is None:
        _raise("jsonschema dependency unavailable; cannot validate pr-schau bundle")
    return jsonschema


def _load_schema() -> Dict[str, Any]:
    if not SCHEMA_PATH.exists():
        _raise(f"Schema file not found: {SCHEMA_PATH}")
    try:
        schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
    except json.JSONDecodeError as e:
        _raise(f"Invalid schema JSON in {SCHEMA_PATH}: {e}")
    except OSError as e:
        _raise(f"Could not read schema file {SCHEMA_PATH}: {e}")
    if not isinstance(schema, dict):
        _raise(f"Schema root must be an object: {SCHEMA_PATH}")
    return schema


def _raise(msg: str) -> None:
    raise PRSchauBundleError(msg)


def load_pr_schau_bundle(
    bundle_dir_or_json: Path,
    *,
    strict: bool = True,
    verify_level: str = "basic",
) -> Tuple[Dict[str, Any], Path]:
    """
    Load PR-Schau v1 bundle.json from a directory or direct file path.

    strict=True (default):
      - Requires kind/version v1.
      - Rejects legacy flat bundle keys.
      - Requires parts exist.
      - basic integrity checks (primary in parts, parts map to artifacts).

    verify_level:
      - "none": load only + minimal structural checks
      - "basic": schema (if available) + existence + integrity mapping
      - "full": additionally verify sha256 hashes for canonical_md/part_md
    """
    if verify_level not in ("none", "basic", "full"):
        _raise(f"Invalid verify_level: {verify_level}")

    target = Path(bundle_dir_or_json)
    bundle_json = target / BUNDLE_FILENAME if target.is_dir() else target

    if not bundle_json.exists():
        _raise(f"{BUNDLE_FILENAME} not found: {bundle_json}")

    try:
        data = json.loads(bundle_json.read_text("utf-8"))
    except Exception as e:
        _raise(f"Invalid JSON in {bundle_json}: {e}")

    bundle_dir = bundle_json.parent

    # --- Minimal checks (always) ---
    if not isinstance(data, dict):
        _raise("Bundle root must be an object")

    if strict:
        for k in LEGACY_TOP_LEVEL_KEYS:
            if k in data:
                _raise(f"Legacy flat bundle key present at top-level: '{k}'")

        if data.get("kind") != "repolens.pr_schau.bundle":
            _raise("Invalid 'kind' (expected repolens.pr_schau.bundle)")

        if data.get("version") != "1.0":
            _raise("Invalid 'version' (expected '1.0')")

        # Ensure nested blocks exist (v1 shape)
        for req in ("meta", "completeness", "artifacts"):
            if req not in data:
                _raise(f"Missing required v1 field: {req}")

    # --- Schema validation (basic/full) ---
    if verify_level in ("basic", "full"):
        schema = _load_schema()
        validator = _require_jsonschema()
        try:
            validator.validate(instance=data, schema=schema)
        except Exception as e:
            _raise(f"Schema validation failed: {e}")

    # --- Existence and integrity checks ---
    if verify_level in ("basic", "full"):
        comp = data.get("completeness", {})
        parts = comp.get("parts", [])
        primary = comp.get("primary_part")

        if strict:
            if not isinstance(parts, list) or len(parts) < 1:
                _raise("completeness.parts must be a non-empty array")
            if not primary or primary not in parts:
                _raise("completeness.primary_part must be present and included in completeness.parts")

        # physical existence
        for p in parts:
            p_path = bundle_dir / p
            if not p_path.exists():
                _raise(f"Missing part file: {p}")

        # parts <-> artifacts mapping
        arts = data.get("artifacts", [])
        if strict:
            if not isinstance(arts, list):
                _raise("artifacts must be an array")
            art_map = {a.get("basename"): a for a in arts if isinstance(a, dict)}
            for p in parts:
                if p not in art_map:
                    _raise(f"Part '{p}' has no corresponding artifact entry (basename)")

    # --- Full verification: hashes for content artifacts ---
    if verify_level == "full":
        arts = data.get("artifacts", [])
        art_map = [a for a in arts if isinstance(a, dict)]
        for art in art_map:
            role = art.get("role")
            basename = art.get("basename")
            declared = art.get("sha256")

            if role in ("canonical_md", "part_md"):
                if not declared:
                    _raise(f"Missing sha256 for content artifact: {basename} (role={role})")
                p = bundle_dir / str(basename)
                if not p.exists():
                    _raise(f"Missing artifact file on disk: {basename}")
                computed = _compute_sha256(p)
                if computed != declared:
                    _raise(f"SHA256 mismatch for {basename}: declared={declared} computed={computed}")

    return data, bundle_dir