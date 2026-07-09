import json
from pathlib import Path

from merger.lenskit.core.answer_grounding_delta import check_answer_grounding_delta
from merger.lenskit.tests.test_answer_grounding_verifier import _bundle, _declaration


def _empty_citation_map(path: Path) -> Path:
    path.write_text("", encoding="utf-8")
    return path


def _citation_without_range(path: Path) -> Path:
    path.write_text(json.dumps({"citation_id": "cit_0000000000000001", "repo_id": "demo"}) + "\n", encoding="utf-8")
    return path


def test_answer_grounding_delta_valid_unchanged(tmp_path):
    manifest, citation_map, range_ref = _bundle(tmp_path)
    declaration = _declaration(range_ref)

    verdict = check_answer_grounding_delta(
        declaration,
        new_bundle_manifest=manifest,
        new_citation_map=citation_map,
    )

    assert verdict["status"] == "valid"
    assert verdict["citation_checks"][0]["status"] == "valid"
    assert verdict["range_checks"][0]["status"] == "valid"
    assert verdict["mutation_boundary"]["does_not_create_snapshots"] is True
    assert verdict["mutation_boundary"]["does_not_fetch_git"] is True


def test_answer_grounding_delta_drifted_hash_mismatch(tmp_path):
    manifest, citation_map, range_ref = _bundle(tmp_path)
    declaration = _declaration(range_ref)
    (tmp_path / "demo_merge.md").write_text("Line 1\nchanged\nLine 3\n", encoding="utf-8")

    verdict = check_answer_grounding_delta(
        declaration,
        new_bundle_manifest=manifest,
        new_citation_map=citation_map,
    )

    assert verdict["status"] == "drifted"
    assert any(item["status"] == "drifted" for item in verdict["citation_checks"] + verdict["range_checks"])


def test_answer_grounding_delta_missing_citation(tmp_path):
    manifest, _citation_map, range_ref = _bundle(tmp_path)
    declaration = _declaration(range_ref)
    empty = _empty_citation_map(tmp_path / "empty.citation_map.jsonl")

    verdict = check_answer_grounding_delta(
        declaration,
        new_bundle_manifest=manifest,
        new_citation_map=empty,
    )

    assert verdict["status"] == "missing"
    assert verdict["citation_checks"][0]["status"] == "missing"


def test_answer_grounding_delta_not_comparable_when_range_absent(tmp_path):
    manifest, _citation_map, range_ref = _bundle(tmp_path)
    declaration = _declaration(range_ref)
    declaration["used_ranges"] = []
    no_range = _citation_without_range(tmp_path / "no-range.citation_map.jsonl")

    verdict = check_answer_grounding_delta(
        declaration,
        new_bundle_manifest=manifest,
        new_citation_map=no_range,
    )

    assert verdict["status"] == "not_comparable"
    assert verdict["citation_checks"][0]["status"] == "not_comparable"


def test_answer_grounding_delta_preserves_existing_freshness_status(tmp_path):
    manifest, citation_map, range_ref = _bundle(tmp_path)
    declaration = _declaration(range_ref)
    declaration["snapshot_ref"]["freshness_status"] = "stale"

    verdict = check_answer_grounding_delta(
        declaration,
        new_bundle_manifest=manifest,
        new_citation_map=citation_map,
    )

    assert verdict["old_snapshot_freshness_status"] == "stale"
    assert verdict["new_snapshot_freshness_status"] == "unknown"
