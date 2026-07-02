import json
from pathlib import Path

import jsonschema

from merger.lenskit.cli.main import main
from merger.lenskit.core.constants import ArtifactRole
from merger.lenskit.core.required_reading import default_required_reading_protocol, resolve_required_reading
from merger.lenskit.tests.test_bundle_manifest_integration import _artifact_by_role, _make_minimal_bundle


def _linked_roles(manifest: dict) -> set[str]:
    links = manifest.get("links") if isinstance(manifest.get("links"), dict) else {}
    roles: set[str] = set()
    if links.get("post_emit_health_path"):
        roles.add("post_emit_health")
    if links.get("bundle_surface_validation_path"):
        roles.add("bundle_surface_validation")
    if links.get("export_safety_report_path"):
        roles.add("export_safety_report")
    return roles


def test_agent_surfaces_minimal_bundle_contract(tmp_path, capsys):
    artifacts, manifest, manifest_dir = _make_minimal_bundle(tmp_path, output_mode="dual")
    roles = {a["role"] for a in manifest["artifacts"]}
    available = roles | _linked_roles(manifest)

    assert ArtifactRole.CANONICAL_MD.value in roles
    assert ArtifactRole.AGENT_READING_PACK.value in roles
    assert ArtifactRole.AGENT_ENTRY_MANIFEST.value in roles
    assert ArtifactRole.OUTPUT_HEALTH.value in roles
    assert "post_emit_health" in available
    assert "bundle_surface_validation" in available

    entry = _artifact_by_role(manifest, ArtifactRole.AGENT_ENTRY_MANIFEST.value)
    payload = json.loads((manifest_dir / entry["path"]).read_text(encoding="utf-8"))
    schema = json.loads((Path(__file__).parent.parent / "contracts" / "agent-entry-manifest.v1.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=payload, schema=schema)
    surface_roles = {s["role"] for s in payload["available_surfaces"]}
    assert ArtifactRole.CANONICAL_MD.value in surface_roles
    assert ArtifactRole.AGENT_READING_PACK.value in surface_roles
    assert "post_emit_health" in surface_roles
    assert "bundle_surface_validation" in surface_roles
    assert "repo_understood" in payload["does_not_establish"]

    pack = _artifact_by_role(manifest, ArtifactRole.AGENT_READING_PACK.value)
    body = (manifest_dir / pack["path"]).read_text(encoding="utf-8")
    assert "## AGENT_ENTRY_MANIFEST" in body
    assert "## EXPORT_SAFETY_REPORT" in body
    assert "## WHAT_THIS_DOES_NOT_PROVE" in body
    assert "`security_export_review`" in body
    assert "`redaction_required`" in body
    assert "secret absence" in body

    report_path = tmp_path / "report.json"
    rc = main(["export-safety", "report", "--bundle-manifest", str(artifacts.bundle_manifest), "--profile", "local-private", "--out", str(report_path)])
    assert rc == 0
    assert capsys.readouterr().out == ""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report_schema = json.loads((Path(__file__).parent.parent / "contracts" / ("export" + "-safety-report.v1.schema.json")).read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=report_schema)
    assert report["kind"] == "lenskit.export_safety_report"
    assert report["status"] == "pass"
    assert report["profile"] == "local-private"
    assert "secret_absence" in report["does_not_establish"]

    profile = "security" + "_export" + "_review"
    protocol = default_required_reading_protocol()
    missing = resolve_required_reading(protocol, available, profile)
    assert missing["status"] == "fail"
    assert "export_safety_report" in missing["missing_required"]

    complete = resolve_required_reading(protocol, available | {"export_safety_report"}, profile)
    assert complete["status"] == "pass"
    assert complete["missing_required"] == []
    assert complete["missing_recommended"] == []
