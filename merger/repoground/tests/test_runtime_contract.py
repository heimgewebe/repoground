from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WRAPPER = ROOT / "scripts" / "ops" / "repoground-cli-wrapper"
SERVICE_UNIT = ROOT / "docs" / "systemd" / "repoground.service"
MANAGED_RUNTIME_RELATIVE = Path(".local/share/repoground/runtime/current/bin/python")


def _source_root(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    package = root / "repoground"
    package.mkdir(parents=True)
    (package / "__main__.py").write_text("", encoding="utf-8")
    return root


def _fake_python(path: Path, marker: Path, label: str, *, exit_code: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    quoted_marker = shlex.quote(str(marker))
    quoted_label = shlex.quote(label)
    path.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' {quoted_label} > {quoted_marker}\n"
        f"printf '%s\\n' \"$@\" >> {quoted_marker}\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _wrapper_env(home: Path, source_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("REPOGROUND_PYTHON", None)
    env.update({"HOME": str(home), "REPOGROUND_ROOT": str(source_root)})
    return env


def test_wrapper_prefers_managed_runtime_when_present(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source_root = _source_root(tmp_path)
    marker = tmp_path / "managed.args"
    managed_python = home / MANAGED_RUNTIME_RELATIVE
    _fake_python(managed_python, marker, "managed")

    completed = subprocess.run(
        [str(WRAPPER), "probe"],
        env=_wrapper_env(home, source_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    args = marker.read_text(encoding="utf-8").splitlines()
    assert args[0] == "managed"
    assert args[1:3] == ["-I", "-c"]
    assert args[-2:] == [str(source_root), "probe"]


def test_wrapper_explicit_python_override_wins_over_managed_runtime(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source_root = _source_root(tmp_path)
    managed_marker = tmp_path / "managed.args"
    override_marker = tmp_path / "override.args"
    managed_python = home / MANAGED_RUNTIME_RELATIVE
    override_python = tmp_path / "override-python"
    _fake_python(managed_python, managed_marker, "managed", exit_code=91)
    _fake_python(override_python, override_marker, "override")
    env = _wrapper_env(home, source_root)
    env["REPOGROUND_PYTHON"] = str(override_python)

    completed = subprocess.run(
        [str(WRAPPER), "probe"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert override_marker.read_text(encoding="utf-8").splitlines()[0] == "override"
    assert not managed_marker.exists()


def test_wrapper_falls_back_to_path_python3_without_managed_runtime(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source_root = _source_root(tmp_path)
    marker = tmp_path / "fallback.args"
    fake_bin = tmp_path / "bin"
    _fake_python(fake_bin / "python3", marker, "fallback")
    env = _wrapper_env(home, source_root)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    completed = subprocess.run(
        [str(WRAPPER), "probe"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert marker.read_text(encoding="utf-8").splitlines()[0] == "fallback"


def test_service_requires_same_managed_runtime_without_system_python_fallback() -> None:
    text = SERVICE_UNIT.read_text(encoding="utf-8")
    managed = "%h/.local/share/repoground/runtime/current/bin/python"

    assert f"ExecStartPre=/usr/bin/test -x {managed}" in text
    assert f"ExecStart={managed} -m merger.repoground serve" in text
    assert "ExecStart=/usr/bin/python3 -m merger.repoground serve" not in text
