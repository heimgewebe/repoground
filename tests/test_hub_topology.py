import pytest
from pathlib import Path
import tempfile
from merger.repoground.core.merge import detect_hub_dir

def test_detect_hub_dir_saved_path():
    with tempfile.TemporaryDirectory() as script_dir, tempfile.TemporaryDirectory() as hub_dir:
        script_path = Path(script_dir) / "repolens.py"
        script_path.touch()

        hub_path_file = Path(script_dir) / ".repolens-hub-path.txt"
        hub_path_file.write_text(hub_dir)

        detected = detect_hub_dir(script_path)
        assert detected == Path(hub_dir)

def test_detect_hub_dir_arg_base():
    with tempfile.TemporaryDirectory() as script_dir, tempfile.TemporaryDirectory() as hub_dir:
        script_path = Path(script_dir) / "repolens.py"
        script_path.touch()

        detected = detect_hub_dir(script_path, arg_base_dir=hub_dir)
        assert detected == Path(hub_dir)

def test_detect_hub_dir_not_found():
    with tempfile.TemporaryDirectory() as script_dir:
        script_path = Path(script_dir) / "repolens.py"
        script_path.touch()

        with pytest.raises(FileNotFoundError, match="Hub-Verzeichnis"):
            detect_hub_dir(script_path)

def test_detect_hub_dir_invalid_saved_path():
    with tempfile.TemporaryDirectory() as script_dir:
        script_path = Path(script_dir) / "repolens.py"
        script_path.touch()

        hub_path_file = Path(script_dir) / ".repolens-hub-path.txt"
        hub_path_file.write_text("/does/not/exist/ever")

        with pytest.raises(FileNotFoundError, match="Hub-Verzeichnis"):
            detect_hub_dir(script_path)

def test_detect_hub_dir_arg_overrides_saved_and_env(monkeypatch):
    with tempfile.TemporaryDirectory() as script_dir, tempfile.TemporaryDirectory() as hub_dir_arg, tempfile.TemporaryDirectory() as hub_dir_env, tempfile.TemporaryDirectory() as hub_dir_saved:
        script_path = Path(script_dir) / "repolens.py"
        script_path.touch()

        hub_path_file = Path(script_dir) / ".repolens-hub-path.txt"
        hub_path_file.write_text(hub_dir_saved)

        monkeypatch.setenv("REPOLENS_BASEDIR", hub_dir_env)

        detected = detect_hub_dir(script_path, arg_base_dir=hub_dir_arg)
        assert detected == Path(hub_dir_arg)

def test_detect_hub_dir_env_overrides_saved(monkeypatch):
    with tempfile.TemporaryDirectory() as script_dir, tempfile.TemporaryDirectory() as hub_dir_env, tempfile.TemporaryDirectory() as hub_dir_saved:
        script_path = Path(script_dir) / "repolens.py"
        script_path.touch()

        hub_path_file = Path(script_dir) / ".repolens-hub-path.txt"
        hub_path_file.write_text(hub_dir_saved)

        monkeypatch.setenv("REPOLENS_BASEDIR", hub_dir_env)

        detected = detect_hub_dir(script_path)
        assert detected == Path(hub_dir_env)

def test_is_pythonista_runtime(monkeypatch):
    from merger.repoground.frontends.pythonista.pathfinder import _is_pythonista_runtime
    import sys

    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    assert not _is_pythonista_runtime()

    monkeypatch.setattr(sys, "executable", "/private/var/mobile/Containers/Shared/AppGroup/Python3")
    assert _is_pythonista_runtime()

    monkeypatch.setattr(sys, "executable", "/Applications/Pythonista3.app/python3")
    assert _is_pythonista_runtime()

def test_detect_hub_dir_pythonista_local_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("REPOLENS_BASEDIR", raising=False)
    script_dir = tmp_path / "Pythonista" / "script"
    script_dir.mkdir(parents=True)
    script_path = script_dir / "repolens.py"
    script_path.touch()

    fake_home = tmp_path / "home"
    docs = fake_home / "Documents"
    hub = docs / "wc-hub"

    hub.mkdir(parents=True)

    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    detected = detect_hub_dir(script_path)
    assert detected == hub

def test_detect_hub_dir_no_pythonista_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("REPOLENS_BASEDIR", raising=False)
    # script_path clearly outside Pythonista
    script_dir = tmp_path / "usr" / "local" / "bin"
    script_dir.mkdir(parents=True)
    script_path = script_dir / "repolens.py"
    script_path.touch()

    fake_home = tmp_path / "home"
    docs = fake_home / "Documents"
    hub = docs / "wc-hub"
    hub.mkdir(parents=True)

    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    with pytest.raises(FileNotFoundError, match="Hub-Verzeichnis"):
        detect_hub_dir(script_path)
