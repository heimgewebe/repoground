"""Tests for the Planning Drift Ratchet Control Plane (TASK-OPS-CTL-005).

Covers the scanner exemption flow, baseline/ratchet semantics, the JSON report
contract, and the CI workflow wiring. The scanner is exercised against a
synthetic repo tree by repointing its REPO_ROOT, mirroring the existing
scripts/docmeta/tests harness.
"""
import json
from pathlib import Path

import jsonschema
import pytest

import scripts.docmeta.check_planning_registration as check_plan

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = (
    REPO_ROOT
    / "merger/lenskit/contracts/planning-registration-report.v1.schema.json"
)
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/task-index.yml"
BASELINE_PATH = REPO_ROOT / "docs/tasks/planning-registration-baseline.json"

# Dates chosen so the suite never breaks over time.
FAR_FUTURE = "2999-12-31"
LONG_PAST = "2000-01-01"


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """A minimal repo tree with empty control files; scanner points here."""
    (tmp_path / "docs/tasks").mkdir(parents=True)
    (tmp_path / "docs/blueprints").mkdir(parents=True)
    (tmp_path / "docs/roadmap").mkdir(parents=True)
    (tmp_path / "docs/tasks/index.json").write_text('{"tasks":[]}', encoding="utf-8")
    (tmp_path / "docs/tasks/board.md").write_text("# Board", encoding="utf-8")
    (tmp_path / "docs/roadmap.md").write_text("# Roadmap", encoding="utf-8")
    monkeypatch.setattr(check_plan, "REPO_ROOT", str(tmp_path))
    return tmp_path


def write(root: Path, rel: str, content: str) -> None:
    full = root / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def write_baseline(path: Path, findings) -> None:
    doc = check_plan.build_baseline(findings)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. Scanner detects an unregistered planning document
# --------------------------------------------------------------------------- #


def test_scanner_detects_unregistered_planning_artifact(fake_repo):
    write(fake_repo, "docs/blueprints/new-plan.md", "---\nstatus: active\n---\nBody")
    findings = check_plan.run_checks()
    unreg = [f for f in findings if f["code"] == check_plan.CODE_UNREGISTERED]
    assert len(unreg) == 1
    f = unreg[0]
    assert f["path"] == "docs/blueprints/new-plan.md"
    assert f["id"] and len(f["id"]) == 16
    assert f["kind"] == "unregistered"


def test_finding_id_is_line_number_independent(fake_repo):
    write(fake_repo, "docs/blueprints/bp.md", "---\nstatus: active\n---\nHeading one")
    id_a = check_plan.run_checks()[0]["id"]
    # Shift the document down; the id must not move.
    write(fake_repo, "docs/blueprints/bp.md",
          "---\nstatus: active\n---\n\n\n\n# moved heading\nHeading one")
    id_b = check_plan.run_checks()[0]["id"]
    assert id_a == id_b


# --------------------------------------------------------------------------- #
# 2. Baseline tolerates known findings
# --------------------------------------------------------------------------- #


def test_baseline_tolerates_known_finding(fake_repo, tmp_path):
    write(fake_repo, "docs/blueprints/legacy.md", "---\nstatus: active\n---\nBody")
    current = check_plan.run_checks()
    baseline_file = tmp_path / "baseline.json"
    write_baseline(baseline_file, current)

    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(baseline_file), "--format", "json"]
    )
    assert exit_code == 0


def test_known_finding_appears_in_known_findings(fake_repo, tmp_path):
    write(fake_repo, "docs/blueprints/legacy.md", "---\nstatus: active\n---\nBody")
    current = check_plan.run_checks()
    baseline = check_plan.build_baseline(current)
    new, known, resolved = check_plan.partition_ratchet(current, baseline["entries"])
    assert not new
    assert [f["path"] for f in known] == ["docs/blueprints/legacy.md"]
    assert not resolved


# --------------------------------------------------------------------------- #
# 3. New findings block
# --------------------------------------------------------------------------- #


def test_new_finding_blocks(fake_repo, tmp_path):
    # Baseline built while clean (no findings).
    baseline_file = tmp_path / "baseline.json"
    write_baseline(baseline_file, [])
    # Now introduce drift.
    write(fake_repo, "docs/blueprints/sudden.md", "---\nstatus: active\n---\nBody")
    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(baseline_file), "--format", "json"]
    )
    assert exit_code == 1


def test_new_finding_partitioned_as_new(fake_repo):
    write(fake_repo, "docs/blueprints/sudden.md", "---\nstatus: active\n---\nBody")
    current = check_plan.run_checks()
    new, known, resolved = check_plan.partition_ratchet(current, [])
    assert [f["path"] for f in new] == ["docs/blueprints/sudden.md"]
    assert not known


# --------------------------------------------------------------------------- #
# 4. Resolved findings become stale, do not block
# --------------------------------------------------------------------------- #


def test_resolved_finding_is_stale_and_non_blocking(fake_repo, tmp_path):
    # Baseline records a finding that no longer exists in the current scan.
    stale = {
        "code": check_plan.CODE_UNREGISTERED,
        "path": "docs/blueprints/already-fixed.md",
        "kind": "unregistered",
        "reason": "old",
    }
    stale["id"] = check_plan.compute_finding_id(
        stale["code"], stale["path"], stale["kind"]
    )
    baseline_file = tmp_path / "baseline.json"
    write_baseline(baseline_file, [stale])

    # Current tree is clean -> the baseline entry is resolved/stale.
    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(baseline_file), "--format", "json"]
    )
    assert exit_code == 0

    current = check_plan.run_checks()
    baseline = check_plan.load_baseline(str(baseline_file))
    new, known, resolved = check_plan.partition_ratchet(current, baseline["entries"])
    assert [e["path"] for e in resolved] == ["docs/blueprints/already-fixed.md"]
    assert not new


# --------------------------------------------------------------------------- #
# 5. Invalid frontmatter exemption blocks
# --------------------------------------------------------------------------- #


def test_exempt_missing_fields_is_invalid_exception(fake_repo, tmp_path):
    write(
        fake_repo,
        "docs/blueprints/bad-exempt.md",
        "---\nstatus: active\nplanning_registration:\n  status: exempt\n  reason: just because\n---\nBody",
    )
    findings = check_plan.run_checks()
    invalid = [f for f in findings if f["code"] == check_plan.CODE_INVALID_EXCEPTION]
    assert len(invalid) == 1
    assert invalid[0]["kind"] == "exempt_missing_fields"

    # And it blocks in ratchet mode even with an empty baseline.
    baseline_file = tmp_path / "baseline.json"
    write_baseline(baseline_file, [])
    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(baseline_file), "--format", "json"]
    )
    assert exit_code == 1


def test_expired_exemption_is_invalid(fake_repo):
    write(
        fake_repo,
        "docs/blueprints/expired.md",
        "---\nstatus: active\nplanning_registration:\n"
        "  status: exempt\n  reason: temporary\n  owner: docs/tasks\n"
        f"  expires: {LONG_PAST}\n---\nBody",
    )
    findings = check_plan.run_checks()
    invalid = [f for f in findings if f["code"] == check_plan.CODE_INVALID_EXCEPTION]
    assert [f["kind"] for f in invalid] == ["exempt_expired"]


def test_invalid_exception_not_tolerated_by_baseline(fake_repo, tmp_path):
    # Even if a stale-shaped baseline tried to grandfather it, an invalid
    # exemption is never written to a baseline and always blocks.
    write(
        fake_repo,
        "docs/blueprints/bad-exempt.md",
        "---\nstatus: active\nplanning_registration:\n  status: exempt\n---\nBody",
    )
    findings = check_plan.run_checks()
    baseline = check_plan.build_baseline(findings)
    assert baseline["entries"] == []  # invalid exception is not baselined


# --------------------------------------------------------------------------- #
# 6. Valid frontmatter exemption suppresses the unregistered finding
# --------------------------------------------------------------------------- #


def test_valid_exemption_suppresses_finding(fake_repo):
    write(
        fake_repo,
        "docs/blueprints/exempt-ok.md",
        "---\nstatus: active\nplanning_registration:\n"
        "  status: exempt\n  reason: tracked elsewhere\n  owner: docs/tasks\n"
        f"  expires: {FAR_FUTURE}\n---\nBody",
    )
    findings = check_plan.run_checks()
    assert [f for f in findings if f["path"] == "docs/blueprints/exempt-ok.md"] == []


# --------------------------------------------------------------------------- #
# 7. JSON report validates against the contract schema
# --------------------------------------------------------------------------- #


def test_report_validates_against_schema(fake_repo, tmp_path, capsys):
    write(fake_repo, "docs/blueprints/drift.md", "---\nstatus: active\n---\nBody")
    baseline_file = tmp_path / "baseline.json"
    write_baseline(baseline_file, [])
    check_plan.main(
        ["--ratchet", "--baseline", str(baseline_file), "--format", "json"]
    )
    out = capsys.readouterr().out
    report = json.loads(out)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)
    assert report["mode"] == "ratchet"
    assert report["summary"]["new_findings"] == 1


def test_scan_and_update_reports_validate_against_schema(fake_repo, tmp_path, capsys):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    check_plan.main(["--format", "json"])
    scan_report = json.loads(capsys.readouterr().out)
    jsonschema.validate(instance=scan_report, schema=schema)
    assert scan_report["mode"] == "scan"

    baseline_file = tmp_path / "baseline.json"
    check_plan.main(
        ["--update-baseline", "--baseline", str(baseline_file), "--format", "json"]
    )
    update_report = json.loads(capsys.readouterr().out)
    jsonschema.validate(instance=update_report, schema=schema)
    assert update_report["mode"] == "update_baseline"


# --------------------------------------------------------------------------- #
# 8. Workflow contains the ratchet command
# --------------------------------------------------------------------------- #


def test_workflow_wires_ratchet():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "check_planning_registration.py" in text
    assert "--ratchet" in text
    assert "--baseline docs/tasks/planning-registration-baseline.json" in text
    assert "--format json" in text
    assert "upload-artifact" in text
    assert "GITHUB_STEP_SUMMARY" in text


# --------------------------------------------------------------------------- #
# Usage / config error handling (exit code 2)
# --------------------------------------------------------------------------- #


def test_ratchet_and_update_are_mutually_exclusive(fake_repo, tmp_path):
    code = check_plan.main(
        ["--ratchet", "--update-baseline", "--baseline", str(tmp_path / "b.json")]
    )
    assert code == 2


def test_ratchet_requires_baseline(fake_repo):
    assert check_plan.main(["--ratchet"]) == 2


def test_missing_baseline_file_is_config_error(fake_repo, tmp_path):
    code = check_plan.main(
        ["--ratchet", "--baseline", str(tmp_path / "nope.json"), "--format", "json"]
    )
    assert code == 2


def test_bad_schema_baseline_is_config_error(fake_repo, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema":"wrong","entries":[]}', encoding="utf-8")
    code = check_plan.main(
        ["--ratchet", "--baseline", str(bad), "--format", "json"]
    )
    assert code == 2


def test_corrupt_baseline_json_is_config_error(fake_repo, tmp_path):
    bad = tmp_path / "corrupt.json"
    bad.write_text("{not json", encoding="utf-8")
    code = check_plan.main(
        ["--ratchet", "--baseline", str(bad), "--format", "json"]
    )
    assert code == 2


# --------------------------------------------------------------------------- #
# Repo-level: the committed baseline is loadable and schema-correct
# --------------------------------------------------------------------------- #


def test_committed_baseline_is_valid():
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert data["schema"] == check_plan.BASELINE_SCHEMA
    assert isinstance(data["entries"], list)
    # Deterministic order invariant.
    keys = [(e["path"], e["code"], e["id"]) for e in data["entries"]]
    assert keys == sorted(keys)
