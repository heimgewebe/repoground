import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from merger.lenskit.core.agent_export_gate import evaluate_agent_export_gate


_CONTRACTS_DIR = Path(__file__).parent.parent / "contracts"
_SCHEMA_PATH = _CONTRACTS_DIR / "agent-export-gate.v1.schema.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_manifest(
    tmp_path: Path,
    *,
    redaction: bool,
    include_output_health: bool = True,
    output_health_verdict: str = "pass",
    output_health_path: str = "demo.output_health.json",
    run_id: object = "demo-run",
) -> Path:
    canonical = b"# repo: demo\n\nhello\n"
    (tmp_path / "demo.md").write_bytes(canonical)

    artifacts = [
        {
            "role": "canonical_md",
            "path": "demo.md",
            "content_type": "text/markdown",
            "bytes": len(canonical),
            "sha256": _sha256(canonical),
            "authority": "canonical_content",
            "canonicality": "content_source",
            "interpretation": {"mode": "role_only"},
        }
    ]

    if include_output_health:
        output_doc = {
            "kind": "lenskit.output_health",
            "version": "1.0",
            "run_id": "run-1",
            "created_at": "2026-05-23T00:00:00Z",
            "stem": "demo",
            "checks": {},
            "diagnostic_artifacts": {},
            "warnings": [],
            "errors": [],
            "verdict": output_health_verdict,
        }
        output_bytes = json.dumps(output_doc, indent=2).encode("utf-8")
        output_file = tmp_path / output_health_path
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(output_bytes)
        artifacts.append(
            {
                "role": "output_health",
            "path": output_health_path,
                "content_type": "application/json",
                "bytes": len(output_bytes),
                "sha256": _sha256(output_bytes),
                "authority": "diagnostic_signal",
                "canonicality": "diagnostic",
                "interpretation": {"mode": "role_only"},
            }
        )

    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "created_at": "2026-05-23T00:00:00Z",
        "generator": {"name": "test", "version": "1.0", "config_sha256": "a" * 64},
        "artifacts": artifacts,
        "links": {},
        "capabilities": {"fts5_bm25": False, "redaction": redaction},
    }
    if run_id is not ...:
        manifest["run_id"] = run_id
    path = tmp_path / "demo.bundle.manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def _write_post_health(
    tmp_path: Path, status: str, *, observed_output_health: str | None = "pass"
) -> Path:
    report = {
        "kind": "lenskit.post_emit_health",
        "version": "1.0",
        "run_id": "post-run",
        "bundle_run_id": "demo-run",
        "checked_at": "2026-05-23T00:00:00Z",
        "bundle_manifest_path": str(tmp_path / "demo.bundle.manifest.json"),
        "status": status,
        "checks": [],
        "errors": [],
        "warnings": [],
        "does_not_mean": ["repo_understood", "answer_safe_without_citations"],
        "independence_note": "output_health.verdict=pass does not imply post_emit_health.status=pass",
        "artifact_count_checked": 0,
        "hash_mismatch_count": 0,
        "missing_artifact_count": 0,
    }
    if observed_output_health is not None:
        report["output_health_verdict"] = observed_output_health
    path = tmp_path / "demo.bundle_health.post.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def test_agent_facing_pass_when_post_emit_pass_and_redaction_true(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "pass"
    assert report["agent_facing"] is True
    assert report["post_emit_health_status"] == "pass"
    assert report["redaction_required"] is True
    assert report["redaction_enabled"] is True


def test_agent_facing_post_emit_pass_bound_manifest_and_run_id_passes(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "pass"
    assert report["post_emit_health_status"] == "pass"


def test_missing_profile_is_blocked(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile=None,
        require_redaction=True,
    )

    assert report["status"] == "blocked"
    assert any("explicit profile" in e for e in report["errors"])


def test_unknown_profile_is_blocked(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_portable",
        require_redaction=True,
    )

    assert report["status"] == "blocked"
    assert any("unknown export profile" in e for e in report["errors"])


def test_agent_facing_blocks_when_manifest_run_id_missing(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True, run_id=...)
    _write_post_health(tmp_path, "pass")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "blocked"
    assert any("manifest run_id" in e for e in report["errors"])


def test_agent_facing_blocks_when_manifest_run_id_empty(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True, run_id="")
    _write_post_health(tmp_path, "pass")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "blocked"
    assert any("manifest run_id" in e for e in report["errors"])


def test_agent_facing_output_health_pass_but_missing_post_emit_not_pass(tmp_path):
    manifest = _write_manifest(
        tmp_path,
        redaction=True,
        include_output_health=True,
        output_health_verdict="pass",
    )

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["output_health_verdict_observed"] == "pass"
    assert report["status"] in {"blocked", "fail"}
    assert report["status"] != "pass"


def test_output_health_observation_does_not_read_outside_bundle(tmp_path):
    outside_doc = {
        "kind": "lenskit.output_health",
        "version": "1.0",
        "verdict": "pass",
    }
    outside_path = tmp_path.parent / "outside.output_health.json"
    outside_path.write_text(json.dumps(outside_doc, indent=2), encoding="utf-8")

    manifest = _write_manifest(
        tmp_path,
        redaction=True,
        output_health_path="../outside.output_health.json",
    )
    _write_post_health(tmp_path, "pass", observed_output_health=None)

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "pass"
    assert report["output_health_verdict_observed"] is None


def test_agent_facing_fails_when_post_emit_fail(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "fail")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "fail"
    assert report["post_emit_health_status"] == "fail"


def test_agent_facing_invalid_post_emit_kind_is_blocked(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    post = _write_post_health(tmp_path, "pass")
    doc = json.loads(post.read_text(encoding="utf-8"))
    doc["kind"] = "lenskit.output_health"
    post.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "blocked"


def test_agent_facing_invalid_post_emit_version_is_blocked(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    post = _write_post_health(tmp_path, "pass")
    doc = json.loads(post.read_text(encoding="utf-8"))
    doc["version"] = "2.0"
    post.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "blocked"


def test_agent_facing_invalid_post_emit_schema_is_blocked(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    post = _write_post_health(tmp_path, "pass")
    doc = json.loads(post.read_text(encoding="utf-8"))
    doc["does_not_mean"] = ["repo_understood"]
    post.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "blocked"


def test_agent_facing_post_emit_pass_empty_bundle_manifest_path_is_blocked(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    post = _write_post_health(tmp_path, "pass")
    doc = json.loads(post.read_text(encoding="utf-8"))
    doc["bundle_manifest_path"] = ""
    post.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "blocked"


def test_agent_facing_post_emit_pass_mismatched_bundle_manifest_path_is_blocked(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    post = _write_post_health(tmp_path, "pass")
    doc = json.loads(post.read_text(encoding="utf-8"))
    doc["bundle_manifest_path"] = str(tmp_path / "other.bundle.manifest.json")
    post.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "blocked"


def test_agent_facing_post_emit_pass_missing_bundle_run_id_is_blocked(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    post = _write_post_health(tmp_path, "pass")
    doc = json.loads(post.read_text(encoding="utf-8"))
    doc.pop("bundle_run_id", None)
    post.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "blocked"


def test_agent_facing_post_emit_pass_null_bundle_run_id_is_blocked(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    post = _write_post_health(tmp_path, "pass")
    doc = json.loads(post.read_text(encoding="utf-8"))
    doc["bundle_run_id"] = None
    post.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "blocked"


def test_agent_facing_post_emit_pass_empty_bundle_run_id_is_blocked(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    post = _write_post_health(tmp_path, "pass")
    doc = json.loads(post.read_text(encoding="utf-8"))
    doc["bundle_run_id"] = ""
    post.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "blocked"


def test_agent_facing_post_emit_bundle_run_id_mismatch_is_blocked(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    post = _write_post_health(tmp_path, "pass")
    doc = json.loads(post.read_text(encoding="utf-8"))
    doc["bundle_run_id"] = "different-run"
    post.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "blocked"


def test_agent_facing_fails_when_redaction_required_but_disabled(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=False)
    _write_post_health(tmp_path, "pass")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "fail"
    assert report["redaction_required"] is True
    assert report["redaction_enabled"] is False


def test_non_agent_human_review_profile_does_not_claim_agent_certification(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=False)

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="human_review",
        require_redaction=True,
    )

    assert report["status"] == "pass"
    assert report["agent_facing"] is False
    assert report["redaction_required"] is False
    assert any("does not certify agent-surface export" in w for w in report["warnings"])


def test_non_agent_human_review_stays_pass_when_require_redaction_false(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=False)
    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="human_review",
        require_redaction=False,
    )
    assert report["status"] == "pass"


def test_agent_export_gate_validates_against_schema(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_schema_rejects_does_not_mean_without_claims_true(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")
    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    bad = dict(report)
    bad["does_not_mean"] = ["repo_understood", "answer_safe_without_citations"]
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


def test_agent_export_gate_does_not_mutate_manifest(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")
    before = manifest.read_text(encoding="utf-8")

    _ = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    after = manifest.read_text(encoding="utf-8")
    assert after == before
