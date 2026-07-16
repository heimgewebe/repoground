"""Contract tests for the reproducible call-navigation scale benchmark."""

import hashlib
import json
from pathlib import Path

from merger.lenskit.scripts.bench_call_navigation import (
    DEFAULT_SYNTHETIC_CALL_COUNT,
    run_benchmark,
    synthetic_corpus,
)


def test_acceptance_tier_is_fixed_at_fifty_thousand_calls():
    assert DEFAULT_SYNTHETIC_CALL_COUNT == 50_000


def test_synthetic_corpus_is_deterministic_and_coherent():
    first_calls, first_symbols = synthetic_corpus(500)
    second_calls, second_symbols = synthetic_corpus(500)

    assert first_calls == second_calls
    assert first_symbols == second_symbols
    assert len(first_calls) == 500
    symbol_ids = {symbol["id"] for symbol in first_symbols}
    assert all(
        target_id in symbol_ids
        for call in first_calls
        for target_id in [
            *call["resolved_target_ids"],
            *call["candidate_target_ids"],
        ]
    )
    assert all(call["caller_symbol_id"] in symbol_ids for call in first_calls)


def test_small_benchmark_proves_equivalence_and_reports_all_candidates(tmp_path):
    report = run_benchmark(
        tmp_path,
        synthetic_call_count=600,
        query_repetitions=2,
        cold_repetitions=2,
        mcp_repetitions=2,
        include_real_repo=False,
    )

    assert report["status"] == "pass"
    assert report["configuration"]["fixed_acceptance_tier"] is False
    assert report["decision"]["selected"] == "process_local_in_memory_index"
    assert report["mcp"]["cold_warm_byte_equivalent"] is True
    assert len(report["tiers"]) == 1
    tier = report["tiers"][0]
    assert tier["call_count"] == 600
    assert tier["equivalence"]["byte_equivalent"] is True
    assert tier["linear_scan"]["bundle_bytes"] > 0
    assert tier["process_local_index"]["build_retained_bytes"] > 0
    assert tier["process_local_index"]["build_peak_bytes"] >= tier[
        "process_local_index"
    ]["build_retained_bytes"]
    assert tier["persisted_sidecar"]["sidecar_bytes"] > 0
    assert tier["persisted_sidecar"]["source_hash_bound"] is True


def test_committed_measurement_and_proof_are_consistent():
    root = Path(__file__).parents[3]
    measurement_path = (
        root
        / "docs"
        / "proofs"
        / "repobrief-call-navigation-scale-index-v1.measurement.json"
    )
    proof_path = (
        root
        / "docs"
        / "proofs"
        / "repobrief-call-navigation-scale-index-v1-proof.md"
    )
    raw = measurement_path.read_bytes()
    measurement = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    proof = proof_path.read_text(encoding="utf-8")

    assert measurement["status"] == "pass"
    assert measurement["configuration"]["synthetic_call_count"] == 50_000
    assert measurement["configuration"]["fixed_acceptance_tier"] is True
    assert measurement["decision"]["selected"] == "process_local_in_memory_index"
    assert measurement["decision"]["cache_max_entries"] == 2
    assert measurement["mcp"]["cold_warm_byte_equivalent"] is True
    assert all(
        tier["equivalence"]["byte_equivalent"] is True
        for tier in measurement["tiers"]
    )
    assert all(
        tier["process_local_index"]["warm_query_batch"]["median_ms"]
        < tier["linear_scan"]["warm_query_batch"]["median_ms"]
        for tier in measurement["tiers"]
    )
    assert all(
        tier["persisted_sidecar"]["bundle_overhead_ratio"] > 0
        for tier in measurement["tiers"]
    )
    assert digest in proof
