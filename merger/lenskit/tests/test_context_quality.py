"""
Unit tests for core/context_quality.py (Context Quality Signals, PR B1).

context_quality is a diagnostic PROJECTION of signals that already exist around a
bundle. It is not a truth source, not an understanding verdict, not a
retrieval-completeness proof, not an answer-safety gate, not a global score, and
not a claim judgment. These tests pin those boundaries.
"""
import hashlib
import json
from pathlib import Path

import jsonschema

from merger.lenskit.core.context_quality import (
    AGENT_USE_CONSTRAINTS,
    DOES_NOT_MEAN,
    compute_context_quality,
    derive_context_quality_path,
    write_context_quality,
)
from merger.lenskit.core.post_emit_health import derive_post_health_path

_CONTRACTS_DIR = Path(__file__).parent.parent / "contracts"
_SCHEMA_PATH = _CONTRACTS_DIR / "context-quality.v1.schema.json"

_CANONICAL = b"# repo: demo\n\n## file: a.py\nx = 1\n"


# Vocabulary that must never leak into the projection as keys or verdict values.
# JSON booleans are fine; these are forbidden as field NAMES and as string
# verdict VALUES. "answer_safe_without_citations" is allowed only in does_not_mean.
_FORBIDDEN_TOKENS = {
    "understanding_health",
    "understanding_score",
    "context_score",
    "agent_safe",
    "agent_ready",
    "safe",
    "unsafe",
    "green",
    "yellow",
    "red",
    "supported",
    "unsupported",
    "true",
    "false",
    "proven",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_bundle(
    tmp_path: Path,
    *,
    include_pack: bool = True,
    include_output_health: bool = True,
    health_verdict: str = "pass",
    include_retrieval_role: bool = False,
    redaction: bool = False,
) -> Path:
    """Build a synthetic bundle on disk and return the manifest path."""
    artifacts = []

    (tmp_path / "demo.md").write_bytes(_CANONICAL)
    artifacts.append({
        "role": "canonical_md", "path": "demo.md", "content_type": "text/markdown",
        "bytes": len(_CANONICAL), "sha256": _sha256(_CANONICAL),
        "authority": "canonical_content", "canonicality": "content_source",
    })

    chunk = {"chunk_id": "c0", "path": "a.py"}
    chunk_bytes = (json.dumps(chunk) + "\n").encode("utf-8")
    (tmp_path / "demo.chunk_index.jsonl").write_bytes(chunk_bytes)
    artifacts.append({
        "role": "chunk_index_jsonl", "path": "demo.chunk_index.jsonl",
        "content_type": "application/x-ndjson", "bytes": len(chunk_bytes),
        "sha256": _sha256(chunk_bytes),
        "authority": "retrieval_index", "canonicality": "derived",
    })

    if include_output_health:
        health_doc = {
            "kind": "lenskit.output_health", "version": "1.0", "run_id": "demo-run",
            "created_at": "2026-05-20T00:00:00Z", "stem": "demo",
            "checks": {
                "canonical_md_hash_ok": True,
                "chunk_index_hash_ok": True,
                "sqlite_row_count_matches_chunk_count": None,
                "fts_content_non_empty": None,
                "range_ref_resolution_status": "no_range_ref",
                "redaction_status_explicit": True,
                "redact_secrets_enabled": redaction,
            },
            "diagnostic_artifacts": {}, "warnings": [], "errors": [],
            "verdict": health_verdict,
        }
        health_bytes = json.dumps(health_doc, indent=2).encode("utf-8")
        (tmp_path / "demo.output_health.json").write_bytes(health_bytes)
        artifacts.append({
            "role": "output_health", "path": "demo.output_health.json",
            "content_type": "application/json", "bytes": len(health_bytes),
            "sha256": _sha256(health_bytes),
            "authority": "diagnostic_signal", "canonicality": "diagnostic",
        })

    if include_pack:
        pack_bytes = b"# Pack\nNAVIGATION, NOT TRUTH\n"
        (tmp_path / "demo.agent_reading_pack.md").write_bytes(pack_bytes)
        artifacts.append({
            "role": "agent_reading_pack", "path": "demo.agent_reading_pack.md",
            "content_type": "text/markdown", "bytes": len(pack_bytes),
            "sha256": _sha256(pack_bytes),
            "authority": "navigation_index", "canonicality": "derived",
        })

    if include_retrieval_role:
        re_bytes = json.dumps(_retrieval_eval_doc(), indent=2).encode("utf-8")
        (tmp_path / "demo.retrieval_eval.json").write_bytes(re_bytes)
        artifacts.append({
            "role": "retrieval_eval_json", "path": "demo.retrieval_eval.json",
            "content_type": "application/json", "bytes": len(re_bytes),
            "sha256": _sha256(re_bytes),
            "authority": "diagnostic_signal", "canonicality": "diagnostic",
            "contract": {"id": "retrieval-eval", "version": "v1"},
            "interpretation": {"mode": "contract"},
        })

    manifest = {
        "kind": "repolens.bundle.manifest", "version": "1.0", "run_id": "demo-run",
        "created_at": "2026-05-20T00:00:00Z",
        "generator": {"name": "test", "version": "1.0", "config_sha256": "a" * 64},
        "artifacts": artifacts, "links": {},
        "capabilities": {"fts5_bm25": False, "redaction": redaction},
    }
    manifest_path = tmp_path / "demo.bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def _retrieval_eval_doc() -> dict:
    return {
        "metrics": {
            "recall@10": 80.0,
            "MRR": 0.5,
            "total_queries": 10,
            "hits": 8,
            "stale_flag": False,
            "zero_hit_ratio": 0.1,
            "categories": {
                "symbol": {"total_queries": 4, "hits": 3, "MRR": 0.6, "recall@10": 75.0},
            },
        },
        "details": [],
        "claim_boundaries": {
            "proves": ["index returned ranked candidates"],
            "does_not_prove": ["semantic relevance"],
            "evidence_basis": ["retrieval_metrics"],
            "requires_live_check": True,
        },
    }


def _miss_taxonomy(case_count: int = 2) -> dict:
    """A retrieval-eval miss_taxonomy block, shaped like eval_core.build_miss_taxonomy."""
    cases = [
        {
            "query_index": 0,
            "query": "where is auth handled",
            "expected": ["src/auth.py"],
            "is_relevant": False,
            "observed_top_k_count": 0,
            "miss_types": ["zero_results"],
            "primary_miss_type": "zero_results",
            "classification_basis": ["retrieval_eval_expectations"],
        },
        {
            "query_index": 1,
            "query": "token refresh logic",
            "expected": ["src/token.py"],
            "is_relevant": False,
            "observed_top_k_count": 5,
            "miss_types": ["expected_not_in_top_k"],
            "primary_miss_type": "expected_not_in_top_k",
            "classification_basis": ["retrieval_eval_expectations", "returned_hit_paths"],
        },
    ]
    # Synthesize extra padding cases when a larger sample is requested.
    while len(cases) < case_count:
        i = len(cases)
        cases.append({
            "query_index": i,
            "query": f"padding query {i}",
            "expected": [],
            "is_relevant": False,
            "observed_top_k_count": 0,
            "miss_types": ["unknown"],
            "primary_miss_type": "unknown",
            "classification_basis": ["query_metadata"],
        })
    return {
        "version": "1.0",
        "authority": "diagnostic_signal",
        "risk_class": "diagnostic",
        "classification_basis": [
            "retrieval_eval_expectations",
            "returned_hit_paths",
            "query_metadata",
        ],
        "does_not_prove": [
            "absence_of_retrieval_hit_does_not_prove_absence_in_repository",
            "miss_type_does_not_prove_claim_truth_or_falsehood",
            "ranking_position_does_not_prove_semantic_importance",
            "retrieval_eval_does_not_prove_retrieval_completeness",
            "taxonomy_is_diagnostic_not_authoritative",
        ],
        "aggregate": {
            "total_cases_classified": case_count + 1,
            "total_misses": case_count,
            "by_type": {
                "zero_results": 1,
                "expected_not_in_top_k": 1,
                "expected_rank_below_k": 0,
                "expected_path_not_indexed": 0,
                "expected_symbol_not_indexed": 0,
                "path_or_symbol_metadata_missing": 0,
                "possible_query_vocabulary_gap": 0,
                "possible_filter_scope_gap": 0,
                "noise_or_fixture_hit": 0,
                "stale_eval_input": 0,
                "query_execution_error": 0,
                "unknown": max(0, case_count - 2),
            },
        },
        "cases": cases[:case_count],
    }


def _write_post_emit_sidecar(manifest_path: Path, status: str = "pass") -> Path:
    doc = {
        "kind": "lenskit.post_emit_health", "version": "1.0", "run_id": "pe-run",
        "bundle_run_id": "demo-run", "checked_at": "2026-05-23T00:00:00Z",
        "bundle_manifest_path": str(manifest_path), "status": status,
        "checks": [], "errors": [], "warnings": [],
        "does_not_mean": ["repo_understood", "answer_safe_without_citations"],
        "independence_note": "output_health.verdict=pass does not imply post_emit_health.status=pass",
        "evidence_level": "navigable",
        "evidence_levels_reached": ["readable", "navigable"],
        "artifact_count_checked": 3, "hash_mismatch_count": 0, "missing_artifact_count": 0,
    }
    out = derive_post_health_path(manifest_path.resolve())
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return out


def _write_export_gate(tmp_path: Path, status: str = "pass") -> Path:
    doc = {
        "kind": "lenskit.agent_export_gate", "version": "1.0", "status": status,
        "profile": "agent_minimal", "agent_facing": True,
        "checked_at": "2026-05-23T00:00:00Z", "bundle_manifest_path": "x",
        "post_emit_health_status": "pass", "output_health_verdict_observed": "pass",
        "redaction_required": True, "redaction_enabled": True,
        "errors": [], "warnings": [],
        "does_not_mean": ["repo_understood", "answer_safe_without_citations", "claims_true"],
    }
    out = tmp_path / "demo.export_gate.json"
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return out


def _iter_strings(obj, path=""):
    """Yield (path, key, value) for every dict key and string value in obj."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path, k, None
            yield from _iter_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _iter_strings(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, None, obj


# ---------------------------------------------------------------------------
# 1. Clean synthetic bundle produces a schema-valid report
# ---------------------------------------------------------------------------

def test_clean_bundle_is_schema_valid(tmp_path):
    manifest = _make_bundle(tmp_path)
    report = compute_context_quality(str(manifest))
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)
    assert report["kind"] == "lenskit.context_quality"
    assert report["version"] == "1.0"


def test_blocked_and_degraded_reports_are_schema_valid(tmp_path):
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

    # degraded (minimal bundle, optional signals unavailable)
    (tmp_path / "min").mkdir(exist_ok=True)
    minimal = _make_bundle(tmp_path / "min", include_output_health=False)
    degraded = compute_context_quality(str(minimal))
    jsonschema.validate(instance=degraded, schema=schema)
    assert degraded["projection_status"] == "degraded"

    # blocked (missing manifest)
    blocked = compute_context_quality(str(tmp_path / "nope.bundle.manifest.json"))
    jsonschema.validate(instance=blocked, schema=schema)
    assert blocked["projection_status"] == "blocked"


def test_complete_when_all_signals_available(tmp_path):
    manifest = _make_bundle(tmp_path)
    _write_post_emit_sidecar(manifest)
    re_path = tmp_path / "standalone.retrieval_eval.json"
    re_path.write_text(json.dumps(_retrieval_eval_doc()), encoding="utf-8")
    gate_path = _write_export_gate(tmp_path)

    report = compute_context_quality(
        str(manifest),
        retrieval_eval_path=str(re_path),
        agent_export_gate_path=str(gate_path),
    )
    assert report["projection_status"] == "complete"
    assert report["warnings"] == []
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


# ---------------------------------------------------------------------------
# 2. Required authority / risk_class / constraints / disclaimers
# ---------------------------------------------------------------------------

def test_report_carries_authority_risk_constraints_and_disclaimers(tmp_path):
    manifest = _make_bundle(tmp_path)
    report = compute_context_quality(str(manifest))

    assert report["authority"] == "diagnostic_signal"
    assert report["risk_class"] == "diagnostic"

    assert report["agent_use_constraints"]
    assert set(AGENT_USE_CONSTRAINTS).issubset(set(report["agent_use_constraints"]))
    for required in (
        "verify_content_against_canonical_md",
        "cite_canonical_ranges_for_claims",
        "do_not_treat_context_quality_as_repo_understanding",
        "do_not_treat_retrieval_metrics_as_completeness_proof",
        "do_not_treat_export_gate_as_claim_truth",
    ):
        assert required in report["agent_use_constraints"]

    for required in ("repo_understood", "retrieval_complete", "answer_safe_without_citations", "claims_true"):
        assert required in report["does_not_mean"]
    assert set(DOES_NOT_MEAN).issubset(set(report["does_not_mean"]))


# ---------------------------------------------------------------------------
# 3. No global understanding/safety verdict; no forbidden vocabulary
# ---------------------------------------------------------------------------

def test_no_global_understanding_or_safety_verdict(tmp_path):
    manifest = _make_bundle(tmp_path)
    _write_post_emit_sidecar(manifest)
    gate_path = _write_export_gate(tmp_path)
    report = compute_context_quality(
        str(manifest),
        retrieval_eval_path=None,
        agent_export_gate_path=str(gate_path),
    )

    # No top-level global verdict key — only projection_status is allowed.
    assert "understanding_health" not in report
    assert "status" not in report
    assert "verdict" not in report
    assert "agent_safe" not in report
    assert "agent_ready" not in report
    assert report["projection_status"] in {"complete", "degraded", "blocked"}

    # Walk the whole report: no forbidden key names, no forbidden verdict values,
    # and no aggregate score key. answer_safe_without_citations only in does_not_mean.
    for path, key, value in _iter_strings(report):
        if key is not None:
            assert key.lower() not in _FORBIDDEN_TOKENS, f"forbidden key {key!r} at {path}"
            assert not key.lower().endswith("_score"), f"aggregate score key {key!r} at {path}"
            assert key.lower() != "score", f"aggregate score key at {path}"
        if value is not None:
            if value == "answer_safe_without_citations":
                assert "does_not_mean" in path, f"answer_safe_without_citations outside does_not_mean at {path}"
            else:
                assert value.lower() not in _FORBIDDEN_TOKENS, f"forbidden value {value!r} at {path}"


def test_named_blueprint_invariants(tmp_path):
    # Mirrors the blueprint's named B1 tests for traceability.
    manifest = _make_bundle(tmp_path)
    report = compute_context_quality(str(manifest))
    # test_context_quality_has_no_global_understanding_verdict
    assert "understanding_health" not in json.dumps(report)
    # test_context_quality_is_projection_of_existing_signals
    assert set(report["signals"].keys()) == {
        "manifest", "output_health", "post_emit_health",
        "retrieval_eval", "agent_export_gate", "evidence",
    }


# ---------------------------------------------------------------------------
# 4. output_health values projected as observations only
# ---------------------------------------------------------------------------

def test_output_health_projected_as_observation(tmp_path):
    manifest = _make_bundle(tmp_path, health_verdict="warn", redaction=True)
    report = compute_context_quality(str(manifest))

    oh = report["signals"]["output_health"]
    assert oh["available"] is True
    assert oh["source"] == "manifest_role"
    # verdict is surfaced verbatim as an observation, not a context-quality verdict.
    assert oh["verdict_observed"] == "warn"
    assert oh["checks"]["canonical_md_hash_ok"] is True
    assert oh["checks"]["chunk_index_hash_ok"] is True
    assert oh["checks"]["sqlite_row_count_matches_chunk_count"] is None
    assert oh["checks"]["fts_content_non_empty"] is None
    assert oh["checks"]["redaction_status_explicit"] is True
    assert oh["checks"]["redact_secrets_enabled"] is True
    assert oh["checks"]["range_ref_resolution_status"] == "no_range_ref"
    # The projection must not invent post-emit validity from output_health.
    assert report["signals"]["post_emit_health"]["available"] is False


def test_output_health_non_mapping_checks_shape_is_ignored(tmp_path):
    manifest = _make_bundle(tmp_path, health_verdict="pass", redaction=True)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    output_health_artifact = next(a for a in data["artifacts"] if a["role"] == "output_health")
    health_path = tmp_path / output_health_artifact["path"]
    health_doc = json.loads(health_path.read_text(encoding="utf-8"))
    health_doc["checks"] = [
        {"name": "canonical_md_hash_ok", "status": "pass"},
        {"name": "range_ref_resolution_status", "status": "pass", "detail": "ok"},
    ]
    health_bytes = json.dumps(health_doc, indent=2).encode("utf-8")
    health_path.write_bytes(health_bytes)
    output_health_artifact["bytes"] = len(health_bytes)
    output_health_artifact["sha256"] = _sha256(health_bytes)
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")

    report = compute_context_quality(str(manifest))

    oh = report["signals"]["output_health"]
    assert oh["available"] is True
    assert oh["verdict_observed"] == "pass"
    assert oh["checks"] == {
        "canonical_md_hash_ok": None,
        "chunk_index_hash_ok": None,
        "sqlite_row_count_matches_chunk_count": None,
        "fts_content_non_empty": None,
        "range_ref_resolution_status": None,
        "redaction_status_explicit": None,
        "redact_secrets_enabled": None,
    }



# ---------------------------------------------------------------------------
# 5. retrieval_eval metrics projected mechanically
# ---------------------------------------------------------------------------

def test_retrieval_eval_metrics_projected_mechanically(tmp_path):
    manifest = _make_bundle(tmp_path)
    re_path = tmp_path / "standalone.retrieval_eval.json"
    re_path.write_text(json.dumps(_retrieval_eval_doc()), encoding="utf-8")

    report = compute_context_quality(str(manifest), retrieval_eval_path=str(re_path))
    re_sig = report["signals"]["retrieval_eval"]

    assert re_sig["available"] is True
    assert re_sig["source"] == "explicit_path"
    assert re_sig["metrics"] == {
        "recall@10": 80.0,
        "MRR": 0.5,
        "total_queries": 10,
        "hits": 8,
        "zero_hit_ratio": 0.1,
        "stale_flag": False,
    }
    assert re_sig["categories"] == [
        {"category": "symbol", "total_queries": 4, "hits": 3, "MRR": 0.6, "recall@10": 75.0},
    ]


def test_retrieval_eval_resolves_from_manifest_role(tmp_path):
    manifest = _make_bundle(tmp_path, include_retrieval_role=True)
    report = compute_context_quality(str(manifest))
    re_sig = report["signals"]["retrieval_eval"]
    assert re_sig["available"] is True
    assert re_sig["source"] == "manifest_role"
    assert report["signals"]["manifest"]["key_roles"]["retrieval_eval_json"] is True


def test_invalid_retrieval_json_warns_without_fabrication(tmp_path):
    manifest = _make_bundle(tmp_path)
    bad = tmp_path / "bad.retrieval_eval.json"
    bad.write_text("{not valid json", encoding="utf-8")

    report = compute_context_quality(str(manifest), retrieval_eval_path=str(bad))
    re_sig = report["signals"]["retrieval_eval"]
    assert re_sig["available"] is False
    assert "metrics" not in re_sig  # nothing fabricated
    assert "miss_taxonomy" not in re_sig  # nothing fabricated when eval is unavailable
    assert any("retrieval_eval unavailable" in w for w in report["warnings"])
    assert report["projection_status"] == "degraded"


# ---------------------------------------------------------------------------
# 5b. retrieval_eval miss_taxonomy projected mechanically (existing diagnostic)
# ---------------------------------------------------------------------------

def test_retrieval_eval_miss_taxonomy_projected_mechanically(tmp_path):
    manifest = _make_bundle(tmp_path)
    expected_mt = _miss_taxonomy()
    doc = _retrieval_eval_doc()
    doc["miss_taxonomy"] = expected_mt
    re_path = tmp_path / "standalone.retrieval_eval.json"
    re_path.write_text(json.dumps(doc), encoding="utf-8")

    report = compute_context_quality(str(manifest), retrieval_eval_path=str(re_path))
    re_sig = report["signals"]["retrieval_eval"]
    assert re_sig["available"] is True

    mt = re_sig["miss_taxonomy"]
    assert mt["available"] is True
    # The aggregate block is copied verbatim — no new aggregation/score invented.
    assert mt["aggregate"] == expected_mt["aggregate"]
    assert mt["aggregate"]["by_type"]["zero_results"] == 1
    # The does_not_prove boundary is preserved verbatim.
    assert mt["does_not_prove"] == expected_mt["does_not_prove"]
    # A small navigational sample of cases is surfaced (not the full taxonomy).
    assert len(mt["cases_sample"]) == 2
    assert mt["cases_sample"][0]["primary_miss_type"] == "zero_results"
    assert mt["cases_sample"][0]["miss_types"] == ["zero_results"]
    assert mt["cases_sample"][1]["primary_miss_type"] == "expected_not_in_top_k"
    # The projection introduces no truth/completeness/score field of its own.
    assert set(mt.keys()) == {"available", "aggregate", "cases_sample", "does_not_prove"}

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_retrieval_eval_miss_taxonomy_cases_sample_is_capped(tmp_path):
    manifest = _make_bundle(tmp_path)
    doc = _retrieval_eval_doc()
    doc["miss_taxonomy"] = _miss_taxonomy(case_count=12)
    re_path = tmp_path / "standalone.retrieval_eval.json"
    re_path.write_text(json.dumps(doc), encoding="utf-8")

    report = compute_context_quality(str(manifest), retrieval_eval_path=str(re_path))
    mt = report["signals"]["retrieval_eval"]["miss_taxonomy"]
    # Many cases collapse to a small capped navigational sample.
    assert len(mt["cases_sample"]) == 5
    # Aggregate counts still reflect the full set, copied verbatim.
    assert mt["aggregate"]["total_misses"] == 12

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


# ---------------------------------------------------------------------------
# 5c. miss_taxonomy projection is robust against malformed / older JSON shapes
# ---------------------------------------------------------------------------

def _write_eval_with_miss_taxonomy(tmp_path: Path, miss_taxonomy: object) -> Path:
    doc = _retrieval_eval_doc()
    doc["miss_taxonomy"] = miss_taxonomy
    re_path = tmp_path / "standalone.retrieval_eval.json"
    re_path.write_text(json.dumps(doc), encoding="utf-8")
    return re_path


def test_retrieval_eval_miss_taxonomy_ignores_non_list_does_not_prove(tmp_path):
    manifest = _make_bundle(tmp_path)
    mt = _miss_taxonomy()
    mt["does_not_prove"] = True  # truthy non-list must not raise
    re_path = _write_eval_with_miss_taxonomy(tmp_path, mt)

    report = compute_context_quality(str(manifest), retrieval_eval_path=str(re_path))
    projected = report["signals"]["retrieval_eval"]["miss_taxonomy"]
    assert projected["available"] is True
    assert projected["does_not_prove"] == []  # degrades to empty, no crash

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_retrieval_eval_miss_taxonomy_ignores_non_list_case_miss_types(tmp_path):
    manifest = _make_bundle(tmp_path)
    mt = _miss_taxonomy()
    mt["cases"][0]["miss_types"] = 404  # truthy non-list must not raise
    re_path = _write_eval_with_miss_taxonomy(tmp_path, mt)

    report = compute_context_quality(str(manifest), retrieval_eval_path=str(re_path))
    projected = report["signals"]["retrieval_eval"]["miss_taxonomy"]
    assert projected["available"] is True
    # The affected case is still projected; only miss_types degrades to [].
    assert projected["cases_sample"][0]["primary_miss_type"] == "zero_results"
    assert projected["cases_sample"][0]["miss_types"] == []

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_retrieval_eval_miss_taxonomy_ignores_non_list_cases(tmp_path):
    manifest = _make_bundle(tmp_path)
    mt = _miss_taxonomy()
    mt["cases"] = True  # truthy non-list must not raise
    re_path = _write_eval_with_miss_taxonomy(tmp_path, mt)

    report = compute_context_quality(str(manifest), retrieval_eval_path=str(re_path))
    projected = report["signals"]["retrieval_eval"]["miss_taxonomy"]
    assert projected["available"] is True
    assert projected["cases_sample"] == []

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_retrieval_eval_miss_taxonomy_samples_valid_cases_after_invalid_entries(tmp_path):
    manifest = _make_bundle(tmp_path)
    mt = _miss_taxonomy()
    # Leading invalid entries must not starve later valid cases from the sample.
    mt["cases"] = [
        None,
        "broken",
        123,
        {"query": "q1", "primary_miss_type": "zero_results", "miss_types": ["zero_results"]},
        {"query": "q2", "primary_miss_type": "expected_not_in_top_k", "miss_types": ["expected_not_in_top_k"]},
        {"query": "q3", "primary_miss_type": "unknown", "miss_types": ["unknown"]},
    ]
    re_path = _write_eval_with_miss_taxonomy(tmp_path, mt)

    report = compute_context_quality(str(manifest), retrieval_eval_path=str(re_path))
    sample = report["signals"]["retrieval_eval"]["miss_taxonomy"]["cases_sample"]
    # All three valid dict cases are collected; the limit is applied AFTER filtering,
    # so slicing the first N raw entries (3 of which are invalid) would have missed q3.
    assert [c["query"] for c in sample] == ["q1", "q2", "q3"]
    assert all(isinstance(c["miss_types"], list) for c in sample)

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_retrieval_eval_miss_taxonomy_non_dict_shape_is_unavailable(tmp_path):
    manifest = _make_bundle(tmp_path)
    re_path = _write_eval_with_miss_taxonomy(tmp_path, "TODO")  # present but not an object

    report = compute_context_quality(str(manifest), retrieval_eval_path=str(re_path))
    re_sig = report["signals"]["retrieval_eval"]
    # retrieval_eval metrics stay available; only the taxonomy projection is unavailable.
    assert re_sig["available"] is True
    mt = re_sig["miss_taxonomy"]
    assert mt["available"] is False
    assert mt["reason"] == "invalid_miss_taxonomy_shape"
    assert not any("miss_taxonomy" in w for w in report["warnings"])  # no warning inflation

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_retrieval_eval_without_miss_taxonomy_stays_valid(tmp_path):
    # An older retrieval-eval document without miss_taxonomy must remain fully
    # valid: it must not warn, must not degrade, and must not raise.
    manifest = _make_bundle(tmp_path)
    _write_post_emit_sidecar(manifest)
    re_path = tmp_path / "standalone.retrieval_eval.json"
    re_path.write_text(json.dumps(_retrieval_eval_doc()), encoding="utf-8")  # no miss_taxonomy
    gate_path = _write_export_gate(tmp_path)

    report = compute_context_quality(
        str(manifest),
        retrieval_eval_path=str(re_path),
        agent_export_gate_path=str(gate_path),
    )
    # Missing miss_taxonomy is silent: no warning, projection still complete.
    assert report["warnings"] == []
    assert report["projection_status"] == "complete"
    assert not any("miss_taxonomy" in w for w in report["warnings"])

    re_sig = report["signals"]["retrieval_eval"]
    assert re_sig["available"] is True
    assert re_sig["metrics"]["total_queries"] == 10  # metrics still projected
    mt = re_sig["miss_taxonomy"]
    assert mt["available"] is False
    assert mt["reason"] == "missing_from_retrieval_eval"

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


# ---------------------------------------------------------------------------
# 6. Missing optional artifacts degrade availability but do not crash
# ---------------------------------------------------------------------------

def test_missing_optional_artifacts_degrade_without_crash(tmp_path):
    manifest = _make_bundle(tmp_path, include_output_health=False)
    report = compute_context_quality(str(manifest))

    assert report["projection_status"] == "degraded"
    assert report["signals"]["output_health"]["available"] is False
    assert report["signals"]["post_emit_health"]["available"] is False
    assert report["signals"]["retrieval_eval"]["available"] is False
    assert report["signals"]["agent_export_gate"]["available"] is False
    assert report["signals"]["evidence"]["available"] is False
    # manifest signal is still available and surfaces role presence
    assert report["signals"]["manifest"]["available"] is True
    assert report["signals"]["manifest"]["key_roles"]["canonical_md"] is True
    assert report["signals"]["manifest"]["key_roles"]["output_health"] is False


# ---------------------------------------------------------------------------
# 7. Unreadable / non-bundle manifest blocks
# ---------------------------------------------------------------------------

def test_missing_manifest_blocks(tmp_path):
    report = compute_context_quality(str(tmp_path / "nope.bundle.manifest.json"))
    assert report["projection_status"] == "blocked"
    assert report["bundle_run_id"] is None
    assert report["errors"]


def test_non_bundle_manifest_blocks(tmp_path):
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"kind": "something.else", "run_id": "x"}), encoding="utf-8")
    report = compute_context_quality(str(other))
    assert report["projection_status"] == "blocked"
    assert any("not a repolens.bundle.manifest" in e for e in report["errors"])


def test_non_json_manifest_blocks(tmp_path):
    junk = tmp_path / "junk.bundle.manifest.json"
    junk.write_text("not json at all", encoding="utf-8")
    report = compute_context_quality(str(junk))
    assert report["projection_status"] == "blocked"


# ---------------------------------------------------------------------------
# 8. write persists the artifact without mutating the manifest
# ---------------------------------------------------------------------------

def test_compute_does_not_write(tmp_path):
    manifest = _make_bundle(tmp_path)
    compute_context_quality(str(manifest))
    assert not derive_context_quality_path(manifest.resolve()).exists()


def test_write_persists_unregistered_without_mutating_manifest(tmp_path):
    manifest = _make_bundle(tmp_path)
    manifest_before = manifest.read_text(encoding="utf-8")

    out, report = write_context_quality(str(manifest))

    assert out == derive_context_quality_path(manifest.resolve())
    assert out.exists()
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["projection_status"] == report["projection_status"]
    assert written["kind"] == "lenskit.context_quality"

    # Persistence must NOT mutate or register anything in the manifest.
    assert manifest.read_text(encoding="utf-8") == manifest_before
    data = json.loads(manifest_before)
    assert all(a["role"] != "context_quality" for a in data["artifacts"])


def test_write_explicit_output_path(tmp_path):
    manifest = _make_bundle(tmp_path)
    target = tmp_path / "custom" / "cq.json"
    out, _ = write_context_quality(str(manifest), str(target))
    assert out == target.resolve() or out == target
    assert target.exists()


# ---------------------------------------------------------------------------
# Evidence / post_emit projection details
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_docs_do_not_claim_b2_is_implemented():
    proof = (_REPO_ROOT / "docs" / "proofs" / "context-quality-signals-proof.md").read_text(encoding="utf-8")
    roadmap = (_REPO_ROOT / "docs" / "roadmap" / "lenskit-master-roadmap.md").read_text(encoding="utf-8")

    # Both docs must mention B2.
    assert "B2" in proof
    assert "B2" in roadmap

    # No line may assert B2 is done/implemented without a negation/defer marker.
    _separation_markers = ("nicht", "keine", "separat", "getrennt", "zukünftig", "future", "offen", "defer", "not ")
    for text in (proof, roadmap):
        for line in text.splitlines():
            if "B2" not in line:
                continue
            lowered = line.lower()
            if any(marker in lowered for marker in _separation_markers):
                continue  # explicitly framed as separate / deferred
            assert "umgesetzt" not in lowered, f"line claims B2 done: {line!r}"
            assert "implementiert" not in lowered, f"line claims B2 implemented: {line!r}"
            assert "done" not in lowered, f"line claims B2 done: {line!r}"
            assert "completed" not in lowered, f"line claims B2 completed: {line!r}"


def test_post_emit_and_evidence_projected_from_sidecar(tmp_path):
    manifest = _make_bundle(tmp_path)
    _write_post_emit_sidecar(manifest, status="pass")

    report = compute_context_quality(str(manifest))
    pe = report["signals"]["post_emit_health"]
    assert pe["available"] is True
    assert pe["source"] == "derived_sidecar"
    assert pe["status_observed"] == "pass"
    assert pe["evidence_level"] == "navigable"

    ev = report["signals"]["evidence"]
    assert ev["available"] is True
    assert ev["source"] == "post_emit_health"
    assert ev["evidence_level"] == "navigable"
    assert "navigable" in ev["evidence_levels_reached"]


# ---------------------------------------------------------------------------
# 9. Malformed optional inputs: robustness under non-UTF-8 and invalid evidence
# ---------------------------------------------------------------------------

def test_non_utf8_optional_sidecar_degrades_with_warning(tmp_path):
    manifest = _make_bundle(tmp_path)
    # Write a non-UTF-8 byte sequence as the post_emit_health sidecar.
    sidecar = derive_post_health_path(manifest.resolve())
    sidecar.write_bytes(b"\xff\xfe\x80\x81 bad bytes not utf-8")

    report = compute_context_quality(str(manifest))
    pe = report["signals"]["post_emit_health"]
    assert pe["available"] is False
    assert any("post_emit_health unavailable" in w for w in report["warnings"])
    assert report["projection_status"] == "degraded"
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def _write_post_emit_sidecar_with_bad_evidence(manifest_path: Path) -> None:
    doc = {
        "kind": "lenskit.post_emit_health", "version": "1.0", "run_id": "pe-run",
        "bundle_run_id": "demo-run", "checked_at": "2026-05-23T00:00:00Z",
        "bundle_manifest_path": str(manifest_path), "status": "pass",
        "checks": [], "errors": [], "warnings": [],
        "does_not_mean": ["repo_understood"],
        "independence_note": "test",
        "evidence_level": "ultra_complete",  # not in known vocabulary
        "evidence_levels_reached": ["navigable", "exotic_level", "another_bad"],
        "artifact_count_checked": 1, "hash_mismatch_count": 0, "missing_artifact_count": 0,
    }
    out = derive_post_health_path(manifest_path.resolve())
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def test_unknown_evidence_level_is_filtered_to_null(tmp_path):
    manifest = _make_bundle(tmp_path)
    _write_post_emit_sidecar_with_bad_evidence(manifest)

    report = compute_context_quality(str(manifest))
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    # Must remain schema-valid even though the sidecar has an unknown evidence_level.
    jsonschema.validate(instance=report, schema=schema)

    ev = report["signals"]["evidence"]
    assert ev["available"] is True
    assert ev["evidence_level"] is None  # unknown level filtered to null
    assert any("evidence_level" in w and "ultra_complete" in w for w in report["warnings"])


def test_unknown_evidence_levels_reached_are_dropped_with_warning(tmp_path):
    manifest = _make_bundle(tmp_path)
    _write_post_emit_sidecar_with_bad_evidence(manifest)

    report = compute_context_quality(str(manifest))
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)

    ev = report["signals"]["evidence"]
    assert "exotic_level" not in ev["evidence_levels_reached"]
    assert "another_bad" not in ev["evidence_levels_reached"]
    assert "navigable" in ev["evidence_levels_reached"]  # known value kept
    assert any("evidence_levels_reached" in w for w in report["warnings"])


def _write_post_emit_sidecar_with_overrides(manifest_path: Path, overrides: dict) -> None:
    _write_post_emit_sidecar(manifest_path)
    out = derive_post_health_path(manifest_path.resolve())
    doc = json.loads(out.read_text(encoding="utf-8"))
    doc.update(overrides)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def test_post_emit_health_ignores_non_list_does_not_mean(tmp_path):
    manifest = _make_bundle(tmp_path)
    _write_post_emit_sidecar_with_overrides(manifest, {"does_not_mean": True})

    report = compute_context_quality(str(manifest))
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)

    pe = report["signals"]["post_emit_health"]
    assert pe["available"] is True
    assert pe["does_not_mean"] == []
    # Ensure there's no new warning *just* because does_not_mean wasn't a list
    assert not any("does_not_mean" in w for w in report["warnings"])


def test_post_emit_health_ignores_non_list_evidence_levels_reached(tmp_path):
    manifest = _make_bundle(tmp_path)
    _write_post_emit_sidecar_with_overrides(manifest, {"evidence_levels_reached": 404})

    report = compute_context_quality(str(manifest))
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)

    pe = report["signals"]["post_emit_health"]
    assert pe["available"] is True
    assert pe["evidence_levels_reached"] == []

    ev = report["signals"]["evidence"]
    assert ev["evidence_levels_reached"] == []


def test_post_emit_health_filters_non_string_list_items(tmp_path):
    manifest = _make_bundle(tmp_path)
    _write_post_emit_sidecar_with_overrides(manifest, {
        "does_not_mean": ["repo_understood", 7, False, "claims_true"],
        "evidence_levels_reached": ["readable", None, "range_strict"]
    })

    report = compute_context_quality(str(manifest))
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)

    pe = report["signals"]["post_emit_health"]
    assert pe["available"] is True
    assert pe["does_not_mean"] == ["repo_understood", "claims_true"]
    assert pe["evidence_levels_reached"] == ["readable", "range_strict"]

    ev = report["signals"]["evidence"]
    assert ev["evidence_levels_reached"] == ["readable", "range_strict"]
