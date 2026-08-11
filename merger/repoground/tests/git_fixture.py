from __future__ import annotations

import os
import subprocess
from pathlib import Path


_GIT_IDENTITY = (
    "-c",
    "user.name=RepoGround Tests",
    "-c",
    "user.email=repoground-tests@example.invalid",
)


def _run(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *_GIT_IDENTITY, *arguments],
        cwd=root,
        check=check,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false"},
    )


def commit_fixture(root: Path) -> str:
    """Commit the current fixture files and return the exact Git HEAD."""
    root.mkdir(parents=True, exist_ok=True)
    if not (root / ".git").exists():
        _run(root, "init", "-q")
    _run(root, "add", "--all")
    head = _run(root, "rev-parse", "--verify", "HEAD", check=False)
    if head.returncode != 0:
        _run(root, "commit", "-qm", "fixture")
    else:
        staged = _run(root, "diff", "--cached", "--quiet", "HEAD", "--", check=False)
        if staged.returncode not in {0, 1}:
            raise RuntimeError(staged.stderr.strip() or "git diff --cached failed")
        if staged.returncode == 1:
            _run(root, "commit", "-qm", "fixture")
    return _run(root, "rev-parse", "HEAD").stdout.strip()
