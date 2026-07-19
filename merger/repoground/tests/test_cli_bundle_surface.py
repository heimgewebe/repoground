"""CLI tests for `lenskit bundle-surface validate`.

Exit codes: 0 = pass/warn, 1 = fail, 2 = blocked.
"""
import json
from pathlib import Path

from merger.repoground.cli.cmd_bundle_surface import _print_human_report
from merger.repoground.cli.main import main
from merger.repoground.core.post_emit_health import derive_post_health_path


_DUMMY_SHA = "0" * 64
_AGENT_PACK_V1_1_FRONT_DOOR = (
    "<!-- ARTIFACT:agent_reading_pack VERSION:v1.1 "
    "AUTHORITY:navigation_index CANONICALITY:derived -->\n"
    "## REQUIRED_READING_BY_TASK\n"
    "## WHEN_CANONICAL_MD_ONLY_IS_INSUFFICIENT\n"
    "## SIDECAR_USAGE_RULES\n"
    "## ANSWER_COMPLIANCE_CHECKLIST\n"
    "## DO_NOT_CLAIM\n"
    "- `change_impact` — relation or path proximity alone does not prove change impact.\n"
)
_PACK_PRESENT = _AGENT_PACK_V1_1_FRONT_DOOR + (
    "## CLAIM_EVIDENCE_MAP_SUMMARY\n"
    "- artifact: `x.cem.json`\n"
    "- claims: 1\n"
)
_PACK_ABSENT = _AGENT_PACK_V1_1_FRONT_DOOR + (
    "## CLAIM_EVIDENCE_MAP_SUMMARY\n"
    "- _No verified `claim_evidence_map_json` artifact present._\n"
)


def _make_bundle(tmp_path: Path, *, claim_present: bool, absence_reason=None) -> Path:
    artifacts = []
    (tmp_path / "x.md").write_text("# canon\n", encoding="utf-8")
    artifacts.append({"role": "canonical_md", "path": "x.md", "sha256": _DUMMY_SHA, "bytes": 8})

    pack_text = _PACK_PRESENT if claim_present else _PACK_ABSENT
    if not claim_present and absence_reason is not None:
        pack_text += f"- reason={absence_reason} (declared fixture gap)\n"
    (tmp_path / "x.pack.md").write_text(pack_text, encoding="utf-8")
    artifacts.append(
        {"role": "agent_reading_pack", "path": "x.pack.md", "sha256": _DUMMY_SHA, "bytes": 1}
    )

    if claim_present:
        (tmp_path / "x.cem.json").write_text("{}", encoding="utf-8")
        artifacts.append(
            {"role": "claim_evidence_map_json", "path": "x.cem.json", "sha256": _DUMMY_SHA, "bytes": 2}
        )

    links = {}
    if absence_reason is not None:
        links["claim_evidence_map_absence_reason"] = absence_reason

    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "cli-bs-run",
        "created_at": "2026-06-02T00:00:00Z",
        "generator": {
            "name": "repoground",
            "version": "dev",
            "config_sha256": "a" * 64,
            "runtime": {"module": "merger.repoground.core.merge", "python_version": "3.11.0"},
        },
        "artifacts": artifacts,
        "links": links,
        "capabilities": {"redaction": False},
    }
    mp = tmp_path / "x.bundle.manifest.json"
    mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    # Persist a controlled post_emit_health sidecar (status=pass) so the surface
    # is fully coherent; status propagation is unit-tested separately.
    derive_post_health_path(mp).write_text(
        json.dumps({"kind": "lenskit.post_emit_health", "version": "1.0", "status": "pass"}),
        encoding="utf-8",
    )
    return mp


def test_cli_claim_map_present_exit_0(tmp_path, capsys):
    mp = _make_bundle(tmp_path, claim_present=True)
    rc = main(["bundle-surface", "validate", "--manifest", str(mp), "--require", "claim-evidence-map", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pass"
    # The machine-readable headline check is always present in JSON output.
    assert any(c["name"] == "claim_evidence_map_surface" for c in out["checks"])


def test_cli_absent_with_reason_blocked_exit_2(tmp_path, capsys):
    mp = _make_bundle(tmp_path, claim_present=False, absence_reason="no_registry")
    rc = main(["bundle-surface", "validate", "--manifest", str(mp), "--require", "claim-evidence-map", "--json"])
    assert rc == 2  # blocked, NOT a silent pass under --require
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "blocked"


def test_cli_absent_without_reason_fails_exit_1(tmp_path, capsys):
    mp = _make_bundle(tmp_path, claim_present=False, absence_reason=None)
    rc = main(["bundle-surface", "validate", "--manifest", str(mp), "--require", "claim-evidence-map", "--json"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "fail"
    claim_check = next(c for c in out["checks"] if c["name"] == "claim_evidence_map_surface")
    assert claim_check["status"] == "fail"
    assert "silent absence" in claim_check["detail"]


def test_cli_json_contains_claim_surface_check(tmp_path, capsys):
    mp = _make_bundle(tmp_path, claim_present=True)
    rc = main(["bundle-surface", "validate", "--manifest", str(mp), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    names = {c["name"] for c in out["checks"]}
    assert "claim_evidence_map_surface" in names
    assert "generator_provenance" in names


def test_cli_emit_artifact_persists_sidecar(tmp_path):
    mp = _make_bundle(tmp_path, claim_present=True)
    rc = main(["bundle-surface", "validate", "--manifest", str(mp), "--emit-artifact"])
    assert rc == 0
    sidecar = tmp_path / "x.bundle_surface_validation.json"
    assert sidecar.is_file()
    doc = json.loads(sidecar.read_text(encoding="utf-8"))
    assert doc["kind"] == "lenskit.bundle_surface_validation"


def test_cli_missing_manifest_blocked_exit_2(tmp_path, capsys):
    rc = main(["bundle-surface", "validate", "--manifest", str(tmp_path / "nope.json"), "--json"])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "blocked"


def test_cli_human_output_without_require(tmp_path, capsys):
    mp = _make_bundle(tmp_path, claim_present=True)
    rc = main(["bundle-surface", "validate", "--manifest", str(mp)])
    assert rc == 0
    text = capsys.readouterr().out
    assert "Bundle Surface Validation: PASS" in text
    assert "claim_evidence_map_surface" in text


def test_cli_human_printer_uses_checkview_projection_for_mapping_shape(capsys):
    """Human printer can render mapping-shaped checks through CheckView projection.

    The bundle-surface producer remains list-shaped; this fixture proves the
    consumer is no longer hardwired to that one producer shape.
    """
    report = {
        "status": "pass",
        "bundle_manifest_path": "x.bundle.manifest.json",
        "bundle_run_id": "run",
        "require_claim_evidence_map": False,
        "checks": {
            "manifest_present": True,
            "range_ref_resolution": {
                "status": "pass",
                "reason": "range refs resolved",
            },
        },
        "does_not_mean": ["forensic_ready"],
    }

    _print_human_report(report)

    text = capsys.readouterr().out
    assert "manifest_present: True" in text
    assert "[pass] range_ref_resolution: range refs resolved" in text
