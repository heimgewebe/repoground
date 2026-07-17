from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import os
import re

from ..core.path_security import resolve_secure_path

class SecurityViolationError(Exception):
    """Base class for security and path validation errors."""
    pass

class InvalidPathError(SecurityViolationError):
    """Raised when a path is malformed or invalid (400)."""
    pass

class AccessDeniedError(SecurityViolationError):
    """Raised when access to a path is denied (403)."""
    pass

@dataclass
class SecurityConfig:
    # Absolute, normalized roots only. Anything else is rejected at registration.
    allowlist_roots: List[Path] = field(default_factory=list)
    token: str | None = None
    sensitive_fs_access: bool = False
    home_preset_root: Optional[Path] = None

    def set_token(self, token: Optional[str]):
        self.token = token

    def set_sensitive_fs_access(
        self,
        enabled: bool,
        *,
        home_preset_root: Optional[Path] = None,
    ) -> None:
        """Record broad access and the optional, startup-resolved Home preset."""
        enabled = bool(enabled)
        if not enabled:
            self.sensitive_fs_access = False
            self.home_preset_root = None
            return

        if home_preset_root is not None and home_preset_root not in self.allowlist_roots:
            raise ValueError("Home preset root must be allowlisted before activation")

        self.sensitive_fs_access = True
        self.home_preset_root = home_preset_root

    def add_allowlist_root(self, path: Path) -> None:
        """
        Register a trusted root directory for filesystem access.
        This must NOT accept tainted/relative inputs, otherwise it can widen the jail.
        """
        s = str(path)
        if not s.strip():
            raise ValueError("Invalid root (empty)")
        if "\x00" in s:
            raise ValueError("Invalid root (NUL byte)")

        try:
            # Normalize without requiring existence (strict=False) to handle setup flexibility
            # resolving allows us to store canonical roots
            root = path.expanduser().resolve()
        except Exception:
            raise ValueError("Invalid root resolution")

        if not root.is_absolute():
            raise ValueError("Invalid root (not absolute)")

        if root not in self.allowlist_roots:
            self.allowlist_roots.append(root)

    def _lexical_relative_path(self, path: Path, root: Path) -> Optional[str]:
        """Return a normalized relative path when ``path`` is lexically under ``root``."""
        raw = str(path)
        if not raw.strip() or raw != raw.strip():
            raise InvalidPathError("Invalid path (empty or padded)")
        if "\x00" in raw:
            raise InvalidPathError("Invalid path (NUL byte)")

        expanded = os.path.expanduser(raw)
        candidate = Path(expanded)
        if not candidate.is_absolute():
            raise InvalidPathError("Invalid path (not absolute)")
        if any(part in {".", ".."} for part in candidate.parts):
            raise InvalidPathError("Invalid path (dot or parent segment)")

        normalized = os.path.normpath(expanded)
        root_normalized = os.path.normpath(str(root))
        try:
            if os.path.commonpath([root_normalized, normalized]) != root_normalized:
                return None
            relative = os.path.relpath(normalized, root_normalized)
        except (OSError, ValueError):
            return None

        if relative == ".":
            return ""
        return Path(relative).as_posix()

    def validate_path(self, path: Path) -> Path:
        """Resolve one path beneath the narrowest registered allowlist root."""
        if not self.allowlist_roots:
            raise AccessDeniedError(
                "No allowed roots configured (SecurityConfig not initialized)",
            )

        # Prefer the most specific root when roots overlap (for example Hub and `/`).
        roots = sorted(
            self.allowlist_roots,
            key=lambda root: len(root.parts),
            reverse=True,
        )
        for root in roots:
            relative = self._lexical_relative_path(path, root)
            if relative is None:
                continue
            if relative == "":
                # Return the already canonical, operator-registered object rather than
                # rebuilding it from request-controlled text.
                return root
            try:
                return resolve_secure_path(root, relative)
            except ValueError as exc:
                raise AccessDeniedError(
                    "Access denied: Path is not allowed (canonical check)",
                ) from exc

        raise AccessDeniedError("Access denied: Path is not allowed (prefix check)")

    def validate_directory(self, path: Path) -> Path:
        """Validate an allowlisted path and require an existing directory."""
        resolved = self.validate_path(path)
        if not resolved.is_dir():
            raise InvalidPathError("Path is not an existing directory")
        return resolved


_security_config = SecurityConfig()

def get_security_config() -> SecurityConfig:
    return _security_config


def validate_hub_path(path_str: str) -> Path:
    """
    Validate a user-supplied hub path against the allowlist and ensure it exists/is a directory.
    Returns a canonical Path that is safe to use for filesystem operations.
    """
    if "\0" in path_str:
        raise InvalidPathError("Invalid path (NUL byte)")

    return get_security_config().validate_directory(Path(path_str))


def validate_source_dir(path: Path) -> Path:
    """Return an existing source directory beneath the configured allowlist."""
    return get_security_config().validate_directory(path)

def validate_repo_name(name: str) -> str:
    _REPO_RE = re.compile(r"^[A-Za-z0-9._-]+$")
    n = (name or "").strip()
    if not n:
        raise InvalidPathError("Invalid repo name: empty")

    # Specific block for "." and ".." strictly
    if n == "." or n == "..":
        raise InvalidPathError(f"Invalid repo name: {n}")

    if "/" in n or "\\" in n or ".." in n:
        raise InvalidPathError("Invalid repo name: contains slash, backslash, or double-dot")

    if not _REPO_RE.match(n):
        raise InvalidPathError(f"Invalid repo name: {n}")

    return n

def resolve_any_path(root: Path, requested: Optional[str]) -> Path:
    if not requested or requested.strip() == "":
        return root.resolve()

    # If absolute, validate against roots
    if os.path.isabs(requested):
        return get_security_config().validate_path(Path(requested))

    # If relative, join and validate
    joined = root / requested
    return get_security_config().validate_path(joined)
