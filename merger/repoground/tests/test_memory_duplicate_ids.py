import copy

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
            "source_range": _range(),
        }],
    )


def test_build_rejects_duplicate_citation_ids():
    with pytest.raises(ValueError, match="duplicate citation_id"):
        memory.build_memory_record(
            claim_text="Duplicate evidence must fail closed.",
            snapshot_stem="demo-260709-1700",
            snapshot_hash="b" * 64,
            freshness_status="fresh",
            citations=[
                {
                    "citation_id": "cit_0000000000000001",
                    "source_range": _range(),
                },
                {
                    "citation_id": "cit_0000000000000001",
                    "source_range": _range("c" * 64),
                },
            ],
        )


def test_recall_blocks_duplicate_current_citation_ids():
    record = _memory_record()
    result = memory.check_memory_recall(
        record,
        current_snapshot_hash="b" * 64,
        current_freshness_status="fresh",
        current_citations=[
            {
                "citation_id": "cit_0000000000000001",
                "source_range": _range(),
            },
            {
                "citation_id": "cit_0000000000000001",
                "source_range": _range("c" * 64),
            },
        ],
    )

    assert result["status"] == "unusable"
    assert result["citation_checks"][0]["status"] == "conflict"
    assert {issue["code"] for issue in result["issues"]} == {"citation_id_conflict"}


def test_recall_blocks_duplicate_ids_inside_record():
    record = _memory_record()
    duplicate = copy.deepcopy(record["evidence"]["citations"][0])
    duplicate["source_range"]["content_sha256"] = "c" * 64
    duplicate["range_content_sha256"] = "c" * 64
    record["evidence"]["citations"].append(duplicate)

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
    assert all(check["status"] == "conflict" for check in result["citation_checks"])
    assert {issue["code"] for issue in result["issues"]} == {
        "recorded_citation_id_conflict"
    }


def test_mapping_key_inner_id_conflict_still_fails_closed():
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
