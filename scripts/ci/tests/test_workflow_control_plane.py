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


def test_same_length_codeql_ref_substitution_fails_inventory_gate(tmp_path: Path) -> None:
    """A changed action commit must fail even when the workflow byte length stays equal."""
    import re
    import shutil

    workflows = tmp_path / ".github" / "workflows"
    shutil.copytree(ROOT / ".github" / "workflows", workflows)
    config = tmp_path / "config"
    config.mkdir()
    shutil.copy2(ROOT / "config" / "workflow-control-plane.v1.json",
                 config / "workflow-control-plane.v1.json")

    codeql = workflows / "codeql.yml"
    original = codeql.read_bytes()
    matched = re.search(rb"github/codeql-action/init@([0-9a-f]{40})", original)
    assert matched is not None
    pin = matched.group(1)
    modified_pin = (b"0" if pin[:1] != b"0" else b"1") + pin[1:]
    tampered = original[:matched.start(1)] + modified_pin + original[matched.end(1):]
    assert tampered != original
    assert len(tampered) == len(original)
    codeql.write_bytes(tampered)

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci/check_workflow_control_plane.py"),
         "--root", str(tmp_path), "--format", "json"],
        check=False, capture_output=True, text=True, timeout=25,
    )
    report = json.loads(proc.stdout)
    assert proc.returncode != 0
    assert report["ok"] is False
    assert any("codeql.yml" in error and "sha256 drift" in error
               for error in report["errors"])
