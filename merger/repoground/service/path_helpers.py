"""Shared path validation helpers for service API handlers.

Kept outside any domain router so endpoints like `api_prescan` and query
handlers share one secure resolution path without cross-router private
coupling.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from ..adapters.security import resolve_secure_path


def is_safe_filename(name: str) -> bool:
    if not name or name in {".", ".."}:
        return False
    if "/" in name or "\\" in name or ":" in name:
        return False
    path = Path(name)
    return path.name == name and not path.is_absolute()


def resolve_request_path(root: Path, relative_path: str, *, label: str) -> Path:
    """Resolve one API-controlled path beneath an established service root."""
    try:
        return resolve_secure_path(root, relative_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label} path") from exc


# Compatibility aliases used by existing call sites and re-exports.
_is_safe_filename = is_safe_filename
_resolve_request_path = resolve_request_path
