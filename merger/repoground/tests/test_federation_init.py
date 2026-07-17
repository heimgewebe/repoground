import json
from pathlib import Path
import pytest
from merger.repoground.core.federation import init_federation
from merger.repoground.cli.main import main as lenskit_main

def test_init_federation_core(tmp_path: Path):
    out_path = tmp_path / "fed.json"
    data = init_federation("test-fed", out_path)

    assert out_path.exists()
    assert data["kind"] == "repolens.federation.index"
    assert data["version"] == "1.0"
    assert data["federation_id"] == "test-fed"
    assert data["bundles"] == []

    # Read back and verify
    with out_path.open() as f:
        loaded = json.load(f)
        assert loaded == data

def test_init_federation_prevents_overwrite(tmp_path: Path):
    out_path = tmp_path / "fed.json"
    init_federation("test-fed", out_path)

    with pytest.raises(FileExistsError):
        init_federation("test-fed", out_path)

def test_init_federation_fails_without_schema(tmp_path: Path, monkeypatch):
    from merger.repoground.core import federation

    monkeypatch.setattr(federation, "load_federation_schema", lambda: None)

    with pytest.raises(RuntimeError) as exc_info:
        federation.init_federation("test-fed", tmp_path / "out.json")

    assert "Federation schema missing at expected path" in str(exc_info.value)

def test_init_federation_structure(tmp_path: Path):
    out = tmp_path / "fed.json"
    data = init_federation("test-fed", out)

    assert set(data.keys()) == {
        "kind",
        "version",
        "federation_id",
        "created_at",
        "updated_at",
        "bundles",
    }

def test_init_federation_cli_dispatch(tmp_path: Path, capsys):
    out_path = tmp_path / "fed_cli.json"

    exit_code = lenskit_main(["federation", "init", "--id", "my-fed", "--out", str(out_path)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Successfully initialized federation index 'my-fed'" in captured.out

    assert out_path.exists()
    with out_path.open() as f:
        data = json.load(f)
        assert data["federation_id"] == "my-fed"

def test_init_federation_rejects_empty_id(tmp_path: Path):
    with pytest.raises(ValueError) as exc_info:
        init_federation("", tmp_path / "fed.json")
    assert "Failed to generate valid federation index schema" in str(exc_info.value)

def test_rlens_federation_init_dispatch(tmp_path: Path, monkeypatch, capsys):
    out_path = tmp_path / "fed_rlens.json"
    monkeypatch.setattr(
        "sys.argv",
        ["rlens", "federation", "init", "--id", "my-rlens-fed", "--out", str(out_path)]
    )

    from merger.repoground.cli import rlens

    with pytest.raises(SystemExit) as exc_info:
        rlens.main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "Successfully initialized federation index 'my-rlens-fed'" in captured.out
    assert out_path.exists()
