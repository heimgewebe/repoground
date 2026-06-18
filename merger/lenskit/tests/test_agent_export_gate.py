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
    tmp_path: Path,
    status: str,
    *,
    observed_output_health: str | None = "pass",
    forbidden_inferences: list[str] | None = None,
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
    if forbidden_inferences is not None:
        report["forbidden_inferences"] = list(forbidden_inferences)
    path = tmp_path / "demo.bundle_health.post.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def _attach_diagnostic_artifact(
    manifest_path: Path,
    tmp_path: Path,
    *,
    forbidden_inferences: list[str],
    filename: str = "demo.retrieval_eval.json",
    authority: str = "diagnostic_signal",
) -> None:
    """Append an in-bundle diagnostic artifact carrying forbidden_inferences."""
    doc = {
        "metrics": {"total_queries": 0, "hits": 0, "stale_flag": False},
        "details": [],
        "forbidden_inferences": list(forbidden_inferences),
    }
    blob = json.dumps(doc, indent=2).encode("utf-8")
    (tmp_path / filename).write_bytes(blob)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"].append(
        {
            "role": "retrieval_eval_json",
            "path": filename,
            "content_type": "application/json",
            "bytes": len(blob),
            "sha256": _sha256(blob),
            "authority": authority,
            "canonicality": "diagnostic",
            "interpretation": {"mode": "role_only"},
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


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


@pytest.mark.parametrize("profile", ["agent-portable", "agent-safe"])
def test_canonical_agent_profiles_pass_when_post_emit_pass_and_redaction_true(tmp_path, profile):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile=profile,
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


def test_agent_facing_cannot_disable_redaction_requirement(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=False)
    _write_post_health(tmp_path, "pass")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent-portable",
        require_redaction=False,
    )

    assert report["status"] in {"blocked", "fail"}
    assert report["redaction_required"] is True
    assert any("cannot disable redaction requirement" in e for e in report["errors"])


def test_agent_facing_early_return_reports_redaction_required_when_disabled(tmp_path):
    missing_manifest = tmp_path / "missing.bundle.manifest.json"

    report = evaluate_agent_export_gate(
        manifest_path=str(missing_manifest),
        profile="agent-portable",
        require_redaction=False,
    )

    assert report["status"] == "blocked"
    assert report["redaction_required"] is True


@pytest.mark.parametrize("profile", ["local-search", "debug-full", "max-private", "forensic-strict"])
def test_internal_profiles_are_blocked_from_agent_export(tmp_path, profile):
    manifest = _write_manifest(tmp_path, redaction=False)
    _write_post_health(tmp_path, "pass")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile=profile,
        require_redaction=True,
    )

    assert report["status"] == "blocked"
    assert report["agent_facing"] is False
    assert any("not agent-exportable" in e for e in report["errors"])


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


# ---------------------------------------------------------------------------
# C2.1: additive, optional authority/risk_class self-declaration
# ---------------------------------------------------------------------------

def _valid_gate_report(tmp_path) -> dict:
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")
    return evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )


def test_c2_1_legacy_report_without_authority_stays_valid(tmp_path):
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _valid_gate_report(tmp_path)
    assert "authority" not in report
    assert "risk_class" not in report
    jsonschema.validate(instance=report, schema=schema)


def test_c2_1_correct_authority_risk_class_valid(tmp_path):
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _valid_gate_report(tmp_path)
    report["authority"] = "diagnostic_signal"
    report["risk_class"] = "diagnostic"
    jsonschema.validate(instance=report, schema=schema)


def test_c2_1_wrong_authority_invalid(tmp_path):
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _valid_gate_report(tmp_path)
    report["authority"] = "runtime_observation"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_c2_1_wrong_risk_class_invalid(tmp_path):
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _valid_gate_report(tmp_path)
    report["risk_class"] = "content"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


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


# ---------------------------------------------------------------------------
# C2.5 / C5 (L6): export-risk inference boundaries
# ---------------------------------------------------------------------------

_BLOCKING_INFERENCES = [
    "claims_true",
    "repo_understood",
    "answer_safe_without_citations",
    "retrieval_complete",
]


def test_c2_5_legacy_post_health_without_forbidden_inferences_passes(tmp_path):
    """Legacy documents that never declare forbidden_inferences stay clean."""
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass", forbidden_inferences=None)

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "pass"
    assert not any("forbidden inference" in e for e in report["errors"])


def test_c2_5_harmless_forbidden_inference_does_not_block(tmp_path):
    """A free-string forbidden inference outside the export-risk vocabulary is harmless."""
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(
        tmp_path,
        "pass",
        forbidden_inferences=["does_not_establish_claim_truth", "use_only_as_signal"],
    )

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "pass"
    assert not any("forbidden inference" in e for e in report["errors"])


@pytest.mark.parametrize("inference", _BLOCKING_INFERENCES)
def test_c2_5_blocking_inference_in_post_health_fails_agent_export(tmp_path, inference):
    """An export-risk inference forbidden by a diagnostic blocks agent-facing export."""
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass", forbidden_inferences=[inference])

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "fail"
    assert report["agent_facing"] is True
    assert any(
        "forbidden inference" in e and inference in e for e in report["errors"]
    )


def test_c2_5_blocking_inference_in_manifest_diagnostic_fails_agent_export(tmp_path):
    """forbidden_inferences on an in-bundle diagnostic artifact also blocks export."""
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")
    _attach_diagnostic_artifact(
        manifest, tmp_path, forbidden_inferences=["retrieval_complete"]
    )

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "fail"
    assert any("retrieval_complete" in e for e in report["errors"])


def test_c2_5_non_agent_facing_not_blocked_by_forbidden_inference(tmp_path):
    """Non-agent-facing profiles are evaluated separately and are not export-risk gated."""
    manifest = _write_manifest(tmp_path, redaction=False)
    _attach_diagnostic_artifact(
        manifest, tmp_path, forbidden_inferences=["claims_true"]
    )

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="human_review",
        require_redaction=True,
    )

    assert report["status"] == "pass"
    assert report["agent_facing"] is False
    assert not any("forbidden inference" in e for e in report["errors"])


def test_c2_5_non_diagnostic_authority_forbidden_inference_is_ignored(tmp_path):
    """forbidden_inferences are only read from diagnostic_signal artifacts (no overreach)."""
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")
    _attach_diagnostic_artifact(
        manifest,
        tmp_path,
        forbidden_inferences=["claims_true"],
        authority="navigation_index",
    )

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "pass"
    assert not any("forbidden inference" in e for e in report["errors"])


def test_c2_5_invalid_utf8_diagnostic_artifact_is_skipped(tmp_path):
    """A corrupt diagnostic artifact must not abort export-gate certification."""
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")

    bad_path = tmp_path / "bad.retrieval_eval.json"
    bad_blob = b"\xff\xfe\x00not-valid-utf8"
    bad_path.write_bytes(bad_blob)

    manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_doc["artifacts"].append(
        {
            "role": "retrieval_eval_json",
            "path": bad_path.name,
            "content_type": "application/json",
            "bytes": len(bad_blob),
            "sha256": _sha256(bad_blob),
            "authority": "diagnostic_signal",
            "canonicality": "diagnostic",
            "interpretation": {"mode": "role_only"},
        }
    )
    manifest.write_text(json.dumps(manifest_doc, indent=2), encoding="utf-8")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "pass"
    assert not any("forbidden inference" in e for e in report["errors"])


def test_c2_5_out_of_bundle_diagnostic_forbidden_inference_not_read(tmp_path):
    """A diagnostic path escaping the bundle is rejected, so its boundary is not read."""
    outside_doc = {"forbidden_inferences": ["claims_true"]}
    outside_blob = json.dumps(outside_doc, indent=2).encode("utf-8")
    (tmp_path.parent / "outside.retrieval_eval.json").write_bytes(outside_blob)

    manifest_path = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"].append(
        {
            "role": "retrieval_eval_json",
            "path": "../outside.retrieval_eval.json",
            "content_type": "application/json",
            "bytes": len(outside_blob),
            "sha256": _sha256(outside_blob),
            "authority": "diagnostic_signal",
            "canonicality": "diagnostic",
            "interpretation": {"mode": "role_only"},
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest_path),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "pass"
    assert not any("forbidden inference" in e for e in report["errors"])


def test_c2_5_blocked_report_validates_against_schema(tmp_path):
    """The export-risk failure path still emits a schema-valid gate report."""
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass", forbidden_inferences=["claims_true"])

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "fail"
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


# ---------------------------------------------------------------------------
# Agent-consumption surface advisory (non-blocking warnings)
# ---------------------------------------------------------------------------

def _append_artifact(
    manifest_path: Path,
    tmp_path: Path,
    *,
    role: str,
    filename: str,
    content: bytes,
    authority: str = "navigation_index",
    canonicality: str = "derived",
    content_type: str = "text/markdown",
) -> None:
    """Write a file and append a manifest artifact entry referencing it."""
    (tmp_path / filename).write_bytes(content)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"].append(
        {
            "role": role,
            "path": filename,
            "content_type": content_type,
            "bytes": len(content),
            "sha256": _sha256(content),
            "authority": authority,
            "canonicality": canonicality,
            "interpretation": {"mode": "role_only"},
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def test_agent_export_gate_warns_when_agent_entry_manifest_missing(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert "missing_agent_entry_manifest" in report["warnings"]
    assert report["status"] == "pass"
    assert report["errors"] == []


def test_agent_export_gate_warns_when_required_reading_protocol_missing(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert "missing_required_reading_protocol" in report["warnings"]
    assert report["status"] == "pass"
    assert report["errors"] == []


def test_agent_export_gate_warns_when_answer_compliance_checklist_missing(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")
    _append_artifact(
        manifest,
        tmp_path,
        role="agent_reading_pack",
        filename="demo.agent_reading_pack.md",
        content=b"# Agent Reading Pack\n\nNo checklist section here.\n",
    )

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert "missing_answer_compliance_checklist" in report["warnings"]
    assert "cannot_check_answer_compliance_checklist" not in report["warnings"]
    assert report["status"] == "pass"
    assert report["errors"] == []


def test_agent_export_gate_consumption_warnings_do_not_block_agent_export(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert report["status"] == "pass"
    assert report["errors"] == []
    assert "missing_agent_entry_manifest" in report["warnings"]
    assert "missing_required_reading_protocol" in report["warnings"]
    assert "cannot_check_answer_compliance_checklist" in report["warnings"]


def test_agent_export_gate_does_not_warn_when_consumption_surfaces_present(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")
    _append_artifact(
        manifest,
        tmp_path,
        role="agent_entry_manifest",
        filename="demo.agent_entry_manifest.json",
        content=b"{}",
        content_type="application/json",
    )
    _append_artifact(
        manifest,
        tmp_path,
        role="required_reading_protocol",
        filename="demo.required_reading_protocol.json",
        content=b"{}",
        content_type="application/json",
    )
    _append_artifact(
        manifest,
        tmp_path,
        role="agent_reading_pack",
        filename="demo.agent_reading_pack.md",
        content=b"# Agent Reading Pack\n\n## ANSWER_COMPLIANCE_CHECKLIST\n",
    )

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert "missing_agent_entry_manifest" not in report["warnings"]
    assert "missing_required_reading_protocol" not in report["warnings"]
    assert "missing_answer_compliance_checklist" not in report["warnings"]
    assert "cannot_check_answer_compliance_checklist" not in report["warnings"]
    assert report["status"] == "pass"


def test_agent_export_gate_warns_when_answer_compliance_checklist_cannot_be_checked(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")
    # Declare an agent_reading_pack artifact whose file is absent: the gate must
    # surface a cannot-check warning rather than guessing or blocking.
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["artifacts"].append(
        {
            "role": "agent_reading_pack",
            "path": "missing.agent_reading_pack.md",
            "content_type": "text/markdown",
            "bytes": 0,
            "sha256": _sha256(b""),
            "authority": "navigation_index",
            "canonicality": "derived",
            "interpretation": {"mode": "role_only"},
        }
    )
    manifest.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert "cannot_check_answer_compliance_checklist" in report["warnings"]
    assert "missing_answer_compliance_checklist" not in report["warnings"]
    assert report["status"] == "pass"
    assert report["errors"] == []


def test_agent_export_gate_requires_answer_compliance_heading_not_plain_text(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")
    # Pack contains the token as plain text, not as a ## heading — must still warn.
    _append_artifact(
        manifest,
        tmp_path,
        role="agent_reading_pack",
        filename="demo.agent_reading_pack.md",
        content=b"# Agent Reading Pack\n\nANSWER_COMPLIANCE_CHECKLIST\n",
    )

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert "missing_answer_compliance_checklist" in report["warnings"]
    assert "cannot_check_answer_compliance_checklist" not in report["warnings"]
    assert report["status"] == "pass"
    assert report["errors"] == []


def test_agent_export_gate_warns_when_agent_entry_manifest_artifact_has_no_path(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")
    # Role is declared but path is empty: _find_artifact_path must return None.
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["artifacts"].append({
        "role": "agent_entry_manifest",
        "path": "",
        "content_type": "application/json",
        "bytes": 0,
        "sha256": _sha256(b""),
        "authority": "navigation_index",
        "canonicality": "derived",
        "interpretation": {"mode": "role_only"},
    })
    manifest.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert "missing_agent_entry_manifest" in report["warnings"]
    assert report["status"] == "pass"
    assert report["errors"] == []


def test_agent_export_gate_warns_when_required_reading_protocol_artifact_has_no_path(tmp_path):
    manifest = _write_manifest(tmp_path, redaction=True)
    _write_post_health(tmp_path, "pass")
    # Role is declared but path is empty: _find_artifact_path must return None.
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["artifacts"].append({
        "role": "required_reading_protocol",
        "path": "",
        "content_type": "application/json",
        "bytes": 0,
        "sha256": _sha256(b""),
        "authority": "navigation_index",
        "canonicality": "derived",
        "interpretation": {"mode": "role_only"},
    })
    manifest.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    report = evaluate_agent_export_gate(
        manifest_path=str(manifest),
        profile="agent_minimal",
        require_redaction=True,
    )

    assert "missing_required_reading_protocol" in report["warnings"]
    assert report["status"] == "pass"
    assert report["errors"] == []
