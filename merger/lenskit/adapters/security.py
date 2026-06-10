from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import os
import re

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

    def set_token(self, token: Optional[str]):
        self.token = token

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

    def validate_path(self, path: Path) -> Path:
        """
        Central trust boundary for filesystem paths.
        Two-stage gate:
          1) String-only containment pre-check (no filesystem touch) against allowlist_roots
          2) resolve() + post-check using Path.relative_to for canonical enforcement
        """
        raw = str(path)
        if not raw.strip():
            raise InvalidPathError("Invalid path (empty)")
        if "\0" in raw:
            raise InvalidPathError("Invalid path (NUL byte)")

        if not self.allowlist_roots:
            raise AccessDeniedError(
                "No allowed roots configured (SecurityConfig not initialized)",
            )

        # --- Stage 1: pre-check without resolve() ---
        # Expand ~ and normalize purely as a string.
        expanded = os.path.expanduser(raw)
        normalized = os.path.normpath(expanded)

        if not os.path.isabs(normalized):
            raise InvalidPathError("Invalid path (not absolute)")

        allowed_by_prefix = False
        for root in self.allowlist_roots:
            root_norm = os.path.normpath(str(root))
            # commonpath is robust vs "../" tricks after normpath
            try:
                # commonpath returns the longest common sub-path
                if os.path.commonpath([root_norm, normalized]) == root_norm:
                    allowed_by_prefix = True
                    break
            except Exception:
                # If commonpath fails (mixed drives etc.), treat as not allowed.
                continue

        if not allowed_by_prefix:
            # This early exit helps CodeQL see the barrier before resolve()
            raise AccessDeniedError("Access denied: Path is not allowed (prefix check)")

        # --- Stage 2: canonicalize + enforce with Path semantics ---
        try:
            # Now safe to resolve (canonicalize symlinks etc)
            resolved = Path(normalized).resolve()
        except Exception:
            raise InvalidPathError("Invalid path resolution")

        # Post-check: resolved path must still lie within allowlist roots.
        # This prevents symlink escapes that passed string check.
        for root in self.allowlist_roots:
            try:
                # Resolve root too to be sure (it should be already, but robustness)
                resolved_root = root.resolve()
                resolved.relative_to(resolved_root)
                return resolved
            except ValueError:
                continue

        raise AccessDeniedError("Access denied: Path is not allowed (canonical check)")


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

    p = Path(path_str)
    # Use resolved path for checks
    resolved = get_security_config().validate_path(p)

    if not resolved.exists():
        raise InvalidPathError("Hub does not exist")
    if not resolved.is_dir():
        raise InvalidPathError("Hub is not a directory")
    return resolved


def validate_source_dir(path: Path) -> Path:
    # Ensure source is within allowlist roots (hub) and use ONLY the validated path.
    resolved = get_security_config().validate_path(path)
    if not resolved.exists() or not resolved.is_dir():
        raise InvalidPathError("Invalid repo path")
    return resolved

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
