import json
import pytest
from pathlib import Path
from merger.lenskit.cli import cmd_eval
from merger.lenskit.retrieval import index_db, eval_core
import jsonschema

@pytest.fixture
def mini_index_for_eval(tmp_path):
    # Setup paths
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    db_path = tmp_path / "index.sqlite"

    # Write chunks covering typical targets
    chunk_data = [
        {"chunk_id": "c1", "repo_id": "r1", "path": "src/auth/login.py", "content": "def login(): pass", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code"},
        {"chunk_id": "c2", "repo_id": "r1", "path": "src/config/settings.py", "content": "SECRET_KEY = 'xyz'", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code"},
        {"chunk_id": "c3", "repo_id": "r1", "path": "docs/api.md", "content": "# API Docs", "start_line": 1, "end_line": 1, "layer": "docs", "artifact_type": "doc"},
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    dump_path.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(dump_path, chunk_path, db_path)
    return db_path


def _load_retrieval_eval_schema():
    schema_path = Path(__file__).resolve().parent.parent / "contracts" / "retrieval-eval.v1.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def test_parse_gold_queries_basic(tmp_path):
    md_file = tmp_path / "queries.md"
    md_content = """
# Test Queries

1. **"find auth"**
   *Intent:* Check login.
   *Category:* security
   *Expected:* `login.py`, `auth/`
   *Filter:* `layer=core`

2. **"find settings"**
   *Expected:* `settings.py`
"""
    md_file.write_text(md_content, encoding="utf-8")

    queries = eval_core.parse_gold_queries(md_file)
    assert len(queries) == 2

    q1 = queries[0]
    assert q1["query"] == "find auth"
    assert q1["category"] == "security"
    assert "login.py" in q1["expected_paths"]
    assert "auth/" in q1["expected_paths"]
    assert q1["filters"]["layer"] == "core"

    q2 = queries[1]
    assert q2["query"] == "find settings"
    assert q2["category"] is None
    assert "settings.py" in q2["expected_paths"]

def test_parse_gold_queries_robustness(tmp_path):
    # Test weird formatting
    md_file = tmp_path / "messy.md"
    md_content = """
10. **"weird query"**
   - Expected: `foo`
   * Filter: `ext=py` `repo=main`
"""
    md_file.write_text(md_content, encoding="utf-8")

    queries = eval_core.parse_gold_queries(md_file)
    assert len(queries) == 1
    q = queries[0]
    assert q["query"] == "weird query"
    assert "foo" in q["expected_paths"]
    assert q["filters"]["ext"] == "py"
    assert q["filters"]["repo"] == "main"

def test_run_eval_integration(mini_index_for_eval, tmp_path, capsys):
    # Create a query file that matches the mini index
    queries_md = tmp_path / "eval_queries.md"
    queries_md.write_text("""
1. **"login"**
   *Category:* feature
   *Expected:* `login.py`

2. **"missing thing"**
   *Category:* test
   *Expected:* `unicorn.py`
""", encoding="utf-8")

    # Mock args
    class Args:
        index = str(mini_index_for_eval)
        queries = str(queries_md)
        k = 5
        emit = "json"
        stale_policy = "ignore"
        embedding_policy = None

    # Run Eval
    ret_code = cmd_eval.run_eval(Args())
    assert ret_code == 0

    # Capture JSON output
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert "metrics" in output
    metrics = output["metrics"]
    assert metrics["total_queries"] == 2
    assert metrics["hits"] == 1
    assert metrics["recall@5"] == 50.0
    assert "zero_hit_ratio" in metrics
    assert metrics["zero_hit_ratio"] == 0.5
    assert "categories" in metrics
    assert "feature" in metrics["categories"]
    assert metrics["categories"]["feature"]["recall@5"] == 100.0

    details = output["details"]
    assert len(details) == 2

    # Check hit
    hit = details[0]
    assert hit["query"] == "login"
    assert hit["category"] == "feature"
    assert "explain" in hit
    assert "fts_query" in hit["explain"]
    assert "top_k_scoring" in hit["explain"]
    assert hit["is_relevant"] is True
    assert "login.py" in hit["hit_path"]

    # Check miss
    miss = details[1]
    assert miss["query"] == "missing thing"
    assert miss["is_relevant"] is False
    assert "explain" in miss
    assert miss["explain"].get("why_zero") == "tokens too restrictive"

def test_schema_validation(mini_index_for_eval, tmp_path):
    """
    Strict validation of the evaluation output against the JSON schema.
    """
    import jsonschema

    queries_json = tmp_path / "eval_queries.json"
    queries_json.write_text(json.dumps([
        {
            "query": "login",
            "category": "architecture",
            "expected_patterns": ["login.py"]
        }
    ]), encoding="utf-8")

    out = eval_core.do_eval(
        index_path=Path(mini_index_for_eval),
        queries_path=queries_json,
        k=5,
        is_json_mode=True,
        is_stale=False
    )

    schema = _load_retrieval_eval_schema()

    jsonschema.validate(instance=out, schema=schema)


def test_schema_smoke():
    """
    Minimal contract check: Ensure output structure matches key expectations
    without full JSON schema validation lib.
    """
    # Resolve schema path relative to this test file for robustness
    # structure: merger/lenskit/tests/test_retrieval_eval.py
    # target: merger/lenskit/contracts/retrieval-eval.v1.schema.json
    # ../../contracts/

    schema_path = Path(__file__).resolve().parent.parent / "contracts" / "retrieval-eval.v1.schema.json"
    assert schema_path.exists(), f"Schema file missing at expected path: {schema_path}"

    schema = _load_retrieval_eval_schema()
    assert "metrics" in schema["properties"]
    assert "details" in schema["properties"]

def test_parse_gold_queries_json(tmp_path):
    json_file = tmp_path / "queries.json"
    json_content = [
        {
            "query": "find auth",
            "category": "architecture",
            "expected_patterns": ["login.py", "auth/"],
            "filters": {"layer": "core"},
            "accept_criteria": {"recall_at_10": 0.5}
        }
    ]
    json_file.write_text(json.dumps(json_content), encoding="utf-8")

    queries = eval_core.parse_gold_queries(json_file)
    assert len(queries) == 1
    q1 = queries[0]
    assert q1["query"] == "find auth"
    assert q1["category"] == "architecture"
    assert "login.py" in q1["expected_paths"]
    assert q1["filters"]["layer"] == "core"
    assert q1["accept_criteria"]["recall_at_10"] == 0.5

def test_run_eval_integration_json(mini_index_for_eval, tmp_path, capsys):
    queries_json = tmp_path / "eval_queries.json"
    queries_json.write_text(json.dumps([
        {
            "query": "login",
            "expected_patterns": ["login.py"],
            "accept_criteria": {"recall_at_5": 0.5}
        },
        {
            "query": "missing thing",
            "expected_patterns": ["unicorn.py"],
            "accept_criteria": {"recall_at_5": 0.5}
        }
    ]), encoding="utf-8")

    class Args:
        index = str(mini_index_for_eval)
        queries = str(queries_json)
        k = 5
        emit = "json"
        stale_policy = "ignore"
        embedding_policy = None

    # Run Eval
    ret_code = cmd_eval.run_eval(Args())
    assert ret_code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["metrics"]["recall@5"] == 50.0

    # Test why-Propagation for hits
    details = output["details"]
    login_hit = next(d for d in details if d["query"] == "login")
    assert login_hit["is_relevant"] is True
    assert "why" in login_hit
    why = login_hit["why"]
    assert "matched_terms" in why
    assert "filter_pass" in why
    assert "rank_features" in why

def test_run_eval_gate_failure(mini_index_for_eval, tmp_path, capsys):
    queries_json = tmp_path / "eval_queries.json"
    queries_json.write_text(json.dumps([
        {
            "query": "missing thing",
            "expected_patterns": ["unicorn.py"],
            "accept_criteria": {"recall_at_5": 0.8}
        }
    ]), encoding="utf-8")

    class Args:
        index = str(mini_index_for_eval)
        queries = str(queries_json)
        k = 5
        emit = "json"
        stale_policy = "ignore"
        embedding_policy = None

    # Should fail due to accept criteria gate
    ret_code = cmd_eval.run_eval(Args())
    assert ret_code == 1

def test_run_eval_conflicting_thresholds_fails(mini_index_for_eval, tmp_path, capsys):
    queries_json = tmp_path / "eval_queries.json"
    queries_json.write_text(json.dumps([
        {
            "query": "login",
            "expected_patterns": ["login.py"],
            "accept_criteria": {"recall_at_5": 0.5}
        },
        {
            "query": "missing thing",
            "expected_patterns": ["unicorn.py"],
            "accept_criteria": {"recall_at_5": 0.6}
        }
    ]), encoding="utf-8")

    class Args:
        index = str(mini_index_for_eval)
        queries = str(queries_json)
        k = 5
        emit = "json"
        stale_policy = "ignore"
        embedding_policy = None

    ret_code = cmd_eval.run_eval(Args())
    assert ret_code == 1
    captured = capsys.readouterr()
    assert "Error: Multiple conflicting recall_at_5 thresholds found in queries" in captured.err

def test_run_eval_invalid_threshold_fails(mini_index_for_eval, tmp_path, capsys):
    queries_json = tmp_path / "eval_queries.json"
    queries_json.write_text(json.dumps([
        {
            "query": "login",
            "expected_patterns": ["login.py"],
            "accept_criteria": {"recall_at_5": 80.0}
        }
    ]), encoding="utf-8")

    class Args:
        index = str(mini_index_for_eval)
        queries = str(queries_json)
        k = 5
        emit = "json"
        stale_policy = "ignore"
        embedding_policy = None

    ret_code = cmd_eval.run_eval(Args())
    assert ret_code == 1
    captured = capsys.readouterr()
    assert "Error: Invalid recall_at_5 threshold (80.0). accept_criteria must use a ratio between 0.0 and 1.0." in captured.err


def test_retrieval_eval_claim_boundaries_present(mini_index_for_eval, tmp_path):
    queries_json = tmp_path / "eval_queries.json"
    queries_json.write_text(json.dumps([
        {"query": "login", "expected_patterns": ["login.py"]}
    ]), encoding="utf-8")

    out = eval_core.do_eval(
        index_path=Path(mini_index_for_eval),
        queries_path=queries_json,
        k=5,
        is_json_mode=True,
        is_stale=False
    )

    assert "claim_boundaries" in out
    cb = out["claim_boundaries"]
    assert cb["requires_live_check"] is True
    standard_sources = {"eval_queries", "expected_targets", "query_results", "index", "retrieval_metrics"}
    assert standard_sources.issubset(set(cb["evidence_basis"]))
    assert "graph_index" not in cb["evidence_basis"]


def test_retrieval_eval_claim_boundaries_schema_valid(mini_index_for_eval, tmp_path):
    import jsonschema

    queries_json = tmp_path / "eval_queries.json"
    queries_json.write_text(json.dumps([
        {"query": "login", "expected_patterns": ["login.py"]}
    ]), encoding="utf-8")

    out = eval_core.do_eval(
        index_path=Path(mini_index_for_eval),
        queries_path=queries_json,
        k=5,
        is_json_mode=True,
        is_stale=False
    )

    schema = _load_retrieval_eval_schema()
    jsonschema.validate(instance=out, schema=schema)


def test_retrieval_eval_claim_boundaries_reject_unknown_evidence():
    import jsonschema

    schema = _load_retrieval_eval_schema()

    invalid_output = {
        "metrics": {"total_queries": 1, "hits": 0, "stale_flag": False},
        "details": [],
        "claim_boundaries": {
            "proves": ["x"],
            "does_not_prove": ["y"],
            "evidence_basis": ["not_a_valid_source"],
            "requires_live_check": True
        }
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_output, schema=schema)


def test_retrieval_eval_claim_boundaries_reject_extra_field():
    import jsonschema

    schema = _load_retrieval_eval_schema()

    invalid_output = {
        "metrics": {"total_queries": 1, "hits": 0, "stale_flag": False},
        "details": [],
        "claim_boundaries": {
            "proves": ["x"],
            "does_not_prove": ["y"],
            "evidence_basis": ["eval_queries"],
            "requires_live_check": True,
            "unknown_extra_field": "should_fail"
        }
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_output, schema=schema)


def test_retrieval_eval_claim_boundaries_reject_missing_required_subfield():
    import jsonschema

    schema = _load_retrieval_eval_schema()

    invalid_output = {
        "metrics": {"total_queries": 1, "hits": 0, "stale_flag": False},
        "details": [],
        "claim_boundaries": {
            "proves": ["x"],
            "does_not_prove": ["y"],
            "evidence_basis": ["eval_queries"]
            # requires_live_check missing
        }
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_output, schema=schema)


def test_retrieval_eval_schema_rejects_missing_claim_boundaries():
    import jsonschema

    schema = _load_retrieval_eval_schema()

    invalid_output = {
        "metrics": {"total_queries": 1, "hits": 0, "stale_flag": False},
        "details": []
    }

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_output, schema=schema)


def _build_eval_env(tmp_path, graph_index_content=None, graph_invalid=False):
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    db_path = tmp_path / "index.sqlite"
    queries_path = tmp_path / "queries.json"

    chunk_data = [
        {"chunk_id": "c1", "repo_id": "r1", "path": "src/entry.py", "content": "def main(): pass", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h1"},
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    dump_path.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(dump_path, chunk_path, db_path)

    queries_path.write_text(json.dumps([
        {"query": "main", "expected_patterns": ["entry.py"]}
    ]), encoding="utf-8")

    graph_path = None
    if graph_invalid:
        graph_path = tmp_path / "bad_graph.json"
        graph_path.write_text("{bad json")
    elif graph_index_content is not None:
        graph_path = tmp_path / "graph_index.json"
        graph_path.write_text(json.dumps(graph_index_content), encoding="utf-8")

    return db_path, queries_path, graph_path


def test_retrieval_eval_claim_boundaries_graph_absent_when_graph_load_fails(tmp_path):
    db_path, queries_path, graph_path = _build_eval_env(tmp_path, graph_invalid=True)

    out = eval_core.do_eval(
        index_path=db_path,
        queries_path=queries_path,
        k=5,
        is_json_mode=True,
        is_stale=False,
        graph_index_path=graph_path
    )

    assert out is not None
    assert "graph_index" not in out["claim_boundaries"]["evidence_basis"]


def test_retrieval_eval_claim_boundaries_graph_present_when_graph_actually_used(tmp_path):
    valid_graph = {
        "kind": "lenskit.architecture.graph_index",
        "version": "1.0",
        "run_id": "test",
        "canonical_dump_index_sha256": "0" * 64,
        "distances": {"file:src/entry.py": 0},
        "metrics": {"entrypoint_count": 1, "nodes_reachable": 1, "unreachable_nodes": 0}
    }
    db_path, queries_path, graph_path = _build_eval_env(tmp_path, graph_index_content=valid_graph)

    out = eval_core.do_eval(
        index_path=db_path,
        queries_path=queries_path,
        k=5,
        is_json_mode=True,
        is_stale=False,
        graph_index_path=graph_path
    )

    assert out is not None
    assert "graph_index" in out["claim_boundaries"]["evidence_basis"]


def test_run_eval_explain_always_present_on_error(mini_index_for_eval, tmp_path, capsys, monkeypatch):
    queries_json = tmp_path / "eval_queries.json"
    queries_json.write_text(json.dumps([
        {
            "query": "login",
            "expected_patterns": ["login.py"],
            "accept_criteria": {"recall_at_5": 0.5}
        }
    ]), encoding="utf-8")
    class Args:
        index = str(mini_index_for_eval)
        queries = str(queries_json)
        k = 5
        emit = "json"
        stale_policy = "ignore"
        embedding_policy = None

    def mock_execute(*args, **kwargs):
        raise RuntimeError("Mock DB Crash")
    monkeypatch.setattr(eval_core, "execute_query", mock_execute)

    cmd_eval.run_eval(Args())
    captured = capsys.readouterr()
    detail = json.loads(captured.out)["details"][0]
    assert detail["error"] == "Mock DB Crash"
    assert "explain" in detail
    assert detail["explain"]["why_fail"] == eval_core.WHY_FAIL_QUERY_EXECUTION


# B2 — Retrieval Miss Taxonomy Tests

def test_miss_taxonomy_present_in_output(mini_index_for_eval, tmp_path):
    """Test that miss_taxonomy is always present in retrieval_eval output."""
    queries_json = tmp_path / "eval_queries.json"
    queries_json.write_text(json.dumps([
        {"query": "login", "expected_patterns": ["login.py"]},
        {"query": "missing", "expected_patterns": ["nonexistent.py"]}
    ]), encoding="utf-8")

    out = eval_core.do_eval(
        index_path=Path(mini_index_for_eval),
        queries_path=queries_json,
        k=5,
        is_json_mode=True,
        is_stale=False
    )

    assert "miss_taxonomy" in out
    taxonomy = out["miss_taxonomy"]
    assert taxonomy["version"] == "1.0"
    assert taxonomy["authority"] == "diagnostic_signal"
    assert taxonomy["risk_class"] == "diagnostic"


def test_miss_taxonomy_schema_validation(mini_index_for_eval, tmp_path):
    """Test that miss_taxonomy passes JSON schema validation."""
    import jsonschema

    queries_json = tmp_path / "eval_queries.json"
    queries_json.write_text(json.dumps([
        {"query": "login", "expected_patterns": ["login.py"]}
    ]), encoding="utf-8")

    out = eval_core.do_eval(
        index_path=Path(mini_index_for_eval),
        queries_path=queries_json,
        k=5,
        is_json_mode=True,
        is_stale=False
    )

    schema = _load_retrieval_eval_schema()
    jsonschema.validate(instance=out, schema=schema)


def test_miss_taxonomy_schema_validation_stale_eval(mini_index_for_eval, tmp_path):
    """Stale eval output must still validate against retrieval-eval schema."""
    import jsonschema

    queries_json = tmp_path / "eval_queries.json"
    queries_json.write_text(json.dumps([
        {"query": "login", "expected_patterns": ["login.py"]},
        {"query": "missing", "expected_patterns": ["nope.py"]}
    ]), encoding="utf-8")

    out = eval_core.do_eval(
        index_path=Path(mini_index_for_eval),
        queries_path=queries_json,
        k=5,
        is_json_mode=True,
        is_stale=True
    )

    schema = _load_retrieval_eval_schema()
    jsonschema.validate(instance=out, schema=schema)

    taxonomy = out["miss_taxonomy"]
    assert "stale_eval_input" in taxonomy["aggregate"]["by_type"]
    assert "stale_eval_marker" not in taxonomy["classification_basis"]


def test_miss_taxonomy_does_not_prove_entries(mini_index_for_eval, tmp_path):
    """Test that does_not_prove entries are present and correct."""
    queries_json = tmp_path / "eval_queries.json"
    queries_json.write_text(json.dumps([
        {"query": "missing", "expected_patterns": ["nonexistent.py"]}
    ]), encoding="utf-8")

    out = eval_core.do_eval(
        index_path=Path(mini_index_for_eval),
        queries_path=queries_json,
        k=5,
        is_json_mode=True,
        is_stale=False
    )

    taxonomy = out["miss_taxonomy"]
    does_not_prove = taxonomy["does_not_prove"]
    
    # Check that required does_not_prove entries are present
    assert "absence_of_retrieval_hit_does_not_prove_absence_in_repository" in does_not_prove
    assert "miss_type_does_not_prove_claim_truth_or_falsehood" in does_not_prove
    assert "ranking_position_does_not_prove_semantic_importance" in does_not_prove
    assert "retrieval_eval_does_not_prove_retrieval_completeness" in does_not_prove
    assert "taxonomy_is_diagnostic_not_authoritative" in does_not_prove


def test_miss_taxonomy_zero_results_classification(mini_index_for_eval, tmp_path):
    """Test that zero_results miss type is correctly classified."""
    queries_json = tmp_path / "eval_queries.json"
    queries_json.write_text(json.dumps([
        {"query": "xyzabc9999", "expected_patterns": ["nowhere.py"]}
    ]), encoding="utf-8")

    out = eval_core.do_eval(
        index_path=Path(mini_index_for_eval),
        queries_path=queries_json,
        k=5,
        is_json_mode=True,
        is_stale=False
    )

    taxonomy = out["miss_taxonomy"]
    aggregate = taxonomy["aggregate"]
    
    # Should have one miss classified as zero_results
    assert aggregate["total_misses"] >= 1
    assert aggregate["by_type"]["zero_results"] >= 1


def test_classify_miss_zero_results():
    """Test the classify_miss function directly for zero_results case."""
    case = {"query": "test"}
    miss_types, primary = eval_core.classify_miss(
        case,
        expected_paths=["foo.py"],
        is_relevant=False,
        found_count=0,
        top_results=[]
    )
    assert "zero_results" in miss_types
    assert primary == "zero_results"


def test_classify_miss_query_execution_error():
    """Query execution failures must classify as query_execution_error, not zero_results."""
    case = {
        "query": "test",
        "error": "Mock DB Crash",
        "explain": {"why_fail": eval_core.WHY_FAIL_QUERY_EXECUTION}
    }
    miss_types, primary = eval_core.classify_miss(
        case,
        expected_paths=["foo.py"],
        is_relevant=False,
        found_count=0,
        top_results=[]
    )
    assert miss_types == ["query_execution_error"]
    assert primary == "query_execution_error"


def test_classify_miss_expected_not_in_top_k():
    """Test the classify_miss function for expected_not_in_top_k case."""
    case = {"query": "test"}
    miss_types, primary = eval_core.classify_miss(
        case,
        expected_paths=["expected.py"],
        is_relevant=False,
        found_count=2,
        top_results=["other1.py", "other2.py"]
    )
    assert "expected_not_in_top_k" in miss_types
    assert primary == "expected_not_in_top_k"


def test_classify_miss_hit_case():
    """Test that hit cases are not classified as misses."""
    case = {"query": "test"}
    miss_types, primary = eval_core.classify_miss(
        case,
        expected_paths=["foo.py"],
        is_relevant=True,
        found_count=1,
        top_results=["foo.py"]
    )
    assert miss_types == []
    assert primary is None


def test_classify_miss_missing_metadata():
    """Test classification when expected metadata is missing."""
    case = {"query": "test"}
    miss_types, primary = eval_core.classify_miss(
        case,
        expected_paths=[],  # No expected paths
        is_relevant=False,
        found_count=1,
        top_results=["something.py"]
    )
    assert "path_or_symbol_metadata_missing" in miss_types or primary == "path_or_symbol_metadata_missing"


def test_classify_miss_found_expected_pattern_in_results_but_not_relevant():
    """Regression: is_relevant=False but expected pattern IS found in top results.

    This edge case previously returned ([], "unknown"), violating schema minItems: 1
    on miss_taxonomy.cases[].miss_types. The fix ensures at least ["unknown"] is returned.
    """
    case = {"query": "test"}
    miss_types, primary = eval_core.classify_miss(
        case,
        expected_paths=["expected.py"],
        is_relevant=False,
        found_count=1,
        top_results=["src/expected.py"],  # pattern IS found in results
    )
    # Must always return at least one miss type (schema minItems: 1)
    assert len(miss_types) >= 1
    assert primary == "unknown"
    assert miss_types == ["unknown"]


def test_miss_taxonomy_expected_not_in_top_k_integration(mini_index_for_eval, tmp_path):
    """Integration-level check: do_eval emits expected_not_in_top_k on a real miss with returned results."""
    queries_json = tmp_path / "eval_queries.json"
    queries_json.write_text(json.dumps([
        {"query": "def", "expected_patterns": ["never_there.py"]}
    ]), encoding="utf-8")

    out = eval_core.do_eval(
        index_path=Path(mini_index_for_eval),
        queries_path=queries_json,
        k=5,
        is_json_mode=True,
        is_stale=False
    )

    detail = out["details"][0]
    assert detail["is_relevant"] is False
    assert detail["found_count"] > 0

    cases = out["miss_taxonomy"]["cases"]
    assert len(cases) >= 1
    assert "expected_not_in_top_k" in cases[0]["miss_types"]
    assert cases[0]["primary_miss_type"] == "expected_not_in_top_k"


def test_miss_taxonomy_query_execution_error_not_counted_as_zero_results(mini_index_for_eval, tmp_path, monkeypatch):
    queries_json = tmp_path / "eval_queries.json"
    queries_json.write_text(json.dumps([
        {"query": "login", "expected_patterns": ["login.py"]}
    ]), encoding="utf-8")

    def mock_execute(*args, **kwargs):
        raise RuntimeError("Mock DB Crash")

    monkeypatch.setattr(eval_core, "execute_query", mock_execute)

    out = eval_core.do_eval(
        index_path=Path(mini_index_for_eval),
        queries_path=queries_json,
        k=5,
        is_json_mode=True,
        is_stale=False
    )

    assert out is not None
    aggregate = out["miss_taxonomy"]["aggregate"]["by_type"]
    case = out["miss_taxonomy"]["cases"][0]
    assert aggregate["query_execution_error"] == 1
    assert aggregate["zero_results"] == 0
    assert case["miss_types"][0] == "query_execution_error"
    assert case["primary_miss_type"] == "query_execution_error"


def test_retrieval_eval_schema_backward_compatibility_without_miss_taxonomy():
    """Schema remains backward compatible when miss_taxonomy is omitted."""
    import jsonschema

    schema = _load_retrieval_eval_schema()
    legacy_output = {
        "metrics": {"total_queries": 1, "hits": 0, "stale_flag": False},
        "details": [],
        "claim_boundaries": {
            "proves": ["x"],
            "does_not_prove": ["y"],
            "evidence_basis": ["eval_queries"],
            "requires_live_check": True
        }
    }

    jsonschema.validate(instance=legacy_output, schema=schema)


def test_miss_taxonomy_schema_rejects_missing_required_does_not_prove_entry():
    """Schema must reject miss_taxonomy when one canonical does_not_prove entry is missing."""
    import jsonschema

    schema = _load_retrieval_eval_schema()
    invalid_output = {
        "metrics": {"total_queries": 1, "hits": 0, "stale_flag": False},
        "details": [],
        "claim_boundaries": {
            "proves": ["x"],
            "does_not_prove": ["y"],
            "evidence_basis": ["eval_queries"],
            "requires_live_check": True
        },
        "miss_taxonomy": {
            "version": "1.0",
            "authority": "diagnostic_signal",
            "risk_class": "diagnostic",
            "classification_basis": ["retrieval_eval_expectations"],
            "does_not_prove": [
                "absence_of_retrieval_hit_does_not_prove_absence_in_repository",
                "miss_type_does_not_prove_claim_truth_or_falsehood",
                "ranking_position_does_not_prove_semantic_importance",
                "retrieval_eval_does_not_prove_retrieval_completeness"
            ],
            "aggregate": {
                "total_cases_classified": 0,
                "total_misses": 0,
                "by_type": {
                    "zero_results": 0,
                    "expected_not_in_top_k": 0,
                    "expected_rank_below_k": 0,
                    "expected_path_not_indexed": 0,
                    "expected_symbol_not_indexed": 0,
                    "path_or_symbol_metadata_missing": 0,
                    "possible_query_vocabulary_gap": 0,
                    "possible_filter_scope_gap": 0,
                    "noise_or_fixture_hit": 0,
                    "stale_eval_input": 0,
                    "query_execution_error": 0,
                    "unknown": 0
                }
            },
            "cases": []
        }
    }

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_output, schema=schema)


def test_miss_taxonomy_schema_rejects_missing_required_by_type_key():
    """Schema must reject miss_taxonomy.by_type when a required key is omitted."""
    import jsonschema

    schema = _load_retrieval_eval_schema()
    invalid_output = {
        "metrics": {"total_queries": 1, "hits": 0, "stale_flag": False},
        "details": [],
        "claim_boundaries": {
            "proves": ["x"],
            "does_not_prove": ["y"],
            "evidence_basis": ["eval_queries"],
            "requires_live_check": True
        },
        "miss_taxonomy": {
            "version": "1.0",
            "authority": "diagnostic_signal",
            "risk_class": "diagnostic",
            "classification_basis": ["retrieval_eval_expectations"],
            "does_not_prove": [
                "absence_of_retrieval_hit_does_not_prove_absence_in_repository",
                "miss_type_does_not_prove_claim_truth_or_falsehood",
                "ranking_position_does_not_prove_semantic_importance",
                "retrieval_eval_does_not_prove_retrieval_completeness",
                "taxonomy_is_diagnostic_not_authoritative"
            ],
            "aggregate": {
                "total_cases_classified": 0,
                "total_misses": 0,
                "by_type": {
                    "zero_results": 0,
                    "expected_not_in_top_k": 0,
                    "expected_rank_below_k": 0,
                    "expected_path_not_indexed": 0,
                    "expected_symbol_not_indexed": 0,
                    "path_or_symbol_metadata_missing": 0,
                    "possible_query_vocabulary_gap": 0,
                    "possible_filter_scope_gap": 0,
                    "noise_or_fixture_hit": 0,
                    "stale_eval_input": 0,
                    "unknown": 0
                }
            },
            "cases": []
        }
    }

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_output, schema=schema)


# ---------------------------------------------------------------------------
# C2.1: additive, optional top-level authority/risk_class self-declaration
# ---------------------------------------------------------------------------

def _minimal_valid_retrieval_eval():
    return {
        "metrics": {"total_queries": 1, "hits": 0, "stale_flag": False},
        "details": [],
        "claim_boundaries": {
            "proves": ["x"],
            "does_not_prove": ["y"],
            "evidence_basis": ["eval_queries"],
            "requires_live_check": True,
        },
    }


def test_c2_1_legacy_eval_without_top_level_authority_stays_valid():
    schema = _load_retrieval_eval_schema()
    out = _minimal_valid_retrieval_eval()
    assert "authority" not in out
    assert "risk_class" not in out
    jsonschema.validate(instance=out, schema=schema)


def test_c2_1_correct_top_level_authority_risk_class_valid():
    schema = _load_retrieval_eval_schema()
    out = _minimal_valid_retrieval_eval()
    out["authority"] = "diagnostic_signal"
    out["risk_class"] = "diagnostic"
    jsonschema.validate(instance=out, schema=schema)


def test_c2_1_wrong_top_level_authority_invalid():
    schema = _load_retrieval_eval_schema()
    out = _minimal_valid_retrieval_eval()
    out["authority"] = "canonical_content"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=out, schema=schema)


def test_c2_1_wrong_top_level_risk_class_invalid():
    schema = _load_retrieval_eval_schema()
    out = _minimal_valid_retrieval_eval()
    out["risk_class"] = "content"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=out, schema=schema)
