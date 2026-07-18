"""Read-only inventory for bounded RepoGround compatibility surfaces."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

MAX_CONFIG_BYTES = 1024 * 1024
MAX_CMDLINE_BYTES = 1024 * 1024

SURFACE_PATTERNS: dict[str, tuple[str, ...]] = {
    "legacy-python-namespace": ("merger.lenskit",),
    "legacy-cli-entrypoints": (
        "repobrief-mcp-stdio.py",
        " rlens-client ",
        " repobrief ",
    ),
    "legacy-mcp-resource-scheme": ("repobrief://snapshot/",),
    "legacy-bundle-storage-root": (
        "/.local/share/repobrief/",
        "lenskit-briefs",
    ),
    "legacy-repository-path": ("/repos/lenskit",),
    "legacy-environment": ("RLENS_", "rlens.env"),
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _matched_surfaces(text: str) -> list[str]:
    padded = f" {text} "
    return sorted(
        surface
        for surface, patterns in SURFACE_PATTERNS.items()
        if any(pattern in padded for pattern in patterns)
    )


def scan_processes(proc_root: str | Path = "/proc") -> list[dict[str, Any]]:
    """Return redacted process findings; raw command lines never leave the function."""
    root = Path(proc_root)
    findings: list[dict[str, Any]] = []
    try:
        entries = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError:
        return findings
    observer_pid = os.getpid()
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) == observer_pid:
            continue
        cmdline_path = entry / "cmdline"
        try:
            with cmdline_path.open("rb") as handle:
                raw = handle.read(MAX_CMDLINE_BYTES + 1)
        except OSError:
            continue
        if not raw or len(raw) > MAX_CMDLINE_BYTES:
            continue
        text = raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
        matches = _matched_surfaces(text)
        if not matches:
            continue
        executable = text.split(" ", 1)[0]
        findings.append(
            {
                "pid": int(entry.name),
                "executable": Path(executable).name,
                "matched_surfaces": matches,
                "argv_sha256": _sha256(raw),
            }
        )
    return findings


def scan_configs(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    """Return matched compatibility categories without exposing config contents."""
    findings: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        try:
            with path.open("rb") as handle:
                data = handle.read(MAX_CONFIG_BYTES + 1)
        except OSError as exc:
            findings.append(
                {
                    "path": str(path),
                    "status": "unavailable",
                    "reason": type(exc).__name__,
                    "matched_surfaces": [],
                }
            )
            continue
        if len(data) > MAX_CONFIG_BYTES:
            findings.append(
                {
                    "path": str(path),
                    "status": "blocked",
                    "reason": "config_too_large",
                    "max_bytes": MAX_CONFIG_BYTES,
                    "matched_surfaces": [],
                }
            )
            continue
        text = data.decode("utf-8", errors="replace")
        findings.append(
            {
                "path": str(path),
                "status": "scanned",
                "bytes": len(data),
                "sha256": _sha256(data),
                "matched_surfaces": _matched_surfaces(text),
            }
        )
    return findings


def service_state(unit: str) -> dict[str, Any]:
    """Read a bounded systemd user-unit state without changing it."""
    command = [
        "systemctl",
        "--user",
        "show",
        unit,
        "--no-pager",
        "--property=LoadState",
        "--property=ActiveState",
        "--property=SubState",
        "--property=UnitFileState",
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"unit": unit, "status": "unavailable", "reason": type(exc).__name__}
    properties: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value
    return {
        "unit": unit,
        "status": "observed" if result.returncode == 0 else "unavailable",
        "returncode": result.returncode,
        "properties": properties,
    }


def build_inventory(
    *,
    config_paths: Iterable[str | Path] = (),
    proc_root: str | Path = "/proc",
    include_services: bool = True,
) -> dict[str, Any]:
    processes = scan_processes(proc_root)
    configs = scan_configs(config_paths)
    services = (
        [service_state("repoground.service"), service_state("rlens.service")]
        if include_services
        else []
    )
    matched = sorted(
        {
            surface
            for finding in processes + configs
            for surface in finding.get("matched_surfaces", [])
        }
    )
    return {
        "schema": "repoground.compatibility_inventory.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "observer_pid": os.getpid(),
        "read_only": True,
        "raw_command_lines_included": False,
        "raw_config_contents_included": False,
        "matched_surfaces": matched,
        "process_findings": processes,
        "config_findings": configs,
        "service_states": services,
    }


def dumps_inventory(inventory: dict[str, Any]) -> str:
    return json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
