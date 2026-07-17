from merger.repoground.retrieval.output_projection import project_output

def test_agent_profile_lookup_minimal():
    # Mock result mimicking what execute_query returns
    mock_result = {
        "context_bundle": {
            "hits": [
                {
                    "id": "1",
                    "explain": {"bm25": 1.0},
                    "graph_context": {"distance": 1},
                    "surrounding_context": "def foo():\n    pass\n"
                },
                {
                    "id": "2",
                    "explain": {"bm25": 0.5},
                    "graph_context": {"distance": 2},
                    "surrounding_context": None
                }
            ]
        },
        "query_trace": {"status": "ok"} # Adding query_trace to verify the wrapper contract
    }

    projected = project_output(mock_result, output_profile="lookup_minimal")

    # Contract says if query_trace is present, it returns {"context_bundle": ..., "query_trace": ...}
    assert "context_bundle" in projected
    assert "query_trace" in projected

    hits = projected["context_bundle"].get("hits", [])
    assert len(hits) == 2

    # lookup_minimal should strip explain, graph_context, and surrounding_context
    for hit in hits:
        assert "explain" not in hit
        assert "graph_context" not in hit
        assert "surrounding_context" not in hit

def test_agent_profile_review_context():
    mock_result = {
        "context_bundle": {
            "hits": [
                {
                    "id": "1",
                    "explain": {"bm25": 1.0},
                    "graph_context": {"distance": 1},
                    "surrounding_context": "def foo():\n    pass\n"
                },
                {
                    "id": "2",
                    "explain": {"bm25": 0.5},
                    "graph_context": {"distance": 2},
                    "surrounding_context": None
                }
            ]
        }
    }

    # Here query_trace is missing, so it should return the bundle directly
    projected = project_output(mock_result, output_profile="review_context")
    hits = projected.get("hits", [])
    assert len(hits) == 2

    # review_context should strip graph_context, but keep explain and surrounding_context (if not None)
    for hit in hits:
        assert "explain" in hit
        assert "graph_context" not in hit

    assert "surrounding_context" in hits[0]
    # For hit 2, surrounding_context was None, so it is stripped
    assert "surrounding_context" not in hits[1]

def test_agent_profile_lookup_minimal_without_trace():
    # Mock result without query_trace
    mock_result = {
        "context_bundle": {
            "hits": [
                {
                    "id": "1",
                    "explain": {"bm25": 1.0},
                    "graph_context": {"distance": 1},
                    "surrounding_context": "def foo():\n    pass\n"
                },
                {
                    "id": "2",
                    "explain": {"bm25": 0.5},
                    "graph_context": {"distance": 2},
                    "surrounding_context": None
                }
            ]
        }
    }

    # Contract says if query_trace is absent, it returns the bundle directly
    projected = project_output(mock_result, output_profile="lookup_minimal")

    hits = projected.get("hits", [])
    assert len(hits) == 2

    # lookup_minimal should strip explain, graph_context, and surrounding_context
    for hit in hits:
        assert "explain" not in hit
        assert "graph_context" not in hit
        assert "surrounding_context" not in hit

def test_agent_profile_review_context_with_trace():
    mock_result = {
        "context_bundle": {
            "hits": [
                {
                    "id": "1",
                    "explain": {"bm25": 1.0},
                    "graph_context": {"distance": 1},
                    "surrounding_context": "def foo():\n    pass\n"
                },
                {
                    "id": "2",
                    "explain": {"bm25": 0.5},
                    "graph_context": {"distance": 2},
                    "surrounding_context": None
                }
            ]
        },
        "query_trace": {"status": "ok"} # Adding query_trace
    }

    # Contract says if query_trace is present, it returns a wrapper
    projected = project_output(mock_result, output_profile="review_context")

    assert "context_bundle" in projected
    assert "query_trace" in projected

    hits = projected["context_bundle"].get("hits", [])
    assert len(hits) == 2

    # review_context should strip graph_context, but keep explain and surrounding_context (if not None)
    for hit in hits:
        assert "explain" in hit
        assert "graph_context" not in hit

    assert "surrounding_context" in hits[0]
    assert "surrounding_context" not in hits[1]

def test_agent_federated_conflict_warning():
    mock_result = {
        "context_bundle": {
            "hits": [
                {
                    "id": "1",
                    "explain": {"bm25": 1.0},
                    "graph_context": {"distance": 1},
                    "surrounding_context": "def foo():\n    pass\n"
                }
            ]
        },
        "federation_conflicts": [
            {
                "conflict_id": "conflict_0",
                "type": "path",
                "description": "Conflict description",
                "resolution": "unresolved",
                "involved_results": ["1"]
            }
        ],
        "warnings": ["Low result coverage"]
    }

    # Contract says if federation_conflicts or warnings are present, it returns a wrapper
    projected = project_output(mock_result, output_profile="agent_minimal")

    assert "context_bundle" in projected
    assert "federation_conflicts" in projected
    assert projected["federation_conflicts"][0]["conflict_id"] == "conflict_0"

    assert "warnings" in projected
    assert len(projected["warnings"]) == 1

    hits = projected["context_bundle"].get("hits", [])
    assert len(hits) == 1

    # agent_minimal should strip explain, graph_context
    for hit in hits:
        assert "explain" not in hit
        assert "graph_context" not in hit

def test_agent_federated_conflict_empty_no_wrapper():
    mock_result = {
        "context_bundle": {
            "hits": [
                {
                    "id": "1"
                }
            ]
        },
        "federation_conflicts": [],
        "warnings": []
    }

    # If lists are empty, they should NOT trigger a wrapper, returning the bundle directly
    projected = project_output(mock_result, output_profile="agent_minimal")

    assert "context_bundle" not in projected
    assert "federation_conflicts" not in projected
    assert "warnings" not in projected
    assert "hits" in projected

def test_agent_federated_conflict_warning_coexistence():
    """
    Ensures that when all diagnostic/guardrail fields are truthy, they all
    coexist safely in the generated wrapper under 'agent_minimal' profile.
    """
    mock_result = {
        "context_bundle": {
            "hits": [
                {
                    "id": "1",
                    "explain": {"bm25": 1.0},
                    "graph_context": {"distance": 1},
                    "surrounding_context": "def foo():\n    pass\n"
                }
            ]
        },
        "query_trace": {
            "status": "traced",
            "latency": 42
        },
        "federation_conflicts": [
            {
                "conflict_id": "conflict_99",
                "type": "path",
                "description": "Conflict coexistence",
                "resolution": "unresolved",
                "involved_results": ["1"]
            }
        ],
        "warnings": ["Cross repo identity collision"]
    }

    projected = project_output(mock_result, output_profile="agent_minimal")

    # Verify that the wrapper is returned and all 3 elements coexist perfectly
    assert "context_bundle" in projected
    assert "query_trace" in projected
    assert "federation_conflicts" in projected
    assert "warnings" in projected

    # Verify context bundle projection still happened correctly
    hits = projected["context_bundle"].get("hits", [])
    assert len(hits) == 1
    for hit in hits:
        assert "explain" not in hit
        assert "graph_context" not in hit


def test_agent_profile_preserves_cross_repo_links_in_wrapper():
    mock_result = {
        "context_bundle": {
            "query": "hello",
            "hits": [
                {
                    "chunk_id": "c1",
                    "explain": {"bm25": 1.0},
                    "graph_context": {"distance": 1},
                }
            ],
        },
        "cross_repo_links": [
            {
                "source_repo": "repo1",
                "target_repo": "repo2",
                "link_type": "co_occurrence",
                "confidence": "inferred",
                "evidence_refs": ["c1", "c2"],
            }
        ],
    }

    projected = project_output(mock_result, output_profile="agent_minimal")

    assert "context_bundle" in projected
    assert "cross_repo_links" in projected
    assert projected["cross_repo_links"][0]["link_type"] == "co_occurrence"
    assert projected["cross_repo_links"][0]["confidence"] == "inferred"


def test_agent_profile_agent_minimal_preserves_runtime_federation_trace():
    """project_output must not drop runtime federation_trace when output_profile='agent_minimal'.

    Tests with the runtime inline form of federation_trace (not CLI file-artifact form).
    Runtime form has queried_bundles_total, bundle_status dict, etc.
    CLI form has query, timestamp, bundles[] list (tested separately in test_federation_cli.py).
    """
    mock_result = {
        "context_bundle": {
            "hits": [
                {
                    "chunk_id": "c1",
                    "explain": {"bm25": 1.0},
                    "graph_context": {"distance": 1},
                }
            ]
        },
        "federation_trace": {
            "queried_bundles_total": 1,
            "queried_bundles_effective": 1,
            "bundle_status": {"repo1": "ok"},
            "bundle_errors": {},
            "bundle_traces": {},
        },
    }

    projected = project_output(mock_result, output_profile="agent_minimal")

    # Must return a wrapper (federation_trace triggers wrapper creation)
    assert "context_bundle" in projected, "context_bundle must be present in wrapper"
    assert "federation_trace" in projected, "federation_trace must be preserved by output_profile projection"

    # context_bundle projection must still have applied
    hits = projected["context_bundle"].get("hits", [])
    assert len(hits) == 1
    assert "explain" not in hits[0]
    assert "graph_context" not in hits[0]

    # federation_trace runtime form must be preserved
    ft = projected["federation_trace"]
    assert ft["queried_bundles_total"] == 1
    assert ft["queried_bundles_effective"] == 1
    assert isinstance(ft["bundle_status"], dict)
    assert ft["bundle_status"]["repo1"] == "ok"
    assert isinstance(ft["bundle_errors"], dict)
    assert isinstance(ft["bundle_traces"], dict)


def test_agent_profile_keeps_conflicts_with_cross_repo_links():
    mock_result = {
        "context_bundle": {
            "hits": [{"chunk_id": "c1", "explain": {"bm25": 1.0}}]
        },
        "federation_conflicts": [
            {
                "conflict_id": "conflict_1",
                "type": "path",
                "description": "same filename collision",
                "resolution": "unresolved",
                "involved_results": ["c1", "c2"],
            }
        ],
        "cross_repo_links": [
            {
                "source_repo": "repo1",
                "target_repo": "repo2",
                "link_type": "co_occurrence",
                "confidence": "inferred",
                "evidence_refs": ["c1", "c2"],
            }
        ],
    }

    projected = project_output(mock_result, output_profile="agent_minimal")

    assert "context_bundle" in projected
    assert "federation_conflicts" in projected
    assert "cross_repo_links" in projected
