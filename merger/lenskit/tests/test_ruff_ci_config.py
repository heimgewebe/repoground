from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys


def test_repo_wide_ruff_config_preserves_builtin_exclusions(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    source_config = repo_root / "ruff-ci.toml"
    workspace = tmp_path / "workspace"
    config = workspace / "ruff-ci.toml"

    (workspace / ".git" / "refs" / "remotes" / "origin").mkdir(parents=True)
    (workspace / "tests" / "fixtures").mkdir(parents=True)
    (workspace / "src").mkdir(parents=True)
    shutil.copyfile(source_config, config)

    # Both excluded files are intentionally invalid. If either exclusion regresses,
    # Ruff emits parser errors even though the narrow lint selection is F401/F811.
    (workspace / ".git" / "refs" / "remotes" / "origin" / "topic.py").write_text(
        "this is not valid python ???\n",
        encoding="utf-8",
    )
    (workspace / "tests" / "fixtures" / "invalid.py").write_text(
        "this is not valid python ???\n",
        encoding="utf-8",
    )
    visible = workspace / "src" / "visible.py"
    visible.write_text("value = 1\n", encoding="utf-8")

    show_files = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            config.name,
            "--show-files",
            ".",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=workspace,
    )
    discovered = set()
    for line in show_files.stdout.splitlines():
        if not line.strip():
            continue
        candidate = Path(line)
        if not candidate.is_absolute():
            candidate = workspace / candidate
        discovered.add(candidate.resolve())

    assert discovered == {visible.resolve()}

    check = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            config.name,
            ".",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=workspace,
    )

    assert check.returncode == 0, check.stdout + check.stderr
    assert "All checks passed!" in check.stdout
