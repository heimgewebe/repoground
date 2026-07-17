import json
from pathlib import Path

import jsonschema
import pytest

CONTRACT_DIR = Path(__file__).parent.parent / "contracts"
REQUEST_SCHEMA = CONTRACT_DIR / "repobrief-ask-request.v1.schema.json"
CONTEXT_SCHEMA = CONTRACT_DIR / "repobrief-ask-context-pack.v1.schema.json"
NON_CLAIMS = [
    "actual_reading_proven",
    "answer_correct",
    "repo_understood",
    "all_relevant_context_used",
    "claims_true",
    "test_sufficiency",
    "regression_absence",
    "runtime_behavior",
    "forensic_ready",
    "merge_readiness",
    "security_correctness",
]
FORBIDDEN = [
    "implicit_refresh",
    "git_mutation",
    "snapshot_creation_on_read",
    "patch_application",
    "pull_request_mutation",
    "shell_execution",
    "merge_authorization",
]
SHA = "a" * 64


def _schema(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _request():
    return {
        "kind": "repobrief.ask_request",
        "version": "1.0",
        "request_id": "ask-1",
        "query": "What does the verifier check?",
        "task_profile": "basic_repo_question",
        "token_budget": {
            "max_context_tokens": 8000,
            "max_answer_tokens": 1200,
            "truncation_policy": "truncate_with_caveat",
        },
        "snapshot_policy": {
            "mode": "existing_snapshot_only",
            "freshness_policy": "allow_stale_with_caveat",
            "bundle_manifest": "demo.bundle.manifest.json",
        },
        "output_mode": "context_pack_and_scaffold",
        "forbidden_operations": FORBIDDEN,
        "does_not_establish": NON_CLAIMS,
    }


def _context_pack():
    caveat = {"kind": "unknown_freshness", "detail": "Freshness was not compared."}
    return {
        "kind": "repobrief.ask_context_pack",
        "version": "1.0",
        "request_id": "ask-1",
        "snapshot_ref": {
            "stem": "demo",
            "manifest_path": "demo.bundle.manifest.json",
            "manifest_sha256": SHA,
            "freshness_policy": "allow_stale_with_caveat",
            "freshness_status": "unknown",
        },
        "freshness": {"status": "unknown", "caveats": [caveat]},
        "availability": {"status": "partial", "caveats": [{"kind": "missing_artifact", "detail": "No optional graph."}]},
        "required_reading": {
            "task_profile": "basic_repo_question",
            "required": ["agent_reading_pack", "canonical_md"],
            "recommended": ["citation_map_jsonl"],
            "missing_required": [],
            "missing_recommended": ["citation_map_jsonl"],
            "status": "warn",
        },
        "retrieval_hits": [{"artifact_role": "canonical_md", "ref": "hit-1", "score": 1.0, "citation_id": "cit_0000000000000001"}],
        "resolved_ranges": [{"artifact_role": "canonical_md", "status": "resolved", "range_ref": {"file_path": "demo.md"}, "content_sha256": SHA}],
        "answer_scaffold": {
            "citation_obligations": ["Cite every strong repository claim."],
            "caveats_to_surface": [caveat],
            "non_claims_to_surface": NON_CLAIMS,
        },
        "forbidden_operations": FORBIDDEN,
        "does_not_establish": NON_CLAIMS,
    }


def test_ask_request_schema_accepts_minimal_frontdoor_request():
    jsonschema.validate(instance=_request(), schema=_schema(REQUEST_SCHEMA))


def test_ask_request_requires_existing_snapshot_only():
    request = _request()
    request["snapshot_policy"]["mode"] = "refresh_if_missing"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=request, schema=_schema(REQUEST_SCHEMA))


def test_ask_request_requires_no_mutation_boundary():
    request = _request()
    request["forbidden_operations"] = ["git_mutation"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=request, schema=_schema(REQUEST_SCHEMA))


def test_context_pack_schema_accepts_context_and_scaffold():
    jsonschema.validate(instance=_context_pack(), schema=_schema(CONTEXT_SCHEMA))


def test_context_pack_requires_resolved_ranges_and_hits():
    pack = _context_pack()
    del pack["resolved_ranges"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=pack, schema=_schema(CONTEXT_SCHEMA))


def test_context_pack_surfaces_caveats_and_non_claims():
    pack = _context_pack()
    jsonschema.validate(instance=pack, schema=_schema(CONTEXT_SCHEMA))
    assert pack["answer_scaffold"]["caveats_to_surface"]
    assert "actual_reading_proven" in pack["answer_scaffold"]["non_claims_to_surface"]
    assert "answer_correct" in pack["does_not_establish"]


def test_contract_document_states_no_refresh_or_reading_proof():
    text = Path("docs/contracts/repobrief-ask-frontdoor-v1.md").read_text(encoding="utf-8")
    assert "forbids implicit refresh" in text
    assert "not a proof" in text
