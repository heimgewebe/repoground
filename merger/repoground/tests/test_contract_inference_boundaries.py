import json
from pathlib import Path

import jsonschema
import pytest

_CONTRACTS_DIR = Path(__file__).parent.parent / "contracts"


def _load_schema(name: str) -> dict:
    return json.loads((_CONTRACTS_DIR / name).read_text(encoding="utf-8"))


def _post_emit_health_doc() -> dict:
    return {
        "kind": "lenskit.post_emit_health",
        "version": "1.0",
        "run_id": "pe-run",
        "checked_at": "2026-05-28T00:00:00Z",
        "bundle_manifest_path": "/tmp/demo.bundle.manifest.json",
        "status": "pass",
        "checks": [],
        "errors": [],
        "warnings": [],
        "does_not_mean": ["repo_understood", "answer_safe_without_citations"],
        "independence_note": "output_health.verdict=pass does not imply post_emit_health.status=pass",
        "artifact_count_checked": 0,
        "hash_mismatch_count": 0,
        "missing_artifact_count": 0,
    }


def _agent_export_gate_doc() -> dict:
    return {
        "kind": "lenskit.agent_export_gate",
        "version": "1.0",
        "status": "pass",
        "profile": "agent_minimal",
        "agent_facing": True,
        "checked_at": "2026-05-28T00:00:00Z",
        "bundle_manifest_path": "/tmp/demo.bundle.manifest.json",
        "post_emit_health_status": "pass",
        "output_health_verdict_observed": "pass",
        "redaction_required": True,
        "redaction_enabled": True,
        "errors": [],
        "warnings": [],
        "does_not_mean": ["repo_understood", "answer_safe_without_citations", "claims_true"],
    }


def _retrieval_eval_doc() -> dict:
    return {
        "metrics": {"total_queries": 1, "hits": 0, "stale_flag": False},
        "details": [],
        "claim_boundaries": {
            "proves": ["index_returned_ranked_candidates"],
            "does_not_prove": ["retrieval_eval_does_not_prove_retrieval_completeness"],
            "evidence_basis": ["retrieval_metrics"],
            "requires_live_check": True,
        },
    }


def _context_quality_doc() -> dict:
    return {
        "kind": "lenskit.context_quality",
        "version": "1.0",
        "run_id": "cq-run",
        "checked_at": "2026-05-28T00:00:00Z",
        "bundle_manifest_path": "/tmp/demo.bundle.manifest.json",
        "bundle_run_id": "demo-run",
        "projection_status": "degraded",
        "authority": "diagnostic_signal",
        "risk_class": "diagnostic",
        "signals": {
            "manifest": {"available": False},
            "output_health": {"available": False},
            "post_emit_health": {"available": False},
            "retrieval_eval": {"available": False},
            "agent_export_gate": {"available": False},
            "evidence": {"available": False},
        },
        "agent_use_constraints": [
            "verify_content_against_canonical_md",
            "cite_canonical_ranges_for_claims",
            "do_not_treat_context_quality_as_repo_understanding",
            "do_not_treat_retrieval_metrics_as_completeness_proof",
            "do_not_treat_export_gate_as_claim_truth",
        ],
        "does_not_mean": [
            "repo_understood",
            "retrieval_complete",
            "answer_safe_without_citations",
            "claims_true",
        ],
        "warnings": [],
        "errors": [],
    }


_CONTRACT_CASES = [
    ("post-emit-health.v1.schema.json", _post_emit_health_doc),
    ("agent-export-gate.v1.schema.json", _agent_export_gate_doc),
    ("retrieval-eval.v1.schema.json", _retrieval_eval_doc),
    ("context-quality.v1.schema.json", _context_quality_doc),
]


@pytest.mark.parametrize(("schema_name", "doc_factory"), _CONTRACT_CASES)
def test_c2_3_inference_boundaries_are_optional(schema_name, doc_factory):
    schema = _load_schema(schema_name)
    doc = doc_factory()

    assert "allowed_inferences" not in doc
    assert "forbidden_inferences" not in doc
    jsonschema.validate(instance=doc, schema=schema)


@pytest.mark.parametrize(("schema_name", "doc_factory"), _CONTRACT_CASES)
def test_c2_3_accepts_plural_string_arrays(schema_name, doc_factory):
    schema = _load_schema(schema_name)
    doc = doc_factory()
    doc["allowed_inferences"] = ["use_as_diagnostic_signal"]
    doc["forbidden_inferences"] = ["does_not_establish_claim_truth"]

    jsonschema.validate(instance=doc, schema=schema)


@pytest.mark.parametrize(("schema_name", "doc_factory"), _CONTRACT_CASES)
@pytest.mark.parametrize("field", ["allowed_inferences", "forbidden_inferences"])
def test_c2_3_rejects_inference_boundary_scalar(schema_name, doc_factory, field):
    schema = _load_schema(schema_name)
    doc = doc_factory()
    doc[field] = "text"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=doc, schema=schema)


@pytest.mark.parametrize(("schema_name", "doc_factory"), _CONTRACT_CASES)
@pytest.mark.parametrize("field", ["allowed_inferences", "forbidden_inferences"])
def test_c2_3_rejects_inference_boundary_non_string_items(schema_name, doc_factory, field):
    schema = _load_schema(schema_name)
    doc = doc_factory()
    doc[field] = ["valid", 1]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=doc, schema=schema)


@pytest.mark.parametrize(("schema_name", "doc_factory"), _CONTRACT_CASES)
def test_c2_3_singular_inference_boundary_names_remain_unknown(schema_name, doc_factory):
    schema = _load_schema(schema_name)
    doc = doc_factory()
    doc["allowed_inference"] = ["use_as_diagnostic_signal"]
    doc["forbidden_inference"] = ["does_not_establish_claim_truth"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=doc, schema=schema)
