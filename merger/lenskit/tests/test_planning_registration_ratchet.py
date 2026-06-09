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
    # Ratchet may be invoked as either scripts.docmeta.check_planning_registration
    # (via python3 -m) or check_planning_registration.py (direct script path).
    assert (
        "scripts.docmeta.check_planning_registration" in text
        or "check_planning_registration.py" in text
    )
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


def test_workflow_ratchet_step_captures_exit_code_under_errexit():
    """The ratchet step must use || code=$? to capture the exit code."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "|| code=$?" in text, (
        "Ratchet step must use '|| code=$?' to capture exit code "
        "without breaking under 'set -uo pipefail'"
    )


def test_workflow_enforce_step_is_fail_closed():
    """Enforce step must validate that exit_code output is present before using it."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    # Enforce step must:
    # 1. Assign the output to a variable
    assert 'code="${{ steps.ratchet.outputs.exit_code }}"' in text
    # 2. Check if it's empty
    assert '[ -z "${code}" ]' in text or 'if [ -z' in text
    # 3. Fail with exit 2 on missing output
    assert 'exit 2' in text


def test_bash_errexit_semantics_with_code_variable():
    """Prove that code=0; cmd || code=$? correctly captures exit codes under errexit."""
    import subprocess
    import tempfile

    script = """
    set -uo pipefail
    code=0
    false || code=$?
    echo "${code}"
    """

    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    assert result.stdout.strip() == "1", f"Expected exit code 1, got {result.stdout.strip()}"


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
