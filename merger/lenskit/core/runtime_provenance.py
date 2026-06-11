"""Generator runtime provenance for bundle manifests.

The bundle manifest ``generator`` block historically carried only
``{name, version, config_sha256}``. That is enough to identify *what config* a
bundle claims to be built from, but it is **not** enough to detect
runtime/entry-point drift — the situation where a long-running service keeps
emitting bundles from a *stale build* of the generator code that no longer
matches the repository (e.g. a service that predates the claim-evidence-map
wiring). When that happens the dump looks healthy yet silently lacks artifacts
the current code would produce, and nothing in the dump proves which build
emitted it.

This module captures the runtime fingerprint of the generating process so that
drift becomes diagnosable directly from the artifact:

- ``module`` / ``module_file`` — which generator module (and on-disk file) ran.
- ``package_root`` — the installed package root (repo checkout vs site-packages).
- ``python_executable`` / ``python_version`` — the interpreter.
- ``git_commit`` / ``git_dirty`` — the generator working-tree commit, if any.

Redaction: in redacted/export modes absolute filesystem paths are private. When
``redact=True`` the path-bearing fields (``module_file``, ``package_root``,
``python_executable``) are nulled out while the non-sensitive fields (dotted
module name, python version, git commit/dirty) are retained — git commit is the
redaction-safe drift signal.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Dotted name + file of the core generator module. ``write_reports_v2`` lives in
# ``merger.lenskit.core.merge``; the merge module is the canonical bundle
# producer, so its identity is the honest "what code emitted this bundle".
_CORE_GENERATOR_MODULE = "merger.lenskit.core.merge"


def _package_root() -> Path:
    """Filesystem root of the installed ``merger`` package (parent of ``merger``)."""
    # runtime_provenance.py -> core -> lenskit -> merger -> <package_root>
    return Path(__file__).resolve().parents[3]


def _supports_git_subprocess_probe() -> bool:
    """Return whether this runtime can safely attempt git subprocess probes."""
    return sys.platform != "ios"


def _git_state(package_root: Path) -> Tuple[Optional[str], Optional[bool]]:
    """Return ``(git_commit, git_dirty)`` for the generator working tree.

    Returns ``(None, None)`` when the package root is not a git working tree,
    git is unavailable, or subprocess execution is unsupported by the runtime —
    a service installed from a wheel or a sandboxed runtime legitimately has no
    git state, which is itself a useful drift signal.
    """
    if not _supports_git_subprocess_probe():
        return None, None

    def _git(*args: str) -> Optional[str]:
        try:
            out = subprocess.run(
                ["git", "-C", str(package_root), *args],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError):
            return None
        if out.returncode != 0:
            return None
        return out.stdout.strip()

    commit = _git("rev-parse", "HEAD")
    if not commit:
        return None, None
    status = _git("status", "--porcelain")
    # status is "" (clean) or a non-empty listing (dirty); None means unknown.
    git_dirty: Optional[bool] = None if status is None else bool(status)
    return commit, git_dirty


def build_runtime_provenance(
    *,
    redact: bool = False,
    module_name: str = _CORE_GENERATOR_MODULE,
    module_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the ``generator.runtime`` provenance block.

    ``redact`` nulls out absolute-path fields for redacted/export bundles.
    ``module_name`` / ``module_file`` may be overridden to record a specific
    entry-point module; by default the core merge module is recorded.
    """
    if module_file is None:
        mod = sys.modules.get(module_name)
        module_file = getattr(mod, "__file__", None)

    pkg_root = _package_root()
    git_commit, git_dirty = _git_state(pkg_root)

    runtime: Dict[str, Any] = {
        "module": module_name,
        "module_file": str(module_file) if module_file else None,
        "package_root": str(pkg_root),
        "python_executable": sys.executable or None,
        "python_version": platform.python_version(),
        "git_commit": git_commit,
        "git_dirty": git_dirty,
    }

    if redact:
        # Absolute filesystem paths are private in redacted/export modes. Keep
        # the redaction-safe drift signals (module name, python version, git).
        runtime["module_file"] = None
        runtime["package_root"] = None
        runtime["python_executable"] = None

    return runtime
