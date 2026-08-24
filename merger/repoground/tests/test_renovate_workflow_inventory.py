from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
CHECKER = ROOT / "scripts/ci/check_workflow_control_plane.py"
REFRESH = ROOT / "scripts/ci/refresh_workflow_control_plane.py"


def _make_root(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "repo"
    workflow = root / ".github/workflows/example.yml"
    inventory = root / "config/workflow-control-plane.v1.json"
    workflow.parent.mkdir(parents=True)
    inventory.parent.mkdir(parents=True)
    raw = b"name: example\n"
    workflow.write_bytes(raw)
    payload = {
        "kind": "repoground.workflow_control_plane",
        "schema_version": 1,
        "task": "test-task",
        "revision_binding": {"base_revision": "abc", "observed_at": "test"},
        "workflows": [{
            "path": ".github/workflows/example.yml",
            "class": "required_protection",
            "rationale": "keep this metadata",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "sentinel": {"preserve": True},
        }],
        "counts_by_class": {"required_protection": 1},
        "sentinel_root": ["preserve", "order"],
    }
    inventory.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return root, workflow, inventory


def _run(script: Path, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def _without_identity(payload: dict) -> dict:
    result = copy.deepcopy(payload)
    for entry in result["workflows"]:
        entry.pop("sha256", None)
        entry.pop("bytes", None)
    return result


def test_refresh_repairs_intentional_drift_and_preserves_metadata(tmp_path: Path) -> None:
    root, workflow, inventory = _make_root(tmp_path)
    workflow.write_bytes(b"name: intentionally changed\n")
    assert _run(CHECKER, root).returncode == 1

    before = json.loads(inventory.read_text(encoding="utf-8"))
    refresh = _run(REFRESH, root)
    assert refresh.returncode == 0, refresh.stdout + refresh.stderr
    after = json.loads(inventory.read_text(encoding="utf-8"))

    assert _without_identity(after) == _without_identity(before)
    raw = workflow.read_bytes()
    assert after["workflows"][0]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert after["workflows"][0]["bytes"] == len(raw)
    assert _run(CHECKER, root).returncode == 0


def test_refresh_rejects_unclassified_workflow_without_mutating_inventory(tmp_path: Path) -> None:
    root, _, inventory = _make_root(tmp_path)
    (root / ".github/workflows/unclassified.yml").write_text("name: new\n", encoding="utf-8")
    before = inventory.read_bytes()
    refresh = _run(REFRESH, root)
    assert refresh.returncode == 1
    assert "unclassified workflow" in refresh.stdout
    assert inventory.read_bytes() == before


@pytest.mark.parametrize("mutation", ["duplicate", "non_yml", "unknown_class"])
def test_refresh_rejects_invalid_inventory_without_mutating_it(
    tmp_path: Path, mutation: str
) -> None:
    root, _, inventory = _make_root(tmp_path)
    payload = json.loads(inventory.read_text(encoding="utf-8"))
    if mutation == "duplicate":
        payload["workflows"].append(copy.deepcopy(payload["workflows"][0]))
    elif mutation == "non_yml":
        payload["workflows"][0]["path"] = ".github/workflows/example.yaml"
    else:
        payload["workflows"][0]["class"] = "mystery"
    inventory.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    before = inventory.read_bytes()
    assert _run(REFRESH, root).returncode == 1
    assert inventory.read_bytes() == before


def test_renovate_github_actions_updates_refresh_workflow_inventory() -> None:
    config = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))
    rules = [rule for rule in config["packageRules"] if rule.get("matchManagers") == ["github-actions"]]
    assert len(rules) == 1
    task = rules[0]["postUpgradeTasks"]
    assert task["commands"] == ["python3 scripts/ci/refresh_workflow_control_plane.py"]
    assert task["executionMode"] == "branch"
    assert task["fileFilters"] == [
        ".github/workflows/*.yml",
        "config/workflow-control-plane.v1.json",
    ]
