# -*- coding: utf-8 -*-
"""Explicit import bootstrap shared by the Pythonista flat-script entrypoints.

Package imports must use the normal package graph and therefore leave ``sys.path``
untouched. Direct script execution has no package context, so it receives the
smallest deterministic path set needed by the shipped flat Pythonista layout.
"""

import sys
from pathlib import Path
from typing import Optional, Tuple


class PythonistaImportPaths:
    """Resolved import roots for diagnostics and contract tests."""

    __slots__ = ("script_dir", "repo_root", "merger_dir", "package_mode")

    def __init__(
        self,
        script_dir: Path,
        repo_root: Optional[Path],
        merger_dir: Optional[Path],
        package_mode: bool,
    ) -> None:
        self.script_dir = script_dir
        self.repo_root = repo_root
        self.merger_dir = merger_dir
        self.package_mode = package_mode

    def flat_sys_path_entries(self) -> Tuple[str, ...]:
        entries = [str(self.script_dir)]
        if self.repo_root is not None:
            entries.append(str(self.repo_root))
        if self.merger_dir is not None:
            entries.append(str(self.merger_dir))
        return tuple(entries)


def _resolve_script_path(script_file: Optional[str]) -> Path:
    if script_file:
        return Path(script_file).resolve()
    argv0 = None
    try:
        if getattr(sys, "argv", None):
            argv0 = sys.argv[0] or None
    except Exception:
        argv0 = None
    if argv0:
        return Path(argv0).resolve()
    return Path.cwd().resolve()


def _find_merger_dir(script_dir: Path) -> Optional[Path]:
    current = script_dir
    while current.parent != current:
        if current.name == "merger":
            return current
        current = current.parent
    return current if current.name == "merger" else None


def bootstrap_pythonista_imports(
    script_file: Optional[str],
    package_name: Optional[str],
) -> PythonistaImportPaths:
    """Resolve and, only for flat execution, install deterministic import roots.

    The resulting flat order matches the historical standalone contract:
    ``SCRIPT_DIR`` first, followed by the repository root and then ``merger``.
    In package mode no path is inserted or reordered.
    """
    script_path = _resolve_script_path(script_file)
    script_dir = script_path.parent if script_path.suffix else script_path
    merger_dir = _find_merger_dir(script_dir)
    repo_root = merger_dir.parent if merger_dir is not None else None
    package_mode = bool(package_name)
    paths = PythonistaImportPaths(script_dir, repo_root, merger_dir, package_mode)

    if package_mode:
        return paths

    desired = paths.flat_sys_path_entries()
    for entry in desired:
        while entry in sys.path:
            sys.path.remove(entry)
    for entry in reversed(desired):
        sys.path.insert(0, entry)
    return paths
