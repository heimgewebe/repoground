from merger.lenskit.retrieval.output_projection import project_output


CKEY = "citation_id_candidates"
SKEY = "citation_candidates"
IDKEY = "citation_id"


def _result_with_candidates():
    return {
        "context_bundle": {
            "query": "range refs",
            "hits": [
                {
                    "hit_identity": "chunk-a",
                    "file": "merge.md",
                    "path": "merge.md",
                    "range": "1-2",
                    "score": 1.0,
                    "explain": {"debug": True},
                    "graph_context": {"graph_used": False},
                    "resolved_code_snippet": "text",
                    "provenance_type": "explicit",
                    "bundle_source_references": ["merge.md"],
                    "epistemics": {"resolver_status": "resolved_explicit"},
                }
            ],
        },
        "range_coverage": {
            "per_hit": [
                {
                    "chunk_id": "chunk-a",
                    "path": "merge.md",
                    "range": "1-2",
                    "status": "canonical_explicit",
                    "range_ref_kind": "range_ref",
                    CKEY: [
                        {IDKEY: "c-1", "match_reasons": ["chunk_id"]}
                    ],
                }
            ],
            "diagnostic_semantics": {
                "does_not_establish": ["truth", "answer_correctness"]
            },
        },
    }


def test_agent_minimal_wraps_candidate_surface_outside_context_bundle():
    projected = project_output(_result_with_candidates(), "agent_minimal")

    assert set(projected) == {"context_bundle", SKEY}
    hit = projected["context_bundle"]["hits"][0]
    assert "explain" not in hit
    assert "graph_context" not in hit
    assert CKEY not in hit

    surface = projected[SKEY]
    assert surface["source"] == "range_coverage"
    assert surface["hits"] == [
        {
            "chunk_id": "chunk-a",
            "path": "merge.md",
            "range": "1-2",
            "range_status": "canonical_explicit",
            "range_ref_kind": "range_ref",
            CKEY: [
                {IDKEY: "c-1", "match_reasons": ["chunk_id"]}
            ],
        }
    ]
    assert "truth" in surface["does_not_establish"]


def test_no_candidate_surface_preserves_bare_bundle_when_no_wrapper_needed():
    result = _result_with_candidates()
    result["range_coverage"]["per_hit"][0].pop(CKEY)

    projected = project_output(result, "agent_minimal")

    assert "hits" in projected
    assert "context_bundle" not in projected
    assert SKEY not in projected
