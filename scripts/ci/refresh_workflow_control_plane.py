#!/usr/bin/env python3
"""Refresh workflow SHA-256/byte identities after intentional workflow edits."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
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


def _fail(message: str) -> None:
    raise ValueError(message)


def _load_inventory(inventory_path: Path) -> tuple[dict[str, Any], list[Any]]:
    try:
        payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"unreadable inventory: {exc}")
    if not isinstance(payload, dict):
        _fail("inventory root must be an object")
    if payload.get("kind") != "repoground.workflow_control_plane":
        _fail("invalid inventory kind")
    if payload.get("schema_version") != 1:
        _fail("invalid inventory schema_version")
    workflows = payload.get("workflows")
    if not isinstance(workflows, list) or not workflows:
        _fail("inventory.workflows must be a non-empty list")
    return payload, workflows


def _workflow_files(root: Path) -> dict[str, Path]:
    workflow_dir = root / WORKFLOWS_REL
    if not workflow_dir.is_dir():
        _fail(f"missing workflows dir: {WORKFLOWS_REL}")
    return {
        str(path.relative_to(root)).replace("\\", "/"): path
        for path in sorted(workflow_dir.glob("*.yml"))
    }


def _validate_entry(
    entry: Any,
    *,
    index: int,
    on_disk: dict[str, Path],
) -> tuple[dict[str, Any], str, Path]:
    if not isinstance(entry, dict):
        _fail(f"workflows[{index}] must be an object")
    path = entry.get("path")
    if not isinstance(path, str) or not path:
        _fail(f"workflows[{index}].path must be a non-empty string")
    path_obj = Path(path)
    if path_obj.parent != WORKFLOWS_REL or path_obj.suffix != ".yml":
        _fail(f"invalid workflow path: {path}")
    if entry.get("class") not in ALLOWED_CLASSES:
        _fail(f"{path}: unknown class {entry.get('class')!r}")
    disk_path = on_disk.get(path)
    if disk_path is None or not disk_path.is_file():
        _fail(f"{path}: listed but missing on disk")
    return entry, path, disk_path


def _validated_entries(
    workflows: list[Any],
    on_disk: dict[str, Path],
) -> list[tuple[dict[str, Any], Path]]:
    seen: set[str] = set()
    entries: list[tuple[dict[str, Any], Path]] = []
    for index, candidate in enumerate(workflows):
        entry, path, disk_path = _validate_entry(
            candidate, index=index, on_disk=on_disk
        )
        if path in seen:
            _fail(f"duplicate inventory path: {path}")
        seen.add(path)
        entries.append((entry, disk_path))

    missing_classification = set(on_disk) - seen
    if missing_classification:
        _fail(f"unclassified workflow(s): {', '.join(sorted(missing_classification))}")
    return entries


def _refresh_identities(entries: list[tuple[dict[str, Any], Path]]) -> None:
    for entry, disk_path in entries:
        raw = disk_path.read_bytes()
        entry["sha256"] = hashlib.sha256(raw).hexdigest()
        entry["bytes"] = len(raw)


def _write_inventory(inventory_path: Path, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=inventory_path.parent,
            prefix=f".{inventory_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_name = tmp.name
            tmp.write(rendered)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, inventory_path)
        tmp_name = None
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass


def refresh(root: Path) -> None:
    root = root.resolve()
    inventory_path = root / INVENTORY_REL
    payload, workflows = _load_inventory(inventory_path)
    entries = _validated_entries(workflows, _workflow_files(root))
    _refresh_identities(entries)
    _write_inventory(inventory_path, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    try:
        refresh(args.root)
    except ValueError as exc:
        print(f"workflow control-plane refresh: FAIL: {exc}")
        return 1
    print("workflow control-plane refresh: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
