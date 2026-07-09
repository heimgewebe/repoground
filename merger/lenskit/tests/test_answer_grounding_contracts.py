import json
from pathlib import Path

import pytest

try:
    import jsonschema
    from jsonschema import Draft7Validator, ValidationError
except ImportError:
    jsonschema = None
    Draft7Validator = None
    ValidationError = None

CONTRACT_DIR = Path(__file__).parent.parent / "contracts"
DECLARATION_SCHEMA = CONTRACT_DIR / "answer-grounding-declaration.v1.schema.json"
VERDICT_SCHEMA = CONTRACT_DIR / "answer-grounding-verdict.v1.schema.json"
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
SHA = "a" * 64


def _require_jsonschema():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")


def _load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _snapshot_ref() -> dict:
    return {
        "stem": "demo_merge",
        "manifest_path": "demo_merge.bundle.manifest.json",
        "manifest_sha256": SHA,
        "git_commit": "0123456789abcdef",
        "freshness_status": "fresh",
    }


def _declaration() -> dict:
    return {
        "kind": "repobrief.answer_grounding_declaration",
        "version": "1.0",
        "answer_id": "answer-1",
        "snapshot_ref": _snapshot_ref(),
        "task_profile": "basic_repo_question",
        "question_hash": SHA,
        "answer_hash": "b" * 64,
        "used_citations": [
            {"citation_id": "c-demo-1", "purpose": "ground the API boundary claim"}
        ],
        "used_ranges": [
            {
                "artifact_role": "canonical_md",
                "range_ref": {
                    "file_path": "demo_merge.md",
                    "start_line": 10,
                    "end_line": 14,
                },
                "range_content_sha256": "c" * 64,
                "purpose": "check the cited canonical span",
            }
        ],
        "strong_claims": [
            {
                "claim_ref": "claim-1",
                "summary": "The adapter is read-only.",
                "expected_evidence": ["c-demo-1"],
            }
        ],
        "declared_non_claims": NON_CLAIMS,
        "freshness_caveats": [],
        "does_not_establish": NON_CLAIMS,
    }


def _verdict(status: str = "pass") -> dict:
    return {
        "kind": "repobrief.answer_grounding_verdict",
        "version": "1.0",
        "status": status,
        "checked_declaration": {
            "answer_id": "answer-1",
            "question_hash": SHA,
            "answer_hash": "b" * 64,
            "declaration_sha256": "d" * 64,
        },
        "snapshot_ref": _snapshot_ref(),
        "citation_checks": [
            {
                "ref": "c-demo-1",
                "status": "resolved",
                "severity": "info",
                "artifact_role": "citation_map_jsonl",
                "authority": "canonical_snapshot",
                "detail": "Citation ID resolved against the selected snapshot.",
            }
        ],
        "range_checks": [
            {
                "ref": "range-1",
                "status": "resolved",
                "severity": "info",
                "artifact_role": "canonical_md",
                "authority": "canonical_snapshot",
                "detail": "Range resolved against canonical Markdown.",
            }
        ],
        "required_reading_checks": [
            {
                "artifact_role": "canonical_md",
                "status": "declared",
                "severity": "info",
                "detail": "Required canonical source was declared.",
            }
        ],
        "diagnostics": [],
        "freshness_caveats": [],
        "availability_caveats": [],
        "does_not_establish": NON_CLAIMS,
    }


def _validate(instance: dict, schema_path: Path) -> None:
    _require_jsonschema()
    schema = _load_schema(schema_path)
    Draft7Validator.check_schema(schema)
    jsonschema.validate(instance=instance, schema=schema)


def test_declaration_schema_accepts_minimal_grounding_declaration():
    _validate(_declaration(), DECLARATION_SCHEMA)


def test_declaration_requires_non_claims():
    _require_jsonschema()
    instance = _declaration()
    instance["does_not_establish"] = NON_CLAIMS[:-1]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=_load_schema(DECLARATION_SCHEMA))


def test_declaration_rejects_additional_properties():
    _require_jsonschema()
    instance = _declaration()
    instance["semantic_truth"] = "yes"
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=_load_schema(DECLARATION_SCHEMA))


def test_declaration_used_ranges_accept_range_ref_v2_shape():
    instance = _declaration()
    instance["used_ranges"] = [
        {
            "artifact_role": "canonical_md",
            "range_ref": {
                "artifact_path": "demo_merge.md",
                "artifact_line_start": 10,
                "artifact_line_end": 14,
                "source_file_path": "README.md",
                "source_line_start": 1,
                "source_line_end": 5,
            },
            "purpose": "check source-backed range",
        }
    ]
    _validate(instance, DECLARATION_SCHEMA)


@pytest.mark.parametrize("status", ["pass", "warn", "fail", "degraded", "not_applicable"])
def test_verdict_schema_accepts_all_v1_status_examples(status):
    instance = _verdict(status=status)
    if status == "warn":
        instance["diagnostics"] = [
            {
                "code": "missing_recommended_artifact",
                "severity": "warn",
                "detail": "Recommended surface was not available.",
            }
        ]
    elif status == "fail":
        instance["citation_checks"][0]["status"] = "missing"
        instance["citation_checks"][0]["severity"] = "fail"
        instance["diagnostics"] = [
            {
                "code": "citation_not_found",
                "severity": "fail",
                "detail": "Required citation ID was not found.",
                "ref": "c-demo-1",
            }
        ]
    elif status == "degraded":
        instance["diagnostics"] = [
            {
                "code": "degraded_dependency",
                "severity": "warn",
                "detail": "Citation map loader was unavailable.",
            }
        ]
    elif status == "not_applicable":
        instance["diagnostics"] = [
            {
                "code": "not_applicable",
                "severity": "info",
                "detail": "Task profile does not require grounding verification.",
            }
        ]
    _validate(instance, VERDICT_SCHEMA)


@pytest.mark.parametrize("bad_status", ["supported", "unsupported", "true", "false"])
def test_verdict_rejects_truth_or_claim_support_statuses(bad_status):
    _require_jsonschema()
    instance = _verdict(status=bad_status)
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=_load_schema(VERDICT_SCHEMA))


def test_verdict_pass_does_not_establish_truth_or_merge_readiness():
    schema = _load_schema(VERDICT_SCHEMA)
    dne = schema["definitions"]["does_not_establish_array"]
    allowed = set(dne["items"]["enum"])
    assert {"answer_correct", "claims_true", "merge_readiness", "security_correctness"} <= allowed
    assert "supported" not in json.dumps(schema)
    assert "unsupported" not in json.dumps(schema)


def test_verdict_rejects_missing_required_diagnostic_detail():
    _require_jsonschema()
    instance = _verdict(status="fail")
    instance["diagnostics"] = [{"code": "citation_not_found", "severity": "fail"}]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=_load_schema(VERDICT_SCHEMA))


def test_contract_document_names_all_example_outcomes():
    text = Path("docs/contracts/answer-grounding-v1.md").read_text(encoding="utf-8")
    for heading in ["### Pass", "### Warn", "### Fail", "### Degraded"]:
        assert heading in text
    assert "not a truth detector" in text
