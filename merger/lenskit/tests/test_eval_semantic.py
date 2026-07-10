import json
import pytest

from merger.lenskit.cli import cmd_eval
from merger.lenskit.retrieval import index_db

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
        {"chunk_id": "c3", "repo_id": "r1", "path": "tests/test_main.py", "content": "def test_main(): pass", "start_line": 1, "end_line": 1, "layer": "test", "artifact_type": "code"},
        {"chunk_id": "c4", "repo_id": "r1", "path": "src/auth/noise.py", "content": "def auth_manager(): pass", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code"},
        {"chunk_id": "c5", "repo_id": "r1", "path": "src/auth/real_auth.py", "content": "class AuthenticationService: pass", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code"}
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    dump_path.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(dump_path, chunk_path, db_path)
    return db_path

def test_eval_semantic_delta(mini_index_for_eval, tmp_path, capsys, monkeypatch):
    # We will write a deterministic mock for _get_semantic_model similar to test_retrieval_query.py

    # Create queries.md
    queries_md = tmp_path / "eval_queries.md"
    # Query "auth" will lexically match "auth_manager" and "real_auth" (via path src/auth) and "login.py"
    # We want semantic to bump "real_auth.py" above "noise.py"
    queries_md.write_text("""
1. **"auth"**
   *Category:* feature
   *Expected:* `real_auth.py`

2. **"test_main"**
   *Category:* test
   *Expected:* `test_main.py`
""", encoding="utf-8")

    # Create policy
    policy_json = tmp_path / "policy.json"
    policy_json.write_text(json.dumps({
        "provider": "local",
        "similarity_metric": "cosine",
        "model_name": "mock-model",
        "dimensions": 384,
        "fallback_behavior": "ignore"
    }), encoding="utf-8")

    class MockSemanticModel:
        def encode(self, texts):
            # If input is string, make it list-like for uniform processing
            is_single = isinstance(texts, str)
            if is_single: texts = [texts]

            embeddings = []
            for t in texts:
                t = t.lower()
                # Determine mock vectors based on content to force order
                if "auth" == t: # query
                    embeddings.append([1.0, 0.0])
                elif "authentication" in t: # matches real_auth.py content
                    embeddings.append([1.0, 0.0])
                elif "auth_manager" in t: # matches noise.py
                    embeddings.append([0.0, 1.0])
                elif "test_main" in t:
                    embeddings.append([1.0, 0.0])
                elif "def" == t:
                    embeddings.append([1.0, 0.0])
                else:
                    embeddings.append([0.5, 0.5])

            if is_single:
                return embeddings[0]
            return embeddings

    def mock_get_semantic_model(name):
        return MockSemanticModel()

    monkeypatch.setattr("merger.lenskit.retrieval.query_core._get_semantic_model", mock_get_semantic_model)

    # Mock args
    class Args:
        index = str(mini_index_for_eval)
        queries = str(queries_md)
        k = 5
        emit = "json"
        stale_policy = "ignore"
        embedding_policy = str(policy_json)
        graph_index = None
        graph_weights = None

    # Run Eval
    ret_code = cmd_eval.run_eval(Args())
    assert ret_code == 0

    # Capture JSON output
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert "metrics" in output
    metrics = output["metrics"]

    # General output structure assertions
    assert "baseline_MRR" in metrics
    assert "semantic_MRR" in metrics
    assert "delta_mrr" in metrics
    assert "delta_recall" in metrics
    assert "baseline_recall@5" in metrics
    assert "semantic_recall@5" in metrics

    # Semantic delta logic assertions
    assert metrics["baseline_hits"] >= 0
    assert metrics["semantic_hits"] >= 0

    # Assert exact arithmetic relationships using approx for floats
    assert metrics["delta_mrr"] == pytest.approx(metrics["semantic_MRR"] - metrics["baseline_MRR"])
    assert metrics["delta_recall"] == pytest.approx(metrics["semantic_recall@5"] - metrics["baseline_recall@5"])

    # Assert genuine improvement! The test is set up so that the semantic model boosts the correct document
    assert metrics["delta_mrr"] > 0

    # In details, verify it emits both baseline and semantic keys and verify delta calculation
    details = output["details"]
    assert len(details) == 2

    auth_detail = next(d for d in details if d["query"] == "auth")
    test_main_detail = next(d for d in details if d["query"] == "test_main")

    for d in details:
        assert "baseline" in d
        assert "semantic" in d
        assert "delta_rr" in d

        assert "rr" in d["baseline"]
        assert "rr" in d["semantic"]
        assert d["delta_rr"] == pytest.approx(d["semantic"]["rr"] - d["baseline"]["rr"])

    # Isolate precision check: "auth" query must explicitly have delta_rr > 0 because
    # baseline lexical finds real_auth.py at a lower rank than the semantic reranker.
    assert auth_detail["delta_rr"] > 0
    assert auth_detail["semantic"]["rr"] > auth_detail["baseline"]["rr"]

    # Isolate precision check: "test_main" should have no delta since baseline gets it at rank 1.
    assert test_main_detail["delta_rr"] == pytest.approx(0.0)
    assert test_main_detail["baseline"]["rr"] == pytest.approx(1.0)
    assert test_main_detail["semantic"]["rr"] == pytest.approx(1.0)

def test_eval_semantic_failure_isolation(mini_index_for_eval, tmp_path, capsys, monkeypatch):
    # Create queries.md
    queries_md = tmp_path / "eval_queries.md"
    queries_md.write_text("""
1. **"test_main"**
   *Category:* test
   *Expected:* `test_main.py`
""", encoding="utf-8")

    # Create policy with strict fail behavior to trigger do_eval exception wrapper
    policy_json = tmp_path / "policy.json"
    policy_json.write_text(json.dumps({
        "provider": "local",
        "similarity_metric": "cosine",
        "model_name": "crashing-model",
        "dimensions": 384,
        "fallback_behavior": "fail"
    }), encoding="utf-8")

    # Mock the model to throw an exception
    class CrashingSemanticModel:
        def encode(self, texts):
            raise RuntimeError("The model crashed!")

    def mock_get_semantic_model(name):
        return CrashingSemanticModel()

    monkeypatch.setattr("merger.lenskit.retrieval.query_core._get_semantic_model", mock_get_semantic_model)

    # Mock args
    class Args:
        index = str(mini_index_for_eval)
        queries = str(queries_md)
        k = 5
        emit = "json"
        stale_policy = "ignore"
        embedding_policy = str(policy_json)
        graph_index = None
        graph_weights = None

    # Run Eval
    ret_code = cmd_eval.run_eval(Args())
    assert ret_code == 0

    # Capture JSON output
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert "metrics" in output
    metrics = output["metrics"]

    # Assert isolation worked
    # With fail policy, semantic execution bubbles exception and caught by do_eval,
    # resulting in 0 semantic score/hit but preserves baseline.
    assert metrics["baseline_hits"] == 1
    assert metrics["semantic_hits"] == 0
    assert metrics["baseline_MRR"] == pytest.approx(1.0)
    assert metrics["semantic_MRR"] == pytest.approx(0.0)

    # Assert errors properly logged
    details = output["details"]
    assert len(details) == 1
    d = details[0]

    assert "error" in d
    assert d["error"] == (
        "Semantic Run Error: Semantic re-ranking failed during encoding "
        "(fallback_behavior=fail)."
    )
    assert "The model crashed!" not in d["error"]
    assert "semantic" in d
    assert "error" in d["semantic"]
    assert d["semantic"]["error"] == (
        "Semantic re-ranking failed during encoding (fallback_behavior=fail)."
    )
    assert "The model crashed!" not in d["semantic"]["error"]

    # Assert baseline was preserved
    assert d["baseline"]["is_relevant"] is True
    assert d["baseline"]["rr"] == pytest.approx(1.0)
