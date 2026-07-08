from merger.lenskit.core.graph_degradation import GRAPH_DOES_NOT_ESTABLISH, graph_availability_degradation, graph_degradation_report, graph_gap_from_availability, graph_load_degradation


def test_graph_load_degradation_blocks_all_non_ok_statuses():
    for status in ["not_found", "invalid_json", "invalid_schema", "validation_unavailable", "stale_or_mismatched", "unreadable", "invalid_path", "unknown"]:
        semantics = graph_load_degradation(status, graph_used=False)
        assert semantics["retrieval_eligible"] is False
        assert semantics["graph_must_not_influence_retrieval"] is True
        assert semantics["graph_used_consistent_with_status"] is True
        assert semantics["degradation"] != "none"
        assert "runtime_reachability" in semantics["does_not_establish"]
        assert "runtime_causality" in semantics["does_not_establish"]
        assert "change_impact" in semantics["does_not_establish"]
        assert "default_promotion_readiness" in semantics["does_not_establish"]


def test_graph_load_degradation_allows_only_ok_to_be_used():
    semantics = graph_load_degradation("ok", graph_used=True)
    assert semantics["degradation"] == "none"
    assert semantics["severity"] == "pass"
    assert semantics["retrieval_eligible"] is True
    assert semantics["graph_must_not_influence_retrieval"] is False
    assert semantics["graph_used_consistent_with_status"] is True


def test_graph_load_degradation_flags_inconsistent_use():
    semantics = graph_load_degradation("stale_or_mismatched", graph_used=True)
    assert semantics["degradation"] == "stale"
    assert semantics["retrieval_eligible"] is False
    assert semantics["graph_must_not_influence_retrieval"] is True
    assert semantics["graph_used_consistent_with_status"] is False


def test_graph_availability_degradation_vocabulary():
    stale = graph_availability_degradation("stale", load_status="stale_or_mismatched")
    missing = graph_availability_degradation("not_generated")
    available = graph_availability_degradation("available", load_status="ok")
    assert stale["degradation"] == "stale"
    assert stale["severity"] == "warn"
    assert stale["retrieval_eligible"] is False
    assert missing["degradation"] == "missing"
    assert missing["severity"] == "info"
    assert available["degradation"] == "none"
    assert available["retrieval_eligible"] is True



def test_generic_graph_degradation_report_preserves_ok_status():
    semantics = graph_degradation_report("ok", retrieval_eligible=True)
    assert semantics["degradation"] == "none"
    assert semantics["severity"] == "pass"
    assert semantics["retrieval_eligible"] is True
    assert semantics["graph_must_not_influence_retrieval"] is False


def test_graph_gap_from_availability_preserves_negative_semantics():
    gap = graph_gap_from_availability("graph_availability", {"status": "stale", "reason": "graph index canonical dump hash does not match this snapshot", "graph_index": {"load_status": "stale_or_mismatched"}})
    assert gap["source"] == "graph_availability"
    assert gap["status"] == "stale"
    assert gap["severity"] == "warn"
    assert gap["degradation"] == "stale"
    assert gap["graph_must_not_influence_retrieval"] is True
    assert set(GRAPH_DOES_NOT_ESTABLISH).issubset(set(gap["does_not_establish"]))
