"""
Unit tests for core/post_emit_health.py (the post-emit bundle validator, PR A4).

Uses self-contained synthetic bundle manifests so the tests do not depend on the
full merge pipeline. The defining property: post_emit_health validates the FINAL
bundle surface (including the agent_reading_pack, which the in-pipeline
output_health cannot see) and is independent of the pre-emit output_health verdict.
"""

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from merger.lenskit.core import post_emit_health
from merger.lenskit.core import range_resolver
from merger.lenskit.core.post_emit_health import (
    DOES_NOT_MEAN,
    compute_post_emit_health,
    derive_post_health_path,
    write_post_emit_health,
)
from merger.lenskit.tests.bundle_fixtures import make_post_emit_bundle as _make_bundle

_CONTRACTS_DIR = Path(__file__).parent.parent / "contracts"
_POST_HEALTH_SCHEMA_PATH = _CONTRACTS_DIR / "post-emit-health.v1.schema.json"

_CANONICAL = b"# repo: demo\n\n## file: a.py\nx = 1\n"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()



def _inject_sqlite_index(manifest: Path) -> None:
    sqlite_bytes = b"not-a-real-sqlite-db-but-valid-manifest-bytes"
    filename = "demo.index.sqlite"
    (manifest.parent / filename).write_bytes(sqlite_bytes)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["artifacts"].append({
        "role": "sqlite_index",
        "path": filename,
        "content_type": "application/octet-stream",
        "bytes": len(sqlite_bytes),
        "sha256": _sha256(sqlite_bytes),
        "authority": "runtime_cache",
        "canonicality": "cache",
    })
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _replace_output_health_checks(manifest: Path, checks_value) -> None:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    health_entry = next(a for a in data["artifacts"] if a["role"] == "output_health")
    health_path = manifest.parent / health_entry["path"]
    health_doc = json.loads(health_path.read_text(encoding="utf-8"))
    health_doc["checks"] = checks_value
    health_bytes = json.dumps(health_doc, indent=2).encode("utf-8")
    health_path.write_bytes(health_bytes)
    health_entry["bytes"] = len(health_bytes)
    health_entry["sha256"] = _sha256(health_bytes)
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")



# ---------------------------------------------------------------------------
# Required tests
# ---------------------------------------------------------------------------


def test_post_emit_health_output_health_bridge_searchable_when_sqlite_checks_true(tmp_path):
    manifest = _make_bundle(
        tmp_path,
        health_checks={
            "sqlite_row_count_matches_chunk_count": True,
            "fts_content_non_empty": True,
        },
    )
    _inject_sqlite_index(manifest)

    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "pass"
    assert "searchable" in report["evidence_levels_reached"]


@pytest.mark.parametrize(
    "checks_value",
    [
        {"sqlite_row_count_matches_chunk_count": False, "fts_content_non_empty": True},
        {"sqlite_row_count_matches_chunk_count": None, "fts_content_non_empty": True},
        {"fts_content_non_empty": True},
        [
            {"name": "sqlite_row_count_matches_chunk_count", "status": "pass"},
            {"name": "fts_content_non_empty", "status": "pass"},
        ],
    ],
)
def test_post_emit_health_output_health_bridge_does_not_overstate_searchable(tmp_path, checks_value):
    manifest = _make_bundle(tmp_path)
    _inject_sqlite_index(manifest)
    _replace_output_health_checks(manifest, checks_value)

    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "pass"
    assert "searchable" not in report["evidence_levels_reached"]


def test_post_emit_health_respects_output_health_noise_hygiene_unavailable(tmp_path):
    manifest = _make_bundle(
        tmp_path,
        health_checks={
            "excluded_noise": {
                "count": 0,
                "samples": [],
                "patterns": [],
                "count_truncated": False,
            },
            "noise_hygiene": {
                "available": False,
                "excluded_noise_count": 0,
                "excluded_noise_samples": [],
                "patterns": [],
            },
        },
    )

    report = compute_post_emit_health(str(manifest))

    assert report["noise_hygiene"]["available"] is False
    assert report["noise_hygiene"]["excluded_noise_count"] is None


def test_post_emit_health_accepts_legacy_excluded_noise_list(tmp_path):
    manifest = _make_bundle(
        tmp_path,
        health_top_level={
            "excluded_noise": [
                {
                    "path": ".tmp/forensic-preflight-ci-canary/artifacts/forensic-preflight-canary.json"
                }
            ]
        },
    )

    report = compute_post_emit_health(str(manifest))

    assert report["noise_hygiene"]["available"] is True
    assert report["noise_hygiene"]["excluded_noise_count"] == 1


def test_post_emit_health_requires_agent_pack(tmp_path):
    """A bundle without an agent_reading_pack must not silently pass."""
    manifest = _make_bundle(tmp_path, include_pack=False)
    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "blocked"
    assert report["status"] != "pass"
    assert report["agent_pack"]["present"] is False
    pack_check = next(c for c in report["checks"] if c["name"] == "agent_pack_present")
    assert pack_check["status"] == "blocked"


def test_post_emit_health_independent_of_pre_health(tmp_path):
    """output_health.verdict=pass must never imply post_emit_health.status=pass."""
    manifest = _make_bundle(tmp_path, health_verdict="pass")
    # Introduce a post-emit-only defect: corrupt the pack so its hash mismatches.
    (tmp_path / "demo.agent_reading_pack.md").write_bytes(
        b"tampered content not in manifest hash\n"
    )

    report = compute_post_emit_health(str(manifest))

    # The pre-emit verdict is recorded as an observation ...
    assert report["output_health_verdict"] == "pass"
    # ... but the post-emit status is computed independently and fails.
    assert report["status"] == "fail"
    assert report["hash_mismatch_count"] >= 1
    assert report["independence_note"] == (
        "output_health.verdict=pass does not imply post_emit_health.status=pass"
    )


def test_post_emit_health_reports_evidence_level(tmp_path):
    """Evidence level is reported using the existing vocabulary."""
    manifest = _make_bundle(tmp_path)
    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "pass"
    # canonical_md + agent_reading_pack + chunk_index => navigable (no citation_map).
    assert report["evidence_level"] == "navigable"
    assert "readable" in report["evidence_levels_reached"]
    assert "navigable" in report["evidence_levels_reached"]
    assert "citable" not in report["evidence_levels_reached"]


def test_post_emit_health_detects_missing_artifact(tmp_path):
    """A manifest-declared artifact whose file is missing => fail."""
    manifest = _make_bundle(tmp_path)
    (tmp_path / "demo.chunk_index.jsonl").unlink()

    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "fail"
    assert report["missing_artifact_count"] >= 1
    paths_check = next(
        c for c in report["checks"] if c["name"] == "artifact_paths_exist"
    )
    assert paths_check["status"] == "fail"


def test_post_emit_health_detects_hash_mismatch(tmp_path):
    """A file whose content no longer matches the manifest hash => fail."""
    manifest = _make_bundle(tmp_path)
    (tmp_path / "demo.md").write_bytes(_CANONICAL + b"DRIFT\n")

    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "fail"
    assert report["hash_mismatch_count"] >= 1
    hashes_check = next(
        c for c in report["checks"] if c["name"] == "artifact_hashes_match"
    )
    assert hashes_check["status"] == "fail"


# ---------------------------------------------------------------------------
# Supporting coverage
# ---------------------------------------------------------------------------


def test_post_emit_health_clean_bundle_passes(tmp_path):
    manifest = _make_bundle(tmp_path)
    report = compute_post_emit_health(str(manifest))

    deps = report["dependencies"]["jsonschema"]
    assert deps == {
        "available": True,
        "required_for": [
            "manifest_schema",
            "range_ref_schema",
            "claim_evidence_map_schema",
        ],
        "effect": "full_validation_available",
    }
    assert report["status"] == "pass"
    assert report["errors"] == []
    assert report["agent_pack"]["self_role_ok"] is True
    # A clean bundle whose chunks carry canonical_range resolves a real range path.
    assert report["range_ref_resolution_status"] == "ok"
    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["manifest_schema_valid"]["validation"] == {
        "mode": "jsonschema",
        "engine": "jsonschema",
        "reason": "available",
    }
    assert by_name["range_ref_resolution"]["validation"] == {
        "mode": "jsonschema",
        "engine": "range_resolver",
        "reason": "available",
    }
    assert "repo_understood" in report["does_not_mean"]
    assert "answer_safe_without_citations" in report["does_not_mean"]
    assert set(DOES_NOT_MEAN).issubset(set(report["does_not_mean"]))


def test_post_emit_health_range_ref_legacy_content_range_ref(tmp_path):
    """Legacy chunks using content_range_ref still resolve via the fallback."""
    manifest = _make_bundle(tmp_path, range_key="content_range_ref")
    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "pass"
    assert report["range_ref_resolution_status"] == "ok"


def test_post_emit_health_range_ref_precheck_reports_actual_provenance(tmp_path):
    manifest = _make_bundle(tmp_path)
    chunk_bytes = (
        json.dumps(
            {
                "chunk_id": "c0",
                "path": "a.py",
                "canonical_range": ["not", "an", "object"],
            }
        )
        + "\n"
    ).encode("utf-8")
    (tmp_path / "demo.chunk_index.jsonl").write_bytes(chunk_bytes)

    manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))
    for artifact in manifest_doc["artifacts"]:
        if artifact.get("role") == "chunk_index_jsonl":
            artifact["bytes"] = len(chunk_bytes)
            artifact["sha256"] = _sha256(chunk_bytes)
            break
    manifest.write_text(json.dumps(manifest_doc, indent=2), encoding="utf-8")

    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "fail"
    assert report["range_ref_resolution_status"] == "fail"
    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["range_ref_resolution"]["validation"] == {
        "mode": "structural_precheck",
        "engine": "range_resolver",
        "reason": "malformed_range_ref",
    }
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_output_health_must_be_validated_not_declared(tmp_path):
    """A declared but tampered output_health must not be trusted nor boost coverage."""
    manifest = _make_bundle(tmp_path)  # includes a declared, hash-valid output_health
    # Tamper the file after the manifest (and its recorded hash) were written.
    (tmp_path / "demo.output_health.json").write_bytes(
        b'{"kind":"lenskit.output_health","verdict":"pass","tampered":true}\n'
    )

    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "fail"
    assert report["hash_mismatch_count"] >= 1
    assert report["output_health_verdict"] is None
    assert "diagnostic_full" not in report["evidence_levels_reached"]


def test_post_emit_health_checks_claim_evidence_map_when_present(tmp_path):
    manifest = _make_bundle(tmp_path, include_claim_map=True, include_citation=True)
    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "pass"
    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["claim_evidence_map_present"]["status"] == "pass"
    assert by_name["claim_evidence_map_hash_ok"]["status"] == "pass"
    assert by_name["claim_evidence_map_schema_valid"]["status"] == "pass"
    assert by_name["claim_evidence_map_schema_valid"]["validation"] == {
        "mode": "jsonschema",
        "engine": "jsonschema",
        "reason": "available",
    }


def test_post_emit_health_reports_jsonschema_degradation_machine_readably(
    tmp_path, monkeypatch
):
    manifest = _make_bundle(tmp_path, include_claim_map=True, include_citation=True)
    monkeypatch.setattr(post_emit_health, "jsonschema", None)
    monkeypatch.setattr(range_resolver, "jsonschema", None)

    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "warn"
    by_name = {item["name"]: item for item in report["checks"]}
    for check_name, engine in (
        ("manifest_schema_valid", "jsonschema"),
        ("range_ref_resolution", "range_resolver"),
        ("claim_evidence_map_schema_valid", "jsonschema"),
    ):
        check = by_name[check_name]
        assert check["status"] == "skipped"
        assert "jsonschema unavailable" in check["detail"]
        assert check["validation"] == {
            "mode": "skipped_unavailable",
            "engine": engine,
            "reason": "dependency_unavailable",
        }


def test_post_emit_health_reports_missing_claim_schema_machine_readably(
    tmp_path, monkeypatch
):
    manifest = _make_bundle(tmp_path, include_claim_map=True, include_citation=True)
    monkeypatch.setattr(
        post_emit_health,
        "_validate_claim_evidence_map_schema",
        lambda _doc: (
            "environment_error",
            "claim_evidence_map schema not found: claim-evidence-map.v1.schema.json",
        ),
    )

    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "warn"
    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["claim_evidence_map_schema_valid"]["validation"] == {
        "mode": "skipped_unavailable",
        "engine": "jsonschema",
        "reason": "schema_missing",
    }


def test_post_emit_health_fails_on_invalid_claim_map_schema(tmp_path):
    manifest = _make_bundle(tmp_path, include_claim_map=True, include_citation=True)
    bad_payload = b'{"kind":"wrong"}\n'
    (tmp_path / "demo.claim_evidence_map.json").write_bytes(bad_payload)
    manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))
    for art in manifest_doc["artifacts"]:
        if art.get("role") == "claim_evidence_map_json":
            art["bytes"] = len(bad_payload)
            art["sha256"] = _sha256(bad_payload)
            break
    manifest.write_text(json.dumps(manifest_doc, indent=2), encoding="utf-8")
    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "fail"
    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["claim_evidence_map_present"]["status"] == "pass"
    assert by_name["claim_evidence_map_hash_ok"]["status"] == "pass"
    assert by_name["claim_evidence_map_schema_valid"]["status"] == "fail"


def test_post_emit_health_claim_map_absence_reports_reason(tmp_path):
    manifest = _make_bundle(
        tmp_path,
        include_claim_map=False,
        claim_absence_reason="multi_repo_out_of_scope",
    )
    report = compute_post_emit_health(str(manifest))

    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["claim_evidence_map_present"]["status"] == "skipped"
    detail = by_name["claim_evidence_map_present"]["detail"]
    assert "claim_evidence_map_json absent" in detail
    assert "reason=multi_repo_out_of_scope" in detail
    assert "multi-repo aggregation is out of scope" in detail


def test_post_emit_health_output_validates_against_schema(tmp_path):
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    # Build distinct bundles in fresh dirs and validate each report against schema.
    for i, kwargs in enumerate(
        ({}, {"include_pack": False}, {"include_citation": True})
    ):
        sub = tmp_path / f"bundle_{i}"
        sub.mkdir()
        manifest = _make_bundle(sub, **kwargs)
        report = compute_post_emit_health(str(manifest))
        jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_reports_redaction_without_enforcing(tmp_path):
    """redaction=false must be reported but must NOT cause a fail (no enforcement)."""
    manifest = _make_bundle(tmp_path, redaction=False)
    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "pass"
    assert report["redaction_status"]["redact_secrets_enabled"] is False
    assert report["redaction_status"]["enforced"] is False


def test_post_emit_health_blocked_on_missing_manifest(tmp_path):
    report = compute_post_emit_health(str(tmp_path / "nope.bundle.manifest.json"))
    assert report["status"] == "blocked"
    assert report["bundle_run_id"] is None
    # Even the early-exit blocked report must be a schema-valid artifact.
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_self_role_misdeclared_fails(tmp_path):
    """A pack that declares itself as a canonical/content source is a defect."""
    manifest = _make_bundle(
        tmp_path, pack_authority="canonical_content", pack_canonicality="content_source"
    )
    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "fail"
    assert report["agent_pack"]["self_role_ok"] is False


def test_post_emit_health_no_require_agent_pack_relaxes_block(tmp_path):
    manifest = _make_bundle(tmp_path, include_pack=False)
    report = compute_post_emit_health(str(manifest), agent_pack_required=False)

    # Without the pack requirement the absence is not blocking; the rest is clean.
    assert report["status"] != "blocked"
    assert report["agent_pack"]["present"] is False


def test_post_emit_health_blocked_precedes_fail(tmp_path):
    """blocked takes precedence over fail: even when an inspectable defect exists,
    the absence of agent_reading_pack from the manifest makes the status blocked."""
    # Build without pack; also corrupt canonical so a hash defect is detectable.
    manifest = _make_bundle(tmp_path, include_pack=False)
    (tmp_path / "demo.md").write_bytes(_CANONICAL + b"CORRUPTION\n")

    report = compute_post_emit_health(str(manifest))

    # The hash defect is inspectable but the required certification surface is absent.
    assert report["status"] == "blocked"
    # The hash mismatch should still be captured in errors for transparency.
    assert report["hash_mismatch_count"] >= 1
    assert len(report["errors"]) >= 1


# ---------------------------------------------------------------------------
# C2.1: additive, optional authority/risk_class self-declaration
# ---------------------------------------------------------------------------


def _valid_post_emit_report(tmp_path) -> dict:
    manifest = _make_bundle(tmp_path)
    return compute_post_emit_health(str(manifest))


def test_c2_1_legacy_report_without_authority_stays_valid(tmp_path):
    """A report that omits authority/risk_class (current producer output) is valid."""
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _valid_post_emit_report(tmp_path)
    assert "authority" not in report
    assert "risk_class" not in report
    jsonschema.validate(instance=report, schema=schema)


def test_c2_1_correct_authority_risk_class_valid(tmp_path):
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _valid_post_emit_report(tmp_path)
    report["authority"] = "diagnostic_signal"
    report["risk_class"] = "diagnostic"
    jsonschema.validate(instance=report, schema=schema)


def test_c2_1_wrong_authority_invalid(tmp_path):
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _valid_post_emit_report(tmp_path)
    report["authority"] = "canonical_content"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_c2_1_wrong_risk_class_invalid(tmp_path):
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _valid_post_emit_report(tmp_path)
    report["risk_class"] = "content"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_write_post_emit_health_persists_unregistered_artifact(tmp_path):
    manifest = _make_bundle(tmp_path)
    manifest_before = manifest.read_text(encoding="utf-8")

    out, report = write_post_emit_health(str(manifest))

    assert out == derive_post_health_path(manifest.resolve())
    assert out.exists()
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["status"] == report["status"] == "pass"

    post_checks = {check["name"]: check for check in written["checks"]}

    expected = {
        "manifest_schema_valid": {
            "mode": "jsonschema",
            "engine": "jsonschema",
            "reason": "available",
        },
        "range_ref_resolution": {
            "mode": "jsonschema",
            "engine": "range_resolver",
            "reason": "available",
        },
        "claim_evidence_map_schema_valid": {
            "mode": "skipped_unavailable",
            "engine": "jsonschema",
            "reason": "check_not_applicable",
        },
    }
    for name, validation in expected.items():
        assert post_checks[name]["validation"] == validation

    # Persistence must NOT mutate the bundle manifest (no registration).
    assert manifest.read_text(encoding="utf-8") == manifest_before
    data = json.loads(manifest_before)
    assert all(a["role"] != "post_emit_health" for a in data["artifacts"])


def test_post_emit_health_schema_rejects_bad_validation_mode(tmp_path):
    report = _valid_post_emit_report(tmp_path)
    by_name = {item["name"]: item for item in report["checks"]}
    check = by_name["manifest_schema_valid"]
    check["validation"]["mode"] = "banana_mode"
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_schema_rejects_bad_validation_reason(tmp_path):
    report = _valid_post_emit_report(tmp_path)
    by_name = {item["name"]: item for item in report["checks"]}
    check = by_name["manifest_schema_valid"]
    check["validation"]["reason"] = "banana_reason"
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_schema_rejects_bad_validation_engine(tmp_path):
    report = _valid_post_emit_report(tmp_path)
    by_name = {item["name"]: item for item in report["checks"]}
    check = by_name["manifest_schema_valid"]
    check["validation"]["engine"] = "banana_engine"
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_schema_rejects_incomplete_validation(tmp_path):
    report = _valid_post_emit_report(tmp_path)
    by_name = {item["name"]: item for item in report["checks"]}
    check = by_name["manifest_schema_valid"]
    check["validation"] = {
        "mode": "jsonschema",
        "engine": "jsonschema",
    }
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_schema_accepts_legacy_check_without_validation(tmp_path):
    report = _valid_post_emit_report(tmp_path)
    by_name = {item["name"]: item for item in report["checks"]}
    check = by_name["manifest_schema_valid"]
    check.pop("validation", None)
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_write_post_emit_health_persists_claim_map_schema_validation(tmp_path):
    manifest = _make_bundle(tmp_path, include_claim_map=True, include_citation=True)
    out = derive_post_health_path(manifest)
    returned, report = write_post_emit_health(str(manifest))
    assert returned == out
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["status"] == report["status"] == "pass"
    post_checks = {check["name"]: check for check in written["checks"]}
    assert post_checks["claim_evidence_map_schema_valid"]["validation"] == {
        "mode": "jsonschema",
        "engine": "jsonschema",
        "reason": "available",
    }
    # Optional positive checks as requested
    assert post_checks["manifest_schema_valid"]["validation"] == {
        "mode": "jsonschema",
        "engine": "jsonschema",
        "reason": "available",
    }
    assert post_checks["range_ref_resolution"]["validation"] == {
        "mode": "jsonschema",
        "engine": "range_resolver",
        "reason": "available",
    }


def _get_base_peh_report():
    from merger.lenskit.core.post_emit_health import _assemble

    return _assemble(
        status="pass",
        run_id="test-run",
        bundle_run_id="bundle-run",
        manifest_path_str="bundle.manifest.json",
        checks=[],
        errors=[],
        warnings=[],
        jsonschema_available=True,
    )


def test_post_emit_health_schema_accepts_dependencies():
    report = _get_base_peh_report()
    report["dependencies"] = {
        "jsonschema": {
            "available": True,
            "required_for": [
                "manifest_schema",
                "range_ref_schema",
                "claim_evidence_map_schema",
            ],
            "effect": "full_validation_available",
        }
    }
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_schema_accepts_legacy_report_without_dependencies():
    report = _get_base_peh_report()
    if "dependencies" in report:
        del report["dependencies"]
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_schema_rejects_invalid_dependency_effect():
    report = _get_base_peh_report()
    report["dependencies"] = {
        "jsonschema": {
            "available": True,
            "required_for": [
                "manifest_schema",
                "range_ref_schema",
                "claim_evidence_map_schema",
            ],
            "effect": "invalid_effect",
        }
    }
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_schema_rejects_invalid_required_for():
    report = _get_base_peh_report()
    report["dependencies"] = {
        "jsonschema": {
            "available": True,
            "required_for": ["unknown_schema"],
            "effect": "full_validation_available",
        }
    }
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_schema_rejects_non_boolean_dependency_available():
    report = _get_base_peh_report()
    report["dependencies"] = {
        "jsonschema": {
            "available": "true",
            "required_for": [
                "manifest_schema",
                "range_ref_schema",
                "claim_evidence_map_schema",
            ],
            "effect": "full_validation_available",
        }
    }
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_schema_rejects_extra_dependency_name():
    report = _get_base_peh_report()
    report["dependencies"] = {
        "jsonschema": {
            "available": True,
            "required_for": [
                "manifest_schema",
                "range_ref_schema",
                "claim_evidence_map_schema",
            ],
            "effect": "full_validation_available",
        },
        "yaml": {
            "available": True,
            "required_for": [],
            "effect": "full_validation_available",
        },
    }
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_dependencies_reports_jsonschema_unavailable(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(post_emit_health, "jsonschema", None)

    manifest = _make_bundle(tmp_path)
    report = post_emit_health.compute_post_emit_health(str(manifest))

    assert report["dependencies"]["jsonschema"] == {
        "available": False,
        "required_for": [
            "manifest_schema",
            "range_ref_schema",
            "claim_evidence_map_schema",
        ],
        "effect": "validation_degraded",
    }


def test_post_emit_health_schema_rejects_empty_dependencies_object():
    report = _get_base_peh_report()
    report["dependencies"] = {}
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_schema_rejects_incomplete_required_for():
    report = _get_base_peh_report()
    report["dependencies"] = {
        "jsonschema": {
            "available": True,
            "required_for": ["manifest_schema"],
            "effect": "full_validation_available",
        }
    }
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_schema_rejects_dependency_available_effect_mismatch():
    report = _get_base_peh_report()
    report["dependencies"] = {
        "jsonschema": {
            "available": False,
            "required_for": [
                "manifest_schema",
                "range_ref_schema",
                "claim_evidence_map_schema",
            ],
            "effect": "full_validation_available",
        }
    }
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)

def test_post_emit_health_degradation_summary_lists_skipped_validation_classes(tmp_path, monkeypatch):
    manifest = _make_bundle(tmp_path, include_claim_map=True, include_citation=True)
    monkeypatch.setattr(post_emit_health, "jsonschema", None)
    monkeypatch.setattr(range_resolver, "jsonschema", None)

    report = compute_post_emit_health(str(manifest))

    assert report["degradation"]["status"] == "degraded"
    assert set(report["degradation"]["classes"]) >= {
        "jsonschema_unavailable",
        "schema_validation_skipped",
        "range_strict_unavailable",
        "claim_evidence_validation_skipped",
        "environment_degraded",
    }
    assert report["health_status_model"] == report["degradation"]["status_model"]
