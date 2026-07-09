import hashlib
import json
from pathlib import Path

import jsonschema

from merger.lenskit.core.answer_grounding import NON_CLAIMS, verify_answer_grounding

SHA = "a" * 64


def _bundle(tmp_path: Path, content: bytes = b"Line 1\nLine 2\nLine 3\n"):
    canonical = tmp_path / "demo_merge.md"
    canonical.write_bytes(content)
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "run_id": "demo-run",
                "artifacts": [{"role": "canonical_md", "path": canonical.name}],
            }
        ),
        encoding="utf-8",
    )
    start, end = 7, 14
    range_hash = hashlib.sha256(content[start:end]).hexdigest()
    full_hash = hashlib.sha256(content).hexdigest()
    citation_map = tmp_path / "demo.citation_map.jsonl"
    citation_map.write_text(
        json.dumps(
            {
                "citation_id": "cit_0000000000000001",
                "repo_id": "demo",
                "snapshot": {
                    "run_id": "demo-run",
                    "canonical_md_path": canonical.name,
                    "canonical_md_sha256": full_hash,
                },
                "canonical_range": {
                    "file_path": canonical.name,
                    "start_byte": start,
                    "end_byte": end,
                    "start_line": 2,
                    "end_line": 2,
                    "content_sha256": range_hash,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    range_ref = {
        "artifact_role": "canonical_md",
        "repo_id": "demo",
        "file_path": canonical.name,
        "start_byte": start,
        "end_byte": end,
        "start_line": 2,
        "end_line": 2,
        "content_sha256": range_hash,
    }
    return manifest, citation_map, range_ref


def _declaration(range_ref=None, citation_id="cit_0000000000000001", non_claims=None):
    return {
        "kind": "repobrief.answer_grounding_declaration",
        "version": "1.0",
        "answer_id": "answer-1",
        "snapshot_ref": {
            "stem": "demo",
            "manifest_path": "demo.bundle.manifest.json",
            "manifest_sha256": SHA,
            "freshness_status": "fresh",
        },
        "task_profile": "basic_repo_question",
        "question_hash": SHA,
        "answer_hash": "b" * 64,
        "used_citations": [{"citation_id": citation_id, "purpose": "ground claim"}],
        "used_ranges": [
            {
                "artifact_role": "canonical_md",
                "range_ref": range_ref,
                "purpose": "check span",
            }
        ] if range_ref else [],
        "declared_non_claims": non_claims or NON_CLAIMS,
        "freshness_caveats": [],
        "does_not_establish": non_claims or NON_CLAIMS,
    }


def _validate_verdict(verdict):
    schema = json.loads(
        (Path(__file__).parent.parent / "contracts" / "answer-grounding-verdict.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(instance=verdict, schema=schema)


def test_verify_answer_grounding_pass_resolves_citation_and_range(tmp_path):
    manifest, citation_map, range_ref = _bundle(tmp_path)

    verdict = verify_answer_grounding(
        _declaration(range_ref),
        bundle_manifest=manifest,
        citation_map=citation_map,
        required_artifacts=["citation_map_jsonl", "canonical_md"],
    )

    _validate_verdict(verdict)
    assert verdict["status"] == "pass"
    assert {check["status"] for check in verdict["citation_checks"]} == {"resolved"}
    assert verdict["range_checks"][0]["status"] == "resolved"
    assert verdict["does_not_establish"] == NON_CLAIMS


def test_verify_answer_grounding_fails_missing_citation(tmp_path):
    manifest, citation_map, range_ref = _bundle(tmp_path)

    verdict = verify_answer_grounding(
        _declaration(range_ref, citation_id="cit_ffffffffffffffff"),
        bundle_manifest=manifest,
        citation_map=citation_map,
    )

    _validate_verdict(verdict)
    assert verdict["status"] == "fail"
    assert any(d["code"] == "citation_not_found" for d in verdict["diagnostics"])


def test_verify_answer_grounding_fails_hash_drift(tmp_path):
    manifest, citation_map, range_ref = _bundle(tmp_path)
    range_ref = dict(range_ref)
    range_ref["content_sha256"] = "e" * 64

    verdict = verify_answer_grounding(
        _declaration(range_ref),
        bundle_manifest=manifest,
        citation_map=citation_map,
    )

    _validate_verdict(verdict)
    assert verdict["status"] == "fail"
    assert verdict["range_checks"][0]["status"] == "drifted"
    assert any(d["code"] == "content_hash_mismatch" for d in verdict["diagnostics"])


def test_verify_answer_grounding_degraded_for_invalid_citation_map_jsonl(tmp_path):
    manifest, citation_map, range_ref = _bundle(tmp_path)
    citation_map.write_text("{not-json}\n", encoding="utf-8")

    declaration = _declaration(range_ref)
    declaration["used_citations"] = []
    verdict = verify_answer_grounding(
        declaration,
        bundle_manifest=manifest,
        citation_map=citation_map,
    )

    _validate_verdict(verdict)
    assert verdict["status"] == "degraded"
    assert any(d["code"] == "degraded_dependency" for d in verdict["diagnostics"])


def test_verify_answer_grounding_fails_missing_required_non_claim(tmp_path):
    manifest, citation_map, range_ref = _bundle(tmp_path)

    verdict = verify_answer_grounding(
        _declaration(range_ref, non_claims=NON_CLAIMS[:-1]),
        bundle_manifest=manifest,
        citation_map=citation_map,
    )

    _validate_verdict(verdict)
    assert verdict["status"] == "fail"
    assert any(d["code"] == "missing_non_claim" for d in verdict["diagnostics"])


def test_verify_answer_grounding_warns_missing_recommended_artifact(tmp_path):
    manifest, citation_map, range_ref = _bundle(tmp_path)

    verdict = verify_answer_grounding(
        _declaration(range_ref),
        bundle_manifest=manifest,
        citation_map=citation_map,
        recommended_artifacts=["bundle_surface_validation"],
    )

    _validate_verdict(verdict)
    assert verdict["status"] == "warn"
    assert any(d["code"] == "missing_recommended_artifact" for d in verdict["diagnostics"])


def test_verify_answer_grounding_not_applicable_without_evidence(tmp_path):
    manifest, citation_map, _range_ref = _bundle(tmp_path)
    declaration = _declaration(range_ref=None)
    declaration["used_citations"] = []

    verdict = verify_answer_grounding(declaration, bundle_manifest=manifest, citation_map=citation_map)

    _validate_verdict(verdict)
    assert verdict["status"] == "not_applicable"
    assert any(d["code"] == "not_applicable" for d in verdict["diagnostics"])
