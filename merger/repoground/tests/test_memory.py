import pytest

from merger.repoground.core import memory


def _range(content_hash="a" * 64):
    return {
        "file_path": "demo.md",
        "start_byte": 0,
        "end_byte": 12,
        "start_line": 1,
        "end_line": 2,
        "content_sha256": content_hash,
    }


def _memory_record():
    return memory.build_memory_record(
        claim_text="RepoBrief source citations must be revalidated before reuse.",
        snapshot_stem="demo-260709-1700",
        snapshot_hash="b" * 64,
        freshness_status="fresh",
        citations=[{
            "citation_id": "cit_0000000000000001",
            "chunk_id": "chunk-1",
            "path": "demo.md",
            "source_range": _range(),
        }],
    )


def test_memory_record_shape_binds_claim_citations_snapshot_and_freshness():
    record = _memory_record()

    assert record["kind"] == "repobrief.agent_memory_claim"
    assert record["status"] == "recorded_requires_recall_check"
    assert record["claim_text"].startswith("RepoBrief source citations")
    assert record["evidence"]["snapshot"] == {
        "stem": "demo-260709-1700",
        "hash": "b" * 64,
        "freshness_status": "fresh",
    }
    citation = record["evidence"]["citations"][0]
    assert citation["citation_id"] == "cit_0000000000000001"
    assert citation["source_range"]["file_path"] == "demo.md"
    assert citation["source_range"]["start_byte"] == 0
    assert citation["source_range"]["end_byte"] == 12
    assert citation["range_content_sha256"] == "a" * 64
    assert record["recall_policy"]["requires_revalidation"] is True
    assert "truth" in record["does_not_establish"]


def test_recall_check_allows_use_only_when_snapshot_freshness_and_citation_match():
    record = _memory_record()

    result = memory.check_memory_recall(
        record,
        current_snapshot_hash="b" * 64,
        current_freshness_status="fresh",
        current_citations=[{
            "citation_id": "cit_0000000000000001",
            "source_range": _range(),
        }],
    )

    assert result["status"] == "usable"
    assert result["usable_as_source_backed_memory"] is True
    assert result["presentation_policy"] == "may_present_with_verified_citations"
    assert result["memory_is_source_truth"] is False
    assert result["citation_checks"][0]["status"] == "verified"
    assert result["issue_count"] == 0


def test_recall_check_blocks_changed_citation_hash():
    record = _memory_record()

    result = memory.check_memory_recall(
        record,
        current_snapshot_hash="b" * 64,
        current_freshness_status="fresh",
        current_citations=[{
            "citation_id": "cit_0000000000000001",
            "source_range": _range("c" * 64),
        }],
    )

    assert result["status"] == "unusable"
    assert result["usable_as_source_backed_memory"] is False
    assert result["presentation_policy"] == "do_not_present_as_source_truth"
    assert result["citation_checks"][0]["status"] == "changed"
    assert result["issues"][0]["code"] == "citation_hash_changed"


def test_recall_check_blocks_missing_citation_and_missing_current_freshness():
    record = _memory_record()

    result = memory.check_memory_recall(
        record,
        current_snapshot_hash="b" * 64,
        current_freshness_status=None,
        current_citations=[],
    )

    codes = {issue["code"] for issue in result["issues"]}
    assert result["status"] == "unusable"
    assert "freshness_status_missing" in codes
    assert "citation_missing" in codes
    assert result["freshness_check"]["status"] == "stale_or_unverified"
    assert result["presentation_policy"] == "do_not_present_as_source_truth"


def test_recall_check_blocks_changed_snapshot_hash():
    record = _memory_record()

    result = memory.check_memory_recall(
        record,
        current_snapshot_hash="d" * 64,
        current_freshness_status="fresh",
        current_citations=[{
            "citation_id": "cit_0000000000000001",
            "source_range": _range(),
        }],
    )

    assert result["status"] == "unusable"
    assert result["snapshot_check"]["status"] == "changed"
    assert {issue["code"] for issue in result["issues"]} == {"snapshot_hash_changed"}


def test_memory_record_from_projection_preserves_resolved_citation_identity():
    projection = {
        "items": [
            {
                "citation_resolved": True,
                "citation_id": "cit_0000000000000001",
                "chunk_id": "chunk-1",
                "path": "demo.md",
                "repo_id": "demo-repo",
                "source_range": _range(),
                "citation_range": _range(),
            },
        ]
    }

    record = memory.memory_record_from_projection(
        claim_text="Projection-backed memory claim.",
        source_citation_projection=projection,
        snapshot_stem="demo-260709-1700",
        snapshot_hash="b" * 64,
        freshness_status="fresh",
    )

    citation = record["evidence"]["citations"][0]
    assert citation["citation_id"] == "cit_0000000000000001"
    assert citation["repo_id"] == "demo-repo"


def test_memory_record_from_projection_blocks_unresolved_citations():
    projection = {
        "items": [
            {
                "citation_resolved": True,
                "citation_id": "cit_0000000000000001",
                "source_range": _range(),
            },
            {
                "citation_resolved": False,
                "citation_id": "cit_0000000000000002",
                "source_range": _range(),
            },
        ]
    }

    with pytest.raises(ValueError, match="unresolved citations"):
        memory.memory_record_from_projection(
            claim_text="Projection-backed memory claim.",
            source_citation_projection=projection,
            snapshot_stem="demo-260709-1700",
            snapshot_hash="b" * 64,
            freshness_status="fresh",
        )


def test_memory_record_accepts_artifact_axis_when_byte_aliases_are_none():
    record = memory.build_memory_record(
        claim_text="Artifact-axis memory claim.",
        snapshot_stem="demo-260709-1700",
        snapshot_hash="b" * 64,
        freshness_status="fresh",
        citations=[{
            "citation_id": "cit_0000000000000001",
            "source_range": {
                "file_path": "merged.md",
                "start_byte": None,
                "end_byte": None,
                "artifact_start_byte": 0,
                "artifact_end_byte": 5,
                "artifact_start_line": 1,
                "artifact_end_line": 1,
                "content_sha256": "a" * 64,
            },
        }],
    )

    source_range = record["evidence"]["citations"][0]["source_range"]
    assert source_range["start_byte"] == 0
    assert source_range["end_byte"] == 5
    assert source_range["start_line"] == 1
    assert source_range["end_line"] == 1


def test_recall_check_blocks_same_hash_different_file_path():
    record = _memory_record()
    current_range = _range()
    current_range["file_path"] = "other.md"

    result = memory.check_memory_recall(
        record,
        current_snapshot_hash="b" * 64,
        current_freshness_status="fresh",
        current_citations=[{
            "citation_id": "cit_0000000000000001",
            "source_range": current_range,
        }],
    )

    assert result["status"] == "unusable"
    assert result["citation_checks"][0]["status"] == "changed"
    assert {issue["code"] for issue in result["issues"]} == {"citation_range_identity_changed"}


def test_recall_check_blocks_same_hash_different_byte_range():
    record = _memory_record()
    current_range = _range()
    current_range["end_byte"] = 13

    result = memory.check_memory_recall(
        record,
        current_snapshot_hash="b" * 64,
        current_freshness_status="fresh",
        current_citations=[{
            "citation_id": "cit_0000000000000001",
            "source_range": current_range,
        }],
    )

    assert result["status"] == "unusable"
    assert result["citation_checks"][0]["status"] == "changed"
    assert {issue["code"] for issue in result["issues"]} == {"citation_range_identity_changed"}


def test_recall_check_blocks_mapping_key_and_inner_citation_id_conflict():
    record = _memory_record()

    result = memory.check_memory_recall(
        record,
        current_snapshot_hash="b" * 64,
        current_freshness_status="fresh",
        current_citations={
            "cit_0000000000000001": {
                "citation_id": "cit_0000000000000002",
                "source_range": _range(),
            }
        },
    )

    assert result["status"] == "unusable"
    assert result["citation_checks"][0]["status"] == "conflict"
    assert {issue["code"] for issue in result["issues"]} == {"citation_id_conflict"}


def test_recall_check_blocks_same_hash_different_repo_id():
    record = memory.build_memory_record(
        claim_text="Repo-scoped memory claim.",
        snapshot_stem="demo-260709-1700",
        snapshot_hash="b" * 64,
        freshness_status="fresh",
        citations=[{
            "citation_id": "cit_0000000000000001",
            "source_range": {**_range(), "repo_id": "repo-a"},
        }],
    )

    result = memory.check_memory_recall(
        record,
        current_snapshot_hash="b" * 64,
        current_freshness_status="fresh",
        current_citations=[{
            "citation_id": "cit_0000000000000001",
            "source_range": {**_range(), "repo_id": "repo-b"},
        }],
    )

    assert result["status"] == "unusable"
    assert result["citation_checks"][0]["status"] == "changed"
    assert {issue["code"] for issue in result["issues"]} == {"citation_range_identity_changed"}


def test_recall_check_accepts_matching_projection_top_level_repo_id():
    record = memory.memory_record_from_projection(
        claim_text="Projection-backed repo memory claim.",
        source_citation_projection={
            "items": [{
                "citation_resolved": True,
                "citation_id": "cit_0000000000000001",
                "repo_id": "repo-a",
                "source_range": _range(),
            }]
        },
        snapshot_stem="demo-260709-1700",
        snapshot_hash="b" * 64,
        freshness_status="fresh",
    )

    result = memory.check_memory_recall(
        record,
        current_snapshot_hash="b" * 64,
        current_freshness_status="fresh",
        current_citations=[{
            "citation_id": "cit_0000000000000001",
            "repo_id": "repo-a",
            "source_range": _range(),
        }],
    )

    assert result["status"] == "usable"
    assert result["citation_checks"][0]["status"] == "verified"


def test_recall_check_blocks_projection_top_level_repo_id_mismatch():
    record = memory.memory_record_from_projection(
        claim_text="Projection-backed repo memory claim.",
        source_citation_projection={
            "items": [{
                "citation_resolved": True,
                "citation_id": "cit_0000000000000001",
                "repo_id": "repo-a",
                "source_range": _range(),
            }]
        },
        snapshot_stem="demo-260709-1700",
        snapshot_hash="b" * 64,
        freshness_status="fresh",
    )

    result = memory.check_memory_recall(
        record,
        current_snapshot_hash="b" * 64,
        current_freshness_status="fresh",
        current_citations=[{
            "citation_id": "cit_0000000000000001",
            "repo_id": "repo-b",
            "source_range": _range(),
        }],
    )

    assert result["status"] == "unusable"
    assert result["citation_checks"][0]["status"] == "changed"
    assert {issue["code"] for issue in result["issues"]} == {"citation_range_identity_changed"}


def test_recall_check_blocks_missing_recorded_source_range_without_crashing():
    record = _memory_record()
    citation = record["evidence"]["citations"][0]
    del citation["source_range"]

    result = memory.check_memory_recall(
        record,
        current_snapshot_hash="b" * 64,
        current_freshness_status="fresh",
        current_citations=[{
            "citation_id": "cit_0000000000000001",
            "source_range": _range(),
        }],
    )

    assert result["status"] == "unusable"
    assert result["citation_checks"][0]["status"] == "invalid_record"
    assert {issue["code"] for issue in result["issues"]} == {"citation_range_identity_missing"}


def test_recall_check_blocks_invalid_memory_kind_version_and_claim_text():
    record = _memory_record()
    record["kind"] = "wrong.kind"
    record["version"] = "v0"
    record["claim_text"] = ""

    result = memory.check_memory_recall(
        record,
        current_snapshot_hash="b" * 64,
        current_freshness_status="fresh",
        current_citations=[{
            "citation_id": "cit_0000000000000001",
            "source_range": _range(),
        }],
    )

    assert result["status"] == "unusable"
    assert {
        "memory_record_kind_invalid",
        "memory_record_version_invalid",
        "claim_text_invalid",
    }.issubset({issue["code"] for issue in result["issues"]})


def test_memory_record_recall_policy_lists_identity_and_conflict_requirements():
    record = _memory_record()

    assert "all_recorded_citation_range_identities_match" in record["recall_policy"]["usable_only_when"]
    assert "no_citation_id_conflicts" in record["recall_policy"]["usable_only_when"]
    assert "memory_record_kind_and_version_are_valid" in record["recall_policy"]["usable_only_when"]


def test_projection_helper_rejects_unresolved_item_directly():
    with pytest.raises(ValueError, match="not resolved"):
        memory.citation_from_projection_item({
            "citation_resolved": False,
            "citation_id": "cit_0000000000000001",
            "source_range": _range(),
        })


def test_memory_record_rejects_bare_sha256_without_range_hash_basis():
    with pytest.raises(ValueError, match="citation must include a range"):
        memory.build_memory_record(
            claim_text="Ambiguous hash claim.",
            snapshot_stem="demo-260709-1700",
            snapshot_hash="b" * 64,
            freshness_status="fresh",
            citations=[{
                "citation_id": "cit_0000000000000001",
                "source_range": {
                    "file_path": "demo.md",
                    "start_byte": 0,
                    "end_byte": 12,
                    "sha256": "a" * 64,
                },
            }],
        )


def test_memory_record_accepts_bare_sha256_with_range_hash_basis():
    record = memory.build_memory_record(
        claim_text="Explicit hash basis claim.",
        snapshot_stem="demo-260709-1700",
        snapshot_hash="b" * 64,
        freshness_status="fresh",
        citations=[{
            "citation_id": "cit_0000000000000001",
            "source_range": {
                "file_path": "demo.md",
                "start_byte": 0,
                "end_byte": 12,
                "sha256": "a" * 64,
                "hash_basis": "range_content",
            },
        }],
    )

    assert record["evidence"]["citations"][0]["range_content_sha256"] == "a" * 64
