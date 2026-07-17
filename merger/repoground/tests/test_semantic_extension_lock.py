from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import jsonschema
import pytest

from scripts.release.check_release_contract import scan
from scripts.release.compile_semantic_lock import (
    _prepare_install_target,
    is_supported_target,
)

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "docs/release/repoground-semantic-platforms.v1.json"
SCHEMA_PATH = (
    ROOT / "merger/repoground/contracts/repoground-semantic-platforms.v1.schema.json"
)
LOCK_PATH = ROOT / "requirements/repoground-semantic-linux-x86_64-py312.lock.txt"
CONSTRAINTS_PATH = (
    ROOT / "requirements/repoground-semantic-linux-x86_64-py312.constraints.txt"
)
RUNTIME_LOCK = ROOT / "requirements/repoground-runtime.lock.txt"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_starts(text: str) -> list[str]:
    return [
        line
        for line in text.splitlines()
        if line and not line[0].isspace() and not line.startswith(("#", "--"))
    ]


def test_semantic_platform_contract_validates_and_hashes_match() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft7Validator(schema).validate(contract)

    assert contract["default_enabled"] is False
    assert contract["unsupported_target_policy"] == "fail_closed"
    assert contract["core_dependency"] is False
    assert contract["snapshot_read_dependency"] is False
    assert contract["default_ranking_dependency"] is False

    target = contract["supported_targets"][0]
    for key in ("input", "constraints", "lock"):
        record = target[key]
        assert _sha256(ROOT / record["path"]) == record["sha256"]


def test_supported_target_gate_is_explicit_and_fail_closed() -> None:
    supported = {
        "implementation": "CPython",
        "python_minor": "3.12",
        "os": "linux",
        "architecture": "x86_64",
    }
    assert is_supported_target(supported)
    for key, value in (
        ("implementation", "PyPy"),
        ("python_minor", "3.13"),
        ("os", "darwin"),
        ("architecture", "aarch64"),
    ):
        observed = dict(supported)
        observed[key] = value
        assert not is_supported_target(observed)


def test_semantic_lock_is_exact_single_wheel_closure() -> None:
    text = LOCK_PATH.read_text(encoding="utf-8")
    starts = _package_starts(text)
    assert len(starts) == 58
    assert text.count("--hash=sha256:") == len(starts)
    assert "sentence-transformers==5.6.0 \\" in text
    assert (
        "torch @ https://download-r2.pytorch.org/whl/cpu/"
        "torch-2.13.0%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl \\"
        in text
    )
    assert (
        "--hash=sha256:4ca4a9394b0c771238a4f73590fdbbc4debad85ed0fa63d026ae1b085da7d6e2"
        in text
    )
    assert all("==" in line or line.startswith("torch @ ") for line in starts)


def test_constraints_and_lock_package_versions_match() -> None:
    constraints = {
        name: version
        for name, version in re.findall(
            r"(?m)^([a-z0-9.-]+)==([^\s]+)$",
            CONSTRAINTS_PATH.read_text(encoding="utf-8"),
        )
    }
    starts = _package_starts(LOCK_PATH.read_text(encoding="utf-8"))
    locked: dict[str, str] = {}
    for line in starts:
        if line.startswith("torch @ "):
            locked["torch"] = "2.13.0+cpu"
        else:
            name, remainder = line.split("==", 1)
            locked[name] = remainder.split()[0]
    assert locked == constraints


def test_semantic_compiler_is_digest_pinned_and_model_offline() -> None:
    wrapper = (ROOT / "scripts/release/compile_semantic_lock.sh").read_text(
        encoding="utf-8"
    )
    compiler = (ROOT / "scripts/release/compile_semantic_lock.py").read_text(
        encoding="utf-8"
    )
    assert (
        "mcr.microsoft.com/playwright/python:v1.61.0-noble@sha256:"
        "a9731514f24121d1dcd25d58d0a38146646d290a5998fd80d3e533e7b5e21c69"
        in wrapper
    )
    assert '"HF_HUB_OFFLINE": "1"' in compiler
    assert '"TRANSFORMERS_OFFLINE": "1"' in compiler


def test_semantic_dependencies_do_not_leak_into_core_lock() -> None:
    core = RUNTIME_LOCK.read_text(encoding="utf-8").lower()
    assert "sentence-transformers" not in core
    assert re.search(r"(?m)^torch(?:==|\s@)", core) is None
    report = scan(ROOT)
    assert report["status"] == "pass", report["findings"]


def test_install_target_preparation_never_removes_existing_content(
    tmp_path: Path,
) -> None:
    target = tmp_path / "populated"
    target.mkdir()
    sentinel = target / "sentinel.txt"
    sentinel.write_text("keep me\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="existing contents are never removed"):
        _prepare_install_target(target)

    assert sentinel.read_text(encoding="utf-8") == "keep me\n"


def test_install_target_preparation_accepts_safe_targets_and_rejects_links(
    tmp_path: Path,
) -> None:
    new_target = tmp_path / "new"
    _prepare_install_target(new_target)
    assert new_target.is_dir()

    empty_target = tmp_path / "empty"
    empty_target.mkdir()
    _prepare_install_target(empty_target)
    assert list(empty_target.iterdir()) == []

    file_target = tmp_path / "file"
    file_target.write_text("not a directory\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="must be a directory"):
        _prepare_install_target(file_target)

    link_target = tmp_path / "link"
    link_target.symlink_to(empty_target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="must not be a symlink"):
        _prepare_install_target(link_target)
