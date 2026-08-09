from __future__ import annotations

import importlib.util
import os
import shlex
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
WRAPPER = ROOT / "scripts" / "ops" / "repoground-cli-wrapper"
RENDERER = ROOT / "scripts" / "ops" / "render_repoground_immutable_service.py"
MANAGED_RUNTIME_RELATIVE = Path(".local/share/repoground-runtime/current/.venv/bin/python")


def _renderer_module():
    spec = importlib.util.spec_from_file_location("repoground_service_renderer", RENDERER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_wrapper_prefers_active_immutable_runtime_when_present(tmp_path: Path) -> None:
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
    assert args[-3:] == [str(source_root), "0", "probe"]


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
    args = override_marker.read_text(encoding="utf-8").splitlines()
    assert args[0] == "override"
    assert args[-3:] == [str(source_root), "1", "probe"]
    assert not managed_marker.exists()


def test_wrapper_falls_back_to_path_python3_without_active_runtime(tmp_path: Path) -> None:
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
    args = marker.read_text(encoding="utf-8").splitlines()
    assert args[0] == "fallback"
    assert args[-3:] == [str(source_root), "1", "probe"]


def test_renderer_binds_source_and_python_to_same_immutable_commit(tmp_path: Path) -> None:
    renderer = _renderer_module()
    commit = "a" * 40
    runtime = tmp_path / commit
    python = runtime / ".venv" / "bin" / "python"
    env_file = tmp_path / "repoground.env"

    text = renderer.render_service_unit(
        commit=commit,
        runtime_dir=runtime,
        python_path=python,
        env_file=env_file,
    )

    assert f"ConditionPathIsDirectory={runtime}" in text
    assert f"Environment=REPOGROUND_VERSION={commit}" in text
    assert f"Environment=REPOGROUND_BUILD_ID={commit}" in text
    assert f"Environment=PYTHONPATH={runtime}" in text
    assert f"WorkingDirectory={runtime}" in text
    assert f"ExecStartPre=/usr/bin/test -x {python}" in text
    assert f"ExecStart={python} -m merger.repoground serve" in text
    assert "/usr/bin/python3 -m merger.repoground serve" not in text


def test_renderer_rejects_python_outside_commit_runtime(tmp_path: Path) -> None:
    renderer = _renderer_module()
    commit = "b" * 40
    runtime = tmp_path / commit

    with pytest.raises(ValueError, match="python_path"):
        renderer.render_service_unit(
            commit=commit,
            runtime_dir=runtime,
            python_path=tmp_path / "other" / "python",
            env_file=tmp_path / "repoground.env",
        )


def test_renderer_rejects_runtime_not_named_for_commit(tmp_path: Path) -> None:
    renderer = _renderer_module()
    commit = "c" * 40
    runtime = tmp_path / ("d" * 40)

    with pytest.raises(ValueError, match="basename"):
        renderer.render_service_unit(
            commit=commit,
            runtime_dir=runtime,
            python_path=runtime / ".venv" / "bin" / "python",
            env_file=tmp_path / "repoground.env",
        )


def test_renderer_rejects_parent_directory_segments() -> None:
    renderer = _renderer_module()
    commit = "e" * 40
    runtime = Path("/srv/repoground-runtime/ignored/..") / commit

    with pytest.raises(ValueError, match="canonical simple absolute path"):
        renderer.render_service_unit(
            commit=commit,
            runtime_dir=runtime,
            python_path=runtime / ".venv" / "bin" / "python",
            env_file="/etc/repoground/env",
        )
