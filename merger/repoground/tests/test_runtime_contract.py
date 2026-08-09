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
SOURCE_SERVICE = ROOT / "docs" / "systemd" / "repoground.service"
MANAGED_BASE_RELATIVE = Path(".local/share/repoground-runtime")
MANAGED_POINTER_RELATIVE = MANAGED_BASE_RELATIVE / "current"


def _renderer_module():
    spec = importlib.util.spec_from_file_location("repoground_service_renderer", RENDERER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_root(root: Path) -> Path:
    package = root / "repoground"
    package.mkdir(parents=True)
    (package / "__main__.py").write_text("", encoding="utf-8")
    return root


def _managed_runtime(home: Path, commit: str = "a" * 40) -> tuple[Path, Path]:
    runtime = _source_root(home / MANAGED_BASE_RELATIVE / commit)
    pointer = home / MANAGED_POINTER_RELATIVE
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.symlink_to(runtime, target_is_directory=True)
    return runtime, pointer


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


def _wrapper_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("REPOGROUND_ROOT", None)
    env.pop("REPOGROUND_PYTHON", None)
    env["HOME"] = str(home)
    return env


def test_wrapper_resolves_activation_once_before_binding_source_and_python(tmp_path: Path) -> None:
    home = tmp_path / "home"
    managed_root, pointer = _managed_runtime(home)
    managed_python = managed_root / ".venv" / "bin" / "python"
    marker = tmp_path / "managed.args"
    _fake_python(managed_python, marker, "managed")

    completed = subprocess.run(
        [str(WRAPPER), "probe"],
        env=_wrapper_env(home),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    args = marker.read_text(encoding="utf-8").splitlines()
    assert args[0] == "managed"
    assert args[1:3] == ["-I", "-c"]
    assert args[-3:] == [str(managed_root), "0", "probe"]
    assert str(pointer) not in args


def test_wrapper_explicit_overrides_do_not_mix_with_managed_runtime(tmp_path: Path) -> None:
    home = tmp_path / "home"
    managed_root, _ = _managed_runtime(home)
    managed_marker = tmp_path / "managed.args"
    _fake_python(managed_root / ".venv" / "bin" / "python", managed_marker, "managed", exit_code=91)

    source_root = _source_root(tmp_path / "source")
    override_python = tmp_path / "override-python"
    override_marker = tmp_path / "override.args"
    _fake_python(override_python, override_marker, "override")
    env = _wrapper_env(home)
    env.update({"REPOGROUND_ROOT": str(source_root), "REPOGROUND_PYTHON": str(override_python)})

    completed = subprocess.run(
        [str(WRAPPER), "probe"], env=env, capture_output=True, text=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    args = override_marker.read_text(encoding="utf-8").splitlines()
    assert args[0] == "override"
    assert args[-3:] == [str(source_root), "1", "probe"]
    assert not managed_marker.exists()


def test_wrapper_explicit_source_uses_path_python3_instead_of_managed_python(tmp_path: Path) -> None:
    home = tmp_path / "home"
    managed_root, _ = _managed_runtime(home)
    managed_marker = tmp_path / "managed.args"
    _fake_python(managed_root / ".venv" / "bin" / "python", managed_marker, "managed", exit_code=91)

    source_root = _source_root(tmp_path / "source")
    fallback_marker = tmp_path / "fallback.args"
    fake_bin = tmp_path / "bin"
    _fake_python(fake_bin / "python3", fallback_marker, "fallback")
    env = _wrapper_env(home)
    env["REPOGROUND_ROOT"] = str(source_root)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    completed = subprocess.run(
        [str(WRAPPER), "probe"], env=env, capture_output=True, text=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    args = fallback_marker.read_text(encoding="utf-8").splitlines()
    assert args[0] == "fallback"
    assert args[-3:] == [str(source_root), "1", "probe"]
    assert not managed_marker.exists()


def test_wrapper_falls_back_to_checkout_before_first_managed_activation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source_root = _source_root(home / "repos" / "repoground")
    marker = tmp_path / "fallback.args"
    fake_bin = tmp_path / "bin"
    _fake_python(fake_bin / "python3", marker, "fallback")
    env = _wrapper_env(home)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    completed = subprocess.run(
        [str(WRAPPER), "probe"], env=env, capture_output=True, text=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    args = marker.read_text(encoding="utf-8").splitlines()
    assert args[0] == "fallback"
    assert args[-3:] == [str(source_root), "1", "probe"]


def test_wrapper_fails_closed_when_activation_exists_without_python(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _managed_runtime(home)

    completed = subprocess.run(
        [str(WRAPPER), "probe"],
        env=_wrapper_env(home),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "managed runtime activation exists but Python is unavailable" in completed.stderr


def test_wrapper_rejects_activation_outside_managed_runtime_root(tmp_path: Path) -> None:
    home = tmp_path / "home"
    outside = _source_root(tmp_path / ("b" * 40))
    pointer = home / MANAGED_POINTER_RELATIVE
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.symlink_to(outside, target_is_directory=True)

    completed = subprocess.run(
        [str(WRAPPER), "probe"],
        env=_wrapper_env(home),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "must resolve to an immutable commit directory" in completed.stderr


def test_wrapper_rejects_activation_without_commit_named_target(tmp_path: Path) -> None:
    home = tmp_path / "home"
    runtime = _source_root(home / MANAGED_BASE_RELATIVE / "mutable")
    pointer = home / MANAGED_POINTER_RELATIVE
    pointer.symlink_to(runtime, target_is_directory=True)

    completed = subprocess.run(
        [str(WRAPPER), "probe"],
        env=_wrapper_env(home),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "must resolve to an immutable commit directory" in completed.stderr


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
    assert (
        "ExecStart=/usr/bin/env "
        f"REPOGROUND_SERVICE_UNIT=repoground REPOGROUND_VERSION={commit} "
        f"REPOGROUND_BUILD_ID={commit} PYTHONPATH={runtime} "
        f"PYTHONDONTWRITEBYTECODE=1 {python} -m merger.repoground serve"
    ) in text
    assert "/usr/bin/python3 -m merger.repoground serve" not in text


def test_renderer_execstart_overrides_stale_immutable_environment(tmp_path: Path) -> None:
    renderer = _renderer_module()
    commit = "f" * 40
    runtime = tmp_path / commit
    python = runtime / ".venv" / "bin" / "python"
    marker = tmp_path / "service.env"
    python.parent.mkdir(parents=True, exist_ok=True)
    quoted_marker = shlex.quote(str(marker))
    python.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$REPOGROUND_SERVICE_UNIT\" \"$REPOGROUND_VERSION\" \"$REPOGROUND_BUILD_ID\" \"$PYTHONPATH\" \"$PYTHONDONTWRITEBYTECODE\" > {quoted_marker}\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    text = renderer.render_service_unit(
        commit=commit,
        runtime_dir=runtime,
        python_path=python,
        env_file=tmp_path / "repoground.env",
    )
    exec_start = next(line.removeprefix("ExecStart=") for line in text.splitlines() if line.startswith("ExecStart="))
    env = os.environ.copy()
    env.update(
        {
            "REPOGROUND_SERVICE_UNIT": "stale-unit",
            "REPOGROUND_VERSION": "stale-version",
            "REPOGROUND_BUILD_ID": "stale-build",
            "PYTHONPATH": "/stale/pythonpath",
            "PYTHONDONTWRITEBYTECODE": "0",
        }
    )

    completed = subprocess.run(
        shlex.split(exec_start),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "repoground",
        commit,
        commit,
        str(runtime),
        "1",
    ]


def test_renderer_preserves_canonical_service_environment_defaults(tmp_path: Path) -> None:
    renderer = _renderer_module()
    commit = "f" * 40
    runtime = tmp_path / commit
    env_file = tmp_path / "repoground.env"
    text = renderer.render_service_unit(
        commit=commit,
        runtime_dir=runtime,
        python_path=runtime / ".venv" / "bin" / "python",
        env_file=env_file,
    )
    source_lines = SOURCE_SERVICE.read_text(encoding="utf-8").splitlines()

    for name in ("REPOGROUND_HUB", "REPOGROUND_MERGES", "REPOGROUND_HOST", "REPOGROUND_PORT"):
        prefix = f"Environment={name}="
        source_line = next(line for line in source_lines if line.startswith(prefix))
        assert source_line in text


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
