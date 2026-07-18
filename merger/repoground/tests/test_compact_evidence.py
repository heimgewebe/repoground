import json

from merger.repoground.core.compact_evidence import project_compact_evidence


def _result(address):
    return {
        "query": "find_widget",
        "status": "available",
        "resolved_evidence": {
            "hits": [{
                "citation_id": "cit_0123456789abcdef",
                "range_status": "resolved",
                "citation_status": "resolved",
                "live_repo_address": address,
                "text_excerpt": "x" * 10_000,
                "range": {"text": "y" * 10_000},
            }]
        },
    }


def test_compact_evidence_emits_exact_live_path_line_and_reduces_bytes():
    raw = _result({
        "status": "available", "reason": "snapshot_git_provenance_present",
        "path": "src/widget.py", "start_line": 12, "end_line": 15,
    })
    compact = project_compact_evidence(raw)

    hit = compact["hits"][0]
    assert hit["rank"] == 1
    assert hit["live_path_line"] == "src/widget.py:12-15"
    assert hit["citation_id"] == "cit_0123456789abcdef"
    assert hit["range_status"] == "resolved"
    assert hit["citation_status"] == "resolved"
    assert compact["byte_reduction_percent"] >= 60
    assert compact["compaction_pass"] is True
    assert len(json.dumps(compact)) <= len(json.dumps(raw)) * 0.4


def test_compact_evidence_never_invents_a_live_address():
    compact = project_compact_evidence(_result({
        "status": "unavailable", "reason": "snapshot_provenance_missing",
    }))

    hit = compact["hits"][0]
    assert hit["live_path_line"] is None
    assert hit["non_resolution_reason"] == "live_address_snapshot_provenance_missing"


def test_compact_evidence_marks_an_under_60_percent_projection_as_failed():
    compact = project_compact_evidence({
        "query": "x", "status": "available", "resolved_evidence": {"hits": []},
    })

    assert compact["compaction_requirement_percent"] == 60.0
    assert compact["compaction_pass"] is False


def test_evidence_query_is_registered_as_a_canonical_command():
    from merger.repoground.cli.main import main

    # Parsing reaches the command handler (rather than silently accepting an
    # unknown compatibility alias); the missing manifest then gives its normal
    # read-only failure exit status.
    assert main(["evidence-query", "--bundle-manifest", "/missing.json", "--q", "widget"]) == 1
