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
BASELINE_SCHEMA_PATH = (
    REPO_ROOT
    / "merger/lenskit/contracts/planning-registration-baseline.v1.schema.json"
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
    # Must use python3 -m module form, not direct script path.
    assert "python3 -m scripts.docmeta.check_planning_registration" in text
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


# --------------------------------------------------------------------------- #
# 9. invalid_exceptions are a separate blocking class, not new_findings
# --------------------------------------------------------------------------- #


def test_invalid_exception_is_blocking_but_not_new_finding(fake_repo, tmp_path, capsys):
    write(
        fake_repo,
        "docs/blueprints/bad-exempt.md",
        "---\nstatus: active\nplanning_registration:\n"
        "  status: exempt\n  reason: just because\n---\nBody",
    )
    baseline_file = tmp_path / "baseline.json"
    write_baseline(baseline_file, [])

    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(baseline_file), "--format", "json"]
    )
    out = capsys.readouterr().out
    report = json.loads(out)

    assert exit_code == 1
    assert report["summary"]["new_findings"] == 0
    assert report["summary"]["invalid_exceptions"] == 1
    assert report["new_findings"] == []
    assert len(report["invalid_exceptions"]) == 1
    assert report["invalid_exceptions"][0]["code"] == check_plan.CODE_INVALID_EXCEPTION


# --------------------------------------------------------------------------- #
# 10. Committed baseline validates against the baseline contract schema
# --------------------------------------------------------------------------- #


def test_committed_baseline_validates_against_schema():
    import re as _re
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    schema = json.loads(BASELINE_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=schema)
    assert data["schema"] == check_plan.BASELINE_SCHEMA
    keys = [(e["path"], e["code"], e["id"]) for e in data["entries"]]
    assert keys == sorted(keys)
    id_re = _re.compile(r"^[0-9a-f]{16}$")
    for e in data["entries"]:
        assert id_re.match(e["id"]), f"id {e['id']!r} does not match pattern"


# --------------------------------------------------------------------------- #
# 11. partition_ratchet() itself filters invalid exceptions (core invariant)
# --------------------------------------------------------------------------- #


def test_partition_ratchet_excludes_invalid_exceptions_directly(fake_repo):
    """partition_ratchet() must not let INVALID_PLANNING_EXCEPTION into new/known,
    even when called with raw run_checks() output (no pre-filtering by caller)."""
    write(
        fake_repo,
        "docs/blueprints/bad-exempt.md",
        "---\nstatus: active\nplanning_registration:\n"
        "  status: exempt\n  reason: just because\n---\nBody",
    )
    findings = check_plan.run_checks()

    # Confirm the invalid exception is present in the raw findings.
    assert any(f["code"] == check_plan.CODE_INVALID_EXCEPTION for f in findings)

    # Call partition_ratchet directly with unfiltered findings — simulates a
    # caller that does not pre-filter, verifying the core invariant.
    new, known, resolved = check_plan.partition_ratchet(findings, [])
    assert new == []
    assert known == []
    assert resolved == []

    # Build the report to confirm the exception surfaces correctly.
    report = check_plan.build_report("ratchet", findings, None, False, new, known, resolved)
    assert report["summary"]["new_findings"] == 0
    assert report["summary"]["invalid_exceptions"] == 1
    assert report["new_findings"] == []
    assert len(report["invalid_exceptions"]) == 1
    assert report["invalid_exceptions"][0]["code"] == check_plan.CODE_INVALID_EXCEPTION


# --------------------------------------------------------------------------- #
# 12. Schemas reject empty code / path / kind
# --------------------------------------------------------------------------- #


def test_report_schema_rejects_empty_code_path_kind():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    base_finding = {
        "id": "abcdef0123456789",
        "code": "UNREGISTERED_PLANNING_ARTIFACT",
        "path": "docs/blueprints/x.md",
        "kind": "unregistered",
    }

    for field in ("code", "path", "kind"):
        bad = dict(base_finding, **{field: ""})
        bad_report = {
            "schema": "lenskit.planning_registration_report.v1",
            "created_at": "2026-01-01T00:00:00Z",
            "mode": "ratchet",
            "summary": {
                "current_findings": 1, "baseline_findings": 0,
                "new_findings": 1, "known_findings": 0,
                "resolved_findings": 0, "invalid_exceptions": 0,
            },
            "findings": [bad],
            "baseline": {"path": None, "loaded": False},
            "new_findings": [bad],
            "known_findings": [],
            "resolved_findings": [],
            "invalid_exceptions": [],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad_report, schema=schema)


def test_baseline_schema_rejects_empty_code_path_kind():
    schema = json.loads(BASELINE_SCHEMA_PATH.read_text(encoding="utf-8"))

    base_entry = {
        "id": "abcdef0123456789",
        "code": "UNREGISTERED_PLANNING_ARTIFACT",
        "path": "docs/blueprints/x.md",
        "kind": "unregistered",
        "reason": "test",
    }

    for field in ("code", "path", "kind"):
        bad_entry = dict(base_entry, **{field: ""})
        bad_baseline = {
            "schema": "lenskit.planning_registration_baseline.v1",
            "generated_at": "2026-01-01T00:00:00Z",
            "generator": "scripts/docmeta/check_planning_registration.py",
            "entries": [bad_entry],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad_baseline, schema=schema)


# --------------------------------------------------------------------------- #
# 13. load_baseline() runtime validation (entry-level)
# --------------------------------------------------------------------------- #

_VALID_ENTRY = {
    "id": "abcdef0123456789",
    "code": "UNREGISTERED_PLANNING_ARTIFACT",
    "path": "docs/blueprints/x.md",
    "kind": "unregistered",
    "reason": "legacy",
}


def _make_baseline(entries):
    return json.dumps({
        "schema": "lenskit.planning_registration_baseline.v1",
        "generated_at": "2026-01-01T00:00:00Z",
        "generator": "scripts/docmeta/check_planning_registration.py",
        "entries": entries,
    })


@pytest.mark.parametrize("field", ["code", "path", "kind"])
def test_baseline_entry_empty_required_string_is_config_error(fake_repo, tmp_path, field):
    bad = dict(_VALID_ENTRY, **{field: ""})
    bl = tmp_path / "baseline.json"
    bl.write_text(_make_baseline([bad]), encoding="utf-8")
    code = check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    )
    assert code == 2


@pytest.mark.parametrize("bad_id", [
    "not-a-hex-id",
    "abcdef",           # too short
    "ABCDEF0123456789", # uppercase not allowed
    "abcdef012345678z", # invalid char
])
def test_baseline_entry_invalid_id_is_config_error(fake_repo, tmp_path, bad_id):
    bad = dict(_VALID_ENTRY, id=bad_id)
    bl = tmp_path / "baseline.json"
    bl.write_text(_make_baseline([bad]), encoding="utf-8")
    code = check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    )
    assert code == 2


@pytest.mark.parametrize("field", ["id", "code", "path", "kind", "reason"])
def test_baseline_entry_missing_required_field_is_config_error(fake_repo, tmp_path, field):
    bad = {k: v for k, v in _VALID_ENTRY.items() if k != field}
    bl = tmp_path / "baseline.json"
    bl.write_text(_make_baseline([bad]), encoding="utf-8")
    code = check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    )
    assert code == 2


def test_baseline_entry_invalid_exception_code_is_config_error(fake_repo, tmp_path):
    bad = dict(_VALID_ENTRY, code=check_plan.CODE_INVALID_EXCEPTION)
    bl = tmp_path / "baseline.json"
    bl.write_text(_make_baseline([bad]), encoding="utf-8")
    code = check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    )
    assert code == 2


# --------------------------------------------------------------------------- #
# 14. Baseline eligibility: only UNREGISTERED_PLANNING_ARTIFACT is permitted
# --------------------------------------------------------------------------- #


def test_build_baseline_allows_only_unregistered_planning_artifacts():
    """build_baseline() retains only UNREGISTERED_PLANNING_ARTIFACT findings."""
    findings = [
        {
            "id": "abcdef0123456789",
            "code": check_plan.CODE_UNREGISTERED,
            "path": "docs/blueprints/x.md",
            "kind": "unregistered",
        },
        {
            "id": "bbbbbbbbbbbbbbbb",
            "code": check_plan.CODE_INVALID_EXCEPTION,
            "path": "docs/blueprints/y.md",
            "kind": "invalid_exception",
        },
        {
            "id": "cccccccccccccccc",
            "code": check_plan.CODE_CONTROL_FILE_MISSING,
            "path": "docs/tasks",
            "kind": "control_file",
        },
        {
            "id": "dddddddddddddddd",
            "code": check_plan.CODE_CONTROL_FILE_PARSE_ERROR,
            "path": "docs/tasks/board.md",
            "kind": "control_file",
        },
    ]
    result = check_plan.build_baseline(findings)
    codes_in_baseline = [e["code"] for e in result["entries"]]
    assert codes_in_baseline == [check_plan.CODE_UNREGISTERED]


@pytest.mark.parametrize("non_eligible_code", [
    check_plan.CODE_CONTROL_FILE_MISSING,
    check_plan.CODE_CONTROL_FILE_PARSE_ERROR,
    check_plan.CODE_INVALID_EXCEPTION,
])
def test_baseline_entry_non_eligible_code_is_config_error(fake_repo, tmp_path, non_eligible_code):
    """load_baseline() rejects any code that is not UNREGISTERED_PLANNING_ARTIFACT."""
    bad = dict(_VALID_ENTRY, code=non_eligible_code)
    bl = tmp_path / "baseline.json"
    bl.write_text(_make_baseline([bad]), encoding="utf-8")
    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    )
    assert exit_code == 2


def test_baseline_schema_rejects_control_file_code():
    """The baseline JSON schema enforces code = UNREGISTERED_PLANNING_ARTIFACT."""
    schema = json.loads(BASELINE_SCHEMA_PATH.read_text(encoding="utf-8"))
    for bad_code in [
        check_plan.CODE_CONTROL_FILE_MISSING,
        check_plan.CODE_CONTROL_FILE_PARSE_ERROR,
        check_plan.CODE_INVALID_EXCEPTION,
    ]:
        bad_baseline = {
            "schema": "lenskit.planning_registration_baseline.v1",
            "generated_at": "2026-01-01T00:00:00Z",
            "generator": "scripts/docmeta/check_planning_registration.py",
            "entries": [{
                "id": "abcdef0123456789",
                "code": bad_code,
                "path": "docs/blueprints/x.md",
                "kind": "unregistered",
                "reason": "test",
            }],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad_baseline, schema=schema)


# --------------------------------------------------------------------------- #
# 15. Workflow exit-code semantics and enforcement
# --------------------------------------------------------------------------- #


def _get_workflow_step_run(step_name_prefix):
    """Return the run script of a named step from task-index.yml."""
    import yaml
    wf = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    for job_data in wf.get("jobs", {}).values():
        for step in job_data.get("steps", []):
            if step.get("name", "").startswith(step_name_prefix):
                return step.get("run", "")
    raise ValueError(f"Step starting with {step_name_prefix!r} not found")


def test_workflow_ratchet_step_captures_exit_code_under_errexit():
    """Ratchet step must use || code=$? to safely capture exit code under errexit."""
    run = _get_workflow_step_run("Planning registration ratchet")
    assert "python3 -m scripts.docmeta.check_planning_registration" in run, \
        "Ratchet step must invoke the module form, not a direct script path"
    assert "code=0" in run, \
        "Ratchet step must initialise code=0 before the Python call"
    assert "|| code=$?" in run, \
        "Ratchet step must use '|| code=$?' to capture exit code without breaking under set -uo pipefail"
    assert 'echo "exit_code=${code}" >> "$GITHUB_OUTPUT"' in run, \
        "Ratchet step must write exit_code to GITHUB_OUTPUT"


def test_workflow_enforce_step_is_fail_closed():
    """Enforce step must be fail-closed: missing exit_code output → exit 2."""
    run = _get_workflow_step_run("Enforce ratchet result")
    assert 'code="${{ steps.ratchet.outputs.exit_code }}"' in run, \
        "Enforce step must read exit_code from ratchet step output"
    assert '[ -z "${code}" ]' in run, \
        "Enforce step must check for empty/missing exit_code"
    assert 'exit 2' in run, \
        "Enforce step must exit 2 when exit_code is missing"
    assert 'exit "${code}"' in run, \
        "Enforce step must propagate the ratchet exit code"


def test_bash_errexit_semantics_with_code_variable():
    """Prove that code=0; cmd || code=$? captures non-zero exit under set -euo pipefail."""
    import subprocess

    script = """
    set -euo pipefail
    code=0
    false || code=$?
    echo "${code}"
    """

    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Script aborted unexpectedly: {result.stderr}"
    assert result.stdout.strip() == "1", \
        f"Expected captured code 1, got {result.stdout.strip()!r}"


def test_bash_enforce_fail_closed_with_missing_output():
    """Prove that enforce step exits 2 when output is missing/empty."""
    import subprocess

    script = """
    set -euo pipefail
    code=""
    if [ -z "${code}" ]; then
      echo "ERROR: Missing ratchet exit_code output" >&2
      exit 2
    fi
    exit "${code}"
    """

    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, f"Expected exit 2, got {result.returncode}"
    assert "Missing ratchet exit_code output" in result.stderr


@pytest.mark.parametrize("code,expected_exit", [
    ("0", 0),
    ("1", 1),
    ("2", 2),
])
def test_bash_enforce_propagates_exit_code(code, expected_exit):
    """Enforce step must propagate the ratchet exit code unchanged when output is present."""
    import subprocess

    script = f"""
    set -euo pipefail
    code="{code}"
    if [ -z "${{code}}" ]; then
      echo "ERROR: Missing ratchet exit_code output" >&2
      exit 2
    fi
    exit "${{code}}"
    """

    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == expected_exit, \
        f"code={code!r}: expected exit {expected_exit}, got {result.returncode}"


# --------------------------------------------------------------------------- #
# 16. Baseline integrity: ID consistency & contract invariants (load-time)
# --------------------------------------------------------------------------- #


def _raw_baseline(entries, **overrides):
    """Build a baseline JSON string with optional top-level overrides."""
    doc = {
        "schema": "lenskit.planning_registration_baseline.v1",
        "generated_at": "2026-01-01T00:00:00Z",
        "generator": "scripts/docmeta/check_planning_registration.py",
        "entries": entries,
    }
    doc.update(overrides)
    return json.dumps(doc)


def test_baseline_id_must_match_computed_id(fake_repo, tmp_path, capsys):
    """A pattern-valid but computationally wrong baseline id is a config error,
    and must NOT let the finding be tolerated as known."""
    write(fake_repo, "docs/blueprints/legacy.md", "---\nstatus: active\n---\nBody")
    code = check_plan.CODE_UNREGISTERED
    path = "docs/blueprints/legacy.md"
    kind = "unregistered"
    correct = check_plan.compute_finding_id(code, path, kind)
    wrong = "0" * 16 if correct != "0" * 16 else "1" * 16
    entry = {"id": wrong, "code": code, "path": path, "kind": kind, "reason": "forged"}
    bl = tmp_path / "baseline.json"
    bl.write_text(_raw_baseline([entry]), encoding="utf-8")

    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    )
    err = capsys.readouterr().err
    assert exit_code == 2
    assert "does not match" in err and wrong in err


def test_baseline_unexpected_top_level_field_blocks(fake_repo, tmp_path):
    bl = tmp_path / "baseline.json"
    bl.write_text(_raw_baseline([], surprise=True), encoding="utf-8")
    assert check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    ) == 2


def test_baseline_wrong_generator_blocks(fake_repo, tmp_path):
    bl = tmp_path / "baseline.json"
    bl.write_text(_raw_baseline([], generator="totally/wrong.py"), encoding="utf-8")
    assert check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    ) == 2


@pytest.mark.parametrize("bad_ts", ["", "2026-01-01", "not-a-date", "2026-01-01 00:00:00"])
def test_baseline_bad_generated_at_blocks(fake_repo, tmp_path, bad_ts):
    bl = tmp_path / "baseline.json"
    bl.write_text(_raw_baseline([], generated_at=bad_ts), encoding="utf-8")
    assert check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    ) == 2


def test_baseline_entry_unexpected_field_blocks(fake_repo, tmp_path):
    path = "docs/blueprints/legacy.md"
    eid = check_plan.compute_finding_id(check_plan.CODE_UNREGISTERED, path, "unregistered")
    entry = {
        "id": eid, "code": check_plan.CODE_UNREGISTERED, "path": path,
        "kind": "unregistered", "reason": "legacy", "extra": "nope",
    }
    bl = tmp_path / "baseline.json"
    bl.write_text(_raw_baseline([entry]), encoding="utf-8")
    assert check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    ) == 2


def test_baseline_duplicate_ids_block(fake_repo, tmp_path):
    path = "docs/blueprints/legacy.md"
    eid = check_plan.compute_finding_id(check_plan.CODE_UNREGISTERED, path, "unregistered")
    entry = {"id": eid, "code": check_plan.CODE_UNREGISTERED, "path": path,
             "kind": "unregistered", "reason": "legacy"}
    bl = tmp_path / "baseline.json"
    bl.write_text(_raw_baseline([dict(entry), dict(entry)]), encoding="utf-8")
    assert check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    ) == 2


def test_baseline_unsorted_entries_block(fake_repo, tmp_path):
    p1, p2 = "docs/blueprints/aaa.md", "docs/blueprints/bbb.md"
    e1 = {"id": check_plan.compute_finding_id(check_plan.CODE_UNREGISTERED, p1, "unregistered"),
          "code": check_plan.CODE_UNREGISTERED, "path": p1, "kind": "unregistered", "reason": ""}
    e2 = {"id": check_plan.compute_finding_id(check_plan.CODE_UNREGISTERED, p2, "unregistered"),
          "code": check_plan.CODE_UNREGISTERED, "path": p2, "kind": "unregistered", "reason": ""}
    bl = tmp_path / "baseline.json"
    # Deliberately reversed (bbb before aaa) -> not canonical order.
    bl.write_text(_raw_baseline([e2, e1]), encoding="utf-8")
    assert check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    ) == 2


def test_committed_baseline_loads_under_strict_runtime_validation():
    """The committed repo baseline must satisfy the hardened load-time invariants."""
    data = check_plan.load_baseline(str(BASELINE_PATH))
    assert data["schema"] == check_plan.BASELINE_SCHEMA
    assert data["generator"] == check_plan.GENERATOR


# --------------------------------------------------------------------------- #
# 17. --update-baseline refuses to grandfather defective state
# --------------------------------------------------------------------------- #


def test_update_baseline_blocks_on_invalid_exception(fake_repo, tmp_path, capsys):
    write(
        fake_repo,
        "docs/blueprints/bad-exempt.md",
        "---\nstatus: active\nplanning_registration:\n  status: exempt\n  reason: x\n---\nBody",
    )
    bl = tmp_path / "baseline.json"
    exit_code = check_plan.main(
        ["--update-baseline", "--baseline", str(bl), "--format", "json"]
    )
    out = capsys.readouterr().out
    report = json.loads(out)
    assert exit_code == 1
    assert report["summary"]["invalid_exceptions"] == 1
    # The baseline must NOT be written: no "resolved" stamp on a broken structure.
    assert not bl.exists()


def test_update_baseline_does_not_grandfather_invalid_exception_into_entries(fake_repo, tmp_path):
    write(
        fake_repo,
        "docs/blueprints/bad-exempt.md",
        "---\nstatus: active\nplanning_registration:\n  status: exempt\n  reason: x\n---\nBody",
    )
    findings = check_plan.run_checks()
    baseline = check_plan.build_baseline(findings)
    assert baseline["entries"] == []


# --------------------------------------------------------------------------- #
# 18. Control-file errors: own blocking class, exit 2, never baseline-eligible
# --------------------------------------------------------------------------- #


def test_control_file_error_blocks_ratchet_with_exit_2(fake_repo, tmp_path, capsys):
    (fake_repo / "docs/tasks/index.json").unlink()
    bl = tmp_path / "baseline.json"
    write_baseline(bl, [])

    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    )
    report = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert report["summary"]["control_errors"] >= 1
    assert report["summary"]["new_findings"] == 0  # not misclassified as drift
    assert any(
        f["code"] == check_plan.CODE_CONTROL_FILE_MISSING for f in report["control_errors"]
    )


def test_control_file_error_blocks_update_baseline_with_exit_2(fake_repo, tmp_path):
    (fake_repo / "docs/tasks/index.json").unlink()
    bl = tmp_path / "baseline.json"
    exit_code = check_plan.main(
        ["--update-baseline", "--baseline", str(bl), "--format", "json"]
    )
    assert exit_code == 2
    assert not bl.exists()


def test_control_file_error_excluded_from_ratchet_partition(fake_repo):
    (fake_repo / "docs/tasks/index.json").unlink()
    findings = check_plan.run_checks()
    assert any(f["code"] == check_plan.CODE_CONTROL_FILE_MISSING for f in findings)
    new, known, resolved = check_plan.partition_ratchet(findings, [])
    assert new == [] and known == []


def test_ratchet_report_with_control_errors_validates_against_schema(fake_repo, tmp_path, capsys):
    (fake_repo / "docs/tasks/index.json").unlink()
    bl = tmp_path / "baseline.json"
    write_baseline(bl, [])
    check_plan.main(["--ratchet", "--baseline", str(bl), "--format", "json"])
    report = json.loads(capsys.readouterr().out)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


# --------------------------------------------------------------------------- #
# 19. Fix A — generated_at calendar validation (strptime, not just regex)
# --------------------------------------------------------------------------- #


def test_baseline_calendar_invalid_date_blocks(fake_repo, tmp_path):
    """A regex-matching but calendar-invalid timestamp (e.g. month 99) must fail."""
    bl = tmp_path / "baseline.json"
    bl.write_text(_raw_baseline([], generated_at="2026-99-99T99:99:99Z"), encoding="utf-8")
    assert check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    ) == 2


# --------------------------------------------------------------------------- #
# 20. Fix B — baseline path canonicality enforcement
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad_path", [
    "/absolute/path.md",
    "/docs/blueprints/x.md",
])
def test_baseline_path_absolute_blocks(fake_repo, tmp_path, bad_path):
    entry = {
        "id": "abcdef0123456789",
        "code": check_plan.CODE_UNREGISTERED,
        "path": bad_path,
        "kind": "unregistered",
        "reason": "test",
    }
    bl = tmp_path / "baseline.json"
    bl.write_text(_raw_baseline([entry]), encoding="utf-8")
    assert check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    ) == 2


def test_baseline_path_traversal_blocks(fake_repo, tmp_path):
    entry = {
        "id": "abcdef0123456789",
        "code": check_plan.CODE_UNREGISTERED,
        "path": "../etc/passwd",
        "kind": "unregistered",
        "reason": "test",
    }
    bl = tmp_path / "baseline.json"
    bl.write_text(_raw_baseline([entry]), encoding="utf-8")
    assert check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    ) == 2


def test_baseline_path_backslash_blocks(fake_repo, tmp_path):
    entry = {
        "id": "abcdef0123456789",
        "code": check_plan.CODE_UNREGISTERED,
        "path": "docs\\blueprints\\x.md",
        "kind": "unregistered",
        "reason": "test",
    }
    bl = tmp_path / "baseline.json"
    bl.write_text(_raw_baseline([entry]), encoding="utf-8")
    assert check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    ) == 2


@pytest.mark.parametrize("bad_path", [
    "docs//blueprints/x.md",
    "./docs/blueprints/x.md",
    "docs/blueprints/../x.md",
])
def test_baseline_path_non_canonical_blocks(fake_repo, tmp_path, bad_path):
    entry = {
        "id": "abcdef0123456789",
        "code": check_plan.CODE_UNREGISTERED,
        "path": bad_path,
        "kind": "unregistered",
        "reason": "test",
    }
    bl = tmp_path / "baseline.json"
    bl.write_text(_raw_baseline([entry]), encoding="utf-8")
    assert check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    ) == 2


def test_baseline_path_dot_blocks(fake_repo, tmp_path):
    entry = {
        "id": "abcdef0123456789",
        "code": check_plan.CODE_UNREGISTERED,
        "path": ".",
        "kind": "unregistered",
        "reason": "test",
    }
    bl = tmp_path / "baseline.json"
    bl.write_text(_raw_baseline([entry]), encoding="utf-8")
    assert check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    ) == 2


# --------------------------------------------------------------------------- #
# 21. Fix C — docs/tasks/index.json structural validation
# --------------------------------------------------------------------------- #


def test_index_json_structural_root_not_object(fake_repo, tmp_path):
    (fake_repo / "docs/tasks/index.json").write_text('["not", "an", "object"]',
                                                      encoding="utf-8")
    bl = tmp_path / "baseline.json"
    write_baseline(bl, [])
    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    )
    assert exit_code == 2


def test_index_json_structural_tasks_not_list(fake_repo, tmp_path):
    (fake_repo / "docs/tasks/index.json").write_text('{"tasks": "not-a-list"}',
                                                      encoding="utf-8")
    bl = tmp_path / "baseline.json"
    write_baseline(bl, [])
    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    )
    assert exit_code == 2


def test_index_json_structural_task_not_object(fake_repo, tmp_path):
    (fake_repo / "docs/tasks/index.json").write_text('{"tasks": ["not-an-object"]}',
                                                      encoding="utf-8")
    bl = tmp_path / "baseline.json"
    write_baseline(bl, [])
    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    )
    assert exit_code == 2


def test_index_json_structural_evidence_entry_not_string(fake_repo, tmp_path):
    (fake_repo / "docs/tasks/index.json").write_text(
        '{"tasks": [{"id": "T-1", "evidence": [42]}]}', encoding="utf-8"
    )
    bl = tmp_path / "baseline.json"
    write_baseline(bl, [])
    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    )
    assert exit_code == 2


# --------------------------------------------------------------------------- #
# 22. Fix D — workflow summary step surfaces control_errors
# --------------------------------------------------------------------------- #


def test_workflow_summary_step_shows_control_errors():
    """Step summary must display control_errors count and list."""
    run = _get_workflow_step_run("Write step summary")
    assert "control_errors" in run, \
        "Summary step must reference control_errors from the report"


def test_workflow_summary_no_new_drift_excludes_control_errors():
    """'No new drift' message must not appear when control errors are present."""
    run = _get_workflow_step_run("Write step summary")
    assert "ctrl" in run, \
        "No-new-drift condition must reference ctrl (control errors)"


# --------------------------------------------------------------------------- #
# 23. Fix E — --update-baseline report includes written_baseline_entries
# --------------------------------------------------------------------------- #


def test_update_baseline_report_contains_written_baseline_entries(fake_repo, tmp_path, capsys):
    write(fake_repo, "docs/blueprints/legacy.md", "---\nstatus: active\n---\nBody")
    bl = tmp_path / "baseline.json"
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    exit_code = check_plan.main(
        ["--update-baseline", "--baseline", str(bl), "--format", "json"]
    )
    out = capsys.readouterr().out
    report = json.loads(out)

    assert exit_code == 0
    assert report["summary"]["written_baseline_entries"] == 1
    jsonschema.validate(instance=report, schema=schema)


# --------------------------------------------------------------------------- #
# 24. Frontmatter parser hardening: inline comments and multiline
# --------------------------------------------------------------------------- #


def test_inline_comment_after_quoted_expires_does_not_cause_bad_date(fake_repo, tmp_path):
    """An inline comment after a quoted expires value must not trigger exempt_bad_date."""
    write(
        fake_repo,
        "docs/blueprints/inline-expires.md",
        "---\nstatus: active\nplanning_registration:\n"
        "  status: exempt\n"
        '  reason: "temporary exception" # explanation\n'
        "  owner: ops\n"
        '  expires: "2999-12-31" # end of year\n'
        "---\nBody",
    )
    bl = tmp_path / "baseline.json"
    write_baseline(bl, [])
    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    )
    assert exit_code == 0, "Inline comment after quoted expires must not block"


def test_hash_inside_quotes_preserved_through_ratchet(fake_repo, tmp_path):
    """'#' inside quoted values must not be treated as a comment start."""
    write(
        fake_repo,
        "docs/blueprints/hash-in-val.md",
        "---\nstatus: active\nplanning_registration:\n"
        "  status: exempt\n"
        '  reason: "temporary # still reason"\n'
        '  owner: "ops#team"\n'
        '  expires: "2999-12-31"\n'
        "---\nBody",
    )
    bl = tmp_path / "baseline.json"
    write_baseline(bl, [])
    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    )
    assert exit_code == 0, "'#' inside quotes must not truncate the value"


def test_owner_nospace_hash_with_trailing_comment_is_valid(fake_repo, tmp_path):
    """owner: ops#team # inline comment — the '#' without preceding whitespace is
    not a comment start, so the value stays 'ops#team'; the space-prefixed '#' IS
    a comment start and is stripped.  The exemption must be valid (exit 0)."""
    write(
        fake_repo,
        "docs/blueprints/owner-nospace-hash.md",
        "---\nstatus: active\nplanning_registration:\n"
        "  status: exempt\n"
        "  reason: temporary accepted drift\n"
        "  owner: ops#team # inline comment\n"
        "  expires: 2999-12-31\n"
        "---\nBody",
    )
    bl = tmp_path / "baseline.json"
    write_baseline(bl, [])
    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    )
    assert exit_code == 0, "ops#team owner with trailing inline comment must yield valid exemption"


def test_expires_nospace_hash_is_bad_date(fake_repo, tmp_path, capsys):
    """expires: 2099-12-31#no-space — '#' without preceding whitespace is not a
    comment, so the value is '2099-12-31#no-space', which is not a valid ISO date.
    The ratchet must block with exit 1 (invalid_exception / exempt_bad_date)."""
    write(
        fake_repo,
        "docs/blueprints/expires-nospace-hash.md",
        "---\nstatus: active\nplanning_registration:\n"
        "  status: exempt\n"
        "  reason: temporary accepted drift\n"
        "  owner: ops\n"
        "  expires: 2099-12-31#no-space\n"
        "---\nBody",
    )
    bl = tmp_path / "baseline.json"
    write_baseline(bl, [])
    import io, json as _json
    out = io.StringIO()
    with __import__("unittest.mock", fromlist=["patch"]).patch("sys.stdout", out):
        exit_code = check_plan.main(
            ["--ratchet", "--baseline", str(bl), "--format", "json"]
        )
    report = _json.loads(out.getvalue())
    assert exit_code == 1, "no-space hash in expires must produce exit 1"
    assert len(report["invalid_exceptions"]) == 1, "must have exactly one invalid exception"
    assert report["invalid_exceptions"][0]["kind"] == "exempt_bad_date"
    assert report["new_findings"] == [], "invalid exceptions must not appear in new_findings"


def test_invalid_exemption_suggestion_mentions_single_line_only(fake_repo):
    """Suggestion for an invalid exemption must mention single-line scalar support."""
    write(
        fake_repo,
        "docs/blueprints/bad-exempt.md",
        "---\nstatus: active\nplanning_registration:\n"
        "  status: exempt\n"
        "  reason: some reason\n"
        "  owner: ops\n"
        "  expires: not-a-date\n"
        "---\nBody",
    )
    findings = check_plan.run_checks()
    invalid = [f for f in findings if f["code"] == check_plan.CODE_INVALID_EXCEPTION]
    assert len(invalid) == 1
    assert "single-line scalar values only" in invalid[0]["suggestion"]


# --------------------------------------------------------------------------- #
# 25. Block-scalar indicator detection (exempt_unsupported_scalar)
# --------------------------------------------------------------------------- #


def test_block_scalar_reason_blocks_ratchet_with_exit_1(fake_repo, tmp_path, capsys):
    """reason: > with an otherwise-valid block must produce exit 1 (invalid exception)."""
    write(
        fake_repo,
        "docs/blueprints/block-reason.md",
        "---\nstatus: active\nplanning_registration:\n"
        "  status: exempt\n"
        "  reason: >\n"
        "    long reason text\n"
        "  owner: ops\n"
        "  expires: 2999-12-31\n"
        "---\nBody",
    )
    bl = tmp_path / "baseline.json"
    write_baseline(bl, [])

    exit_code = check_plan.main(
        ["--ratchet", "--baseline", str(bl), "--format", "json"]
    )
    out = capsys.readouterr().out
    report = json.loads(out)

    assert exit_code == 1, "Block-scalar reason must block with exit 1"
    assert report["summary"]["invalid_exceptions"] == 1
    assert report["summary"]["new_findings"] == 0
    assert report["new_findings"] == []
    assert len(report["invalid_exceptions"]) == 1
    assert report["invalid_exceptions"][0]["kind"] == "exempt_unsupported_scalar"


def test_block_scalar_finding_not_written_to_baseline(fake_repo):
    """build_baseline() must not include an exempt_unsupported_scalar finding."""
    write(
        fake_repo,
        "docs/blueprints/block-reason.md",
        "---\nstatus: active\nplanning_registration:\n"
        "  status: exempt\n"
        "  reason: >\n"
        "    long reason\n"
        "  owner: ops\n"
        "  expires: 2999-12-31\n"
        "---\nBody",
    )
    findings = check_plan.run_checks()
    assert any(f["code"] == check_plan.CODE_INVALID_EXCEPTION for f in findings)
    baseline = check_plan.build_baseline(findings)
    assert baseline["entries"] == []
