#!/usr/bin/env python3
"""Fail-closed inventory check for RepoGround workflow control-plane classes.

Validates that every file under ``.github/workflows/*.yml`` is listed exactly
once in ``config/workflow-control-plane.v1.json`` with a known class and a
matching SHA-256 identity. Prevents silent workflow drift after T005.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ALLOWED_CLASSES = frozenset(
    {
        "required_protection",
        "fast_feedback",
        "diagnostic",
        "operator_command",
        "historical_ballast",
    }
)
INVENTORY_REL = Path("config/workflow-control-plane.v1.json")
WORKFLOWS_REL = Path(".github/workflows")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_inventory(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    if not path.is_file():
        return None, [f"missing inventory: {INVENTORY_REL}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"unreadable inventory: {exc}"]
    if not isinstance(payload, dict):
        return None, ["inventory root must be an object"]
    if payload.get("kind") != "repoground.workflow_control_plane":
        errors.append("inventory kind must be repoground.workflow_control_plane")
    if payload.get("schema_version") != 1:
        errors.append("inventory schema_version must be 1")
    listed = payload.get("workflows")
    if not isinstance(listed, list) or not listed:
        errors.append("inventory.workflows must be a non-empty list")
    return payload, errors


def _on_disk_workflows(root: Path) -> dict[str, Path] | list[str]:
    workflows_dir = root / WORKFLOWS_REL
    if not workflows_dir.is_dir():
        return [f"missing workflows dir: {WORKFLOWS_REL}"]
    return {
        str(path.relative_to(root)).replace("\\", "/"): path
        for path in sorted(workflows_dir.glob("*.yml"))
    }


def _check_entry(
    entry: Any,
    index: int,
    seen_paths: set[str],
    on_disk: dict[str, Path],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(entry, dict):
        return [f"workflows[{index}] must be an object"]
    path = entry.get("path")
    klass = entry.get("class")
    digest = entry.get("sha256")
    if not isinstance(path, str) or not path:
        return [f"workflows[{index}].path must be a non-empty string"]
    if path in seen_paths:
        errors.append(f"duplicate inventory path: {path}")
    seen_paths.add(path)
    if klass not in ALLOWED_CLASSES:
        errors.append(f"{path}: unknown class {klass!r}")
    if path not in on_disk:
        errors.append(f"{path}: listed but missing on disk")
        return errors
    actual = _sha256(on_disk[path])
    if not isinstance(digest, str) or len(digest) != 64:
        errors.append(f"{path}: sha256 must be a 64-char hex digest")
    elif actual != digest:
        errors.append(
            f"{path}: sha256 drift (inventory={digest[:12]}… disk={actual[:12]}…); "
            "refresh config/workflow-control-plane.v1.json after intentional workflow edits"
        )
    return errors


def _validate_inventory(
    payload: dict[str, Any],
    on_disk: dict[str, Path],
) -> list[str]:
    errors: list[str] = []
    listed = payload.get("workflows")
    assert isinstance(listed, list)
    seen_paths: set[str] = set()
    for index, entry in enumerate(listed):
        errors.extend(_check_entry(entry, index, seen_paths, on_disk))
    for path in sorted(set(on_disk) - seen_paths):
        errors.append(f"{path}: on disk but not classified in inventory")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    payload, errors = _load_inventory(root / INVENTORY_REL)
    disk = _on_disk_workflows(root)
    if isinstance(disk, list):
        errors.extend(disk)
    elif payload is not None:
        errors.extend(_validate_inventory(payload, disk))
    return _emit(args.format, errors, payload or {})


def _emit(fmt: str, errors: list[str], payload: dict[str, Any]) -> int:
    workflows = payload.get("workflows")
    report = {
        "ok": not errors,
        "error_count": len(errors),
        "errors": errors,
        "inventory": str(INVENTORY_REL),
        "workflow_count": len(workflows) if isinstance(workflows, list) else 0,
        "counts_by_class": payload.get("counts_by_class"),
    }
    if fmt == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif errors:
        print("workflow control-plane check: FAIL")
        for item in errors:
            print(f"  - {item}")
    else:
        print(
            "workflow control-plane check: PASS "
            f"({report['workflow_count']} workflows classified)"
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
