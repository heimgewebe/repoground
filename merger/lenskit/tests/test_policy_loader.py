import json
import pytest
from merger.lenskit.cli.policy_loader import load_and_validate_embedding_policy, EmbeddingPolicyError

def test_load_and_validate_embedding_policy_success(tmp_path):
    policy_path = tmp_path / "valid_policy.json"
    valid_policy = {
        "model_name": "test-model",
        "dimensions": 128,
        "provider": "local",
        "similarity_metric": "cosine"
    }
    policy_path.write_text(json.dumps(valid_policy), encoding="utf-8")

    loaded = load_and_validate_embedding_policy(policy_path)
    assert loaded["model_name"] == "test-model"
    assert loaded["dimensions"] == 128

def test_load_and_validate_embedding_policy_invalid_json(tmp_path):
    policy_path = tmp_path / "invalid_json.json"
    policy_path.write_text("{ broken json ", encoding="utf-8")

    with pytest.raises(EmbeddingPolicyError) as exc:
        load_and_validate_embedding_policy(policy_path)

    assert "Failed to parse embedding policy JSON" in str(exc.value)

def test_load_and_validate_embedding_policy_invalid_schema(tmp_path):
    policy_path = tmp_path / "invalid_schema.json"
    invalid_policy = {
        "model_name": "test-model",
        "dimensions": -5,  # Invalid minimum
        "provider": "alien", # Invalid enum
        "similarity_metric": "cosine"
    }
    policy_path.write_text(json.dumps(invalid_policy), encoding="utf-8")

    with pytest.raises(EmbeddingPolicyError) as exc:
        load_and_validate_embedding_policy(policy_path)

    assert "Embedding policy validation failed" in str(exc.value)

def test_load_and_validate_embedding_policy_invalid_schema_additional_properties(tmp_path):
    policy_path = tmp_path / "invalid_schema_additional.json"
    invalid_policy = {
        "model_name": "test-model",
        "dimensions": 128,
        "provider": "local",
        "similarity_metric": "cosine",
        "unknown_field": "should fail"
    }
    policy_path.write_text(json.dumps(invalid_policy), encoding="utf-8")

    with pytest.raises(EmbeddingPolicyError) as exc:
        load_and_validate_embedding_policy(policy_path)

    assert "Embedding policy validation failed" in str(exc.value)

def test_load_and_validate_embedding_policy_not_found(tmp_path):
    policy_path = tmp_path / "not_found.json"

    with pytest.raises(EmbeddingPolicyError) as exc:
        load_and_validate_embedding_policy(policy_path)

    assert "Embedding policy file not found" in str(exc.value)


def test_load_embedding_policy_rejects_non_json_file(tmp_path):
    policy_path = tmp_path / "policy.txt"
    policy_path.write_text("{}", encoding="utf-8")

    with pytest.raises(EmbeddingPolicyError, match="must be a JSON file"):
        load_and_validate_embedding_policy(policy_path)


def test_load_embedding_policy_rejects_directory(tmp_path):
    policy_path = tmp_path / "policy.json"
    policy_path.mkdir()

    with pytest.raises(EmbeddingPolicyError, match="not a regular file"):
        load_and_validate_embedding_policy(policy_path)


def test_load_embedding_policy_rejects_nul_path():
    from pathlib import Path

    with pytest.raises(EmbeddingPolicyError, match="Invalid embedding policy path"):
        load_and_validate_embedding_policy(Path("bad\x00policy.json"))
