from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_workflow_control_plane_passes_on_repo_root() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci/check_workflow_control_plane.py"), "--root", str(ROOT), "--format", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["ok"] is True
    assert report["workflow_count"] >= 1


def test_entry_doc_links_pass_on_repo_root() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci/check_entry_doc_links.py"), "--root", str(ROOT), "--format", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["ok"] is True
    assert report["broken_count"] == 0


def test_inventory_classes_are_known() -> None:
    payload = json.loads((ROOT / "config/workflow-control-plane.v1.json").read_text())
    allowed = {
        "required_protection",
        "fast_feedback",
        "diagnostic",
        "operator_command",
        "historical_ballast",
    }
    for entry in payload["workflows"]:
        assert entry["class"] in allowed
