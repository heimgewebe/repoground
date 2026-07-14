from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import jsonschema

from scripts.release.check_release_contract import scan
from scripts.release.compile_semantic_lock import is_supported_target

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "docs/release/semantic-extension-platforms.v1.json"
SCHEMA_PATH = (
    ROOT / "merger/lenskit/contracts/repobrief-semantic-platforms.v1.schema.json"
)
LOCK_PATH = ROOT / "requirements/repobrief-semantic-linux-x86_64-py312.lock.txt"
CONSTRAINTS_PATH = (
    ROOT / "requirements/repobrief-semantic-linux-x86_64-py312.constraints.txt"
)
RUNTIME_LOCK = ROOT / "requirements/repobrief-runtime.lock.txt"


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
