import json
from pathlib import Path
import pytest
import jsonschema

SCHEMA_PATH = Path(__file__).parent.parent / "contracts" / "embedding-policy.v1.schema.json"

@pytest.fixture(scope="module")
def schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def test_valid_policy(schema):
    """Test that a fully populated and minimally populated policy is valid."""
    valid_full = {
        "model_name": "text-embedding-3-small",
        "dimensions": 1536,
        "provider": "api",
        "similarity_metric": "cosine"
    }
    jsonschema.validate(instance=valid_full, schema=schema)

def test_invalid_policy_missing_model_name(schema):
    """Test that missing required 'model_name' raises a ValidationError."""
    invalid = {
        "dimensions": 1536,
        "provider": "api",
        "similarity_metric": "cosine"
    }
    with pytest.raises(jsonschema.ValidationError) as exc_info:
        jsonschema.validate(instance=invalid, schema=schema)
    assert "model_name" in exc_info.value.message

def test_invalid_policy_invalid_provider(schema):
    """Test that an invalid provider enum value raises a ValidationError."""
    invalid = {
        "model_name": "text-embedding-3-small",
        "dimensions": 1536,
        "provider": "cloud",
        "similarity_metric": "cosine"
    }
    with pytest.raises(jsonschema.ValidationError) as exc_info:
        jsonschema.validate(instance=invalid, schema=schema)
    assert exc_info.value.validator == "enum"
    assert "cloud" in exc_info.value.message

def test_invalid_policy_invalid_similarity_metric(schema):
    """Test that an invalid similarity metric enum value raises a ValidationError."""
    invalid = {
        "model_name": "text-embedding-3-small",
        "dimensions": 1536,
        "provider": "api",
        "similarity_metric": "manhattan"
    }
    with pytest.raises(jsonschema.ValidationError) as exc_info:
        jsonschema.validate(instance=invalid, schema=schema)
    assert exc_info.value.validator == "enum"
    assert "manhattan" in exc_info.value.message

def test_invalid_policy_invalid_dimensions(schema):
    """Test that dimensions = 0 (below minimum 1) raises a ValidationError."""
    invalid = {
        "model_name": "text-embedding-3-small",
        "dimensions": 0,
        "provider": "api",
        "similarity_metric": "cosine"
    }
    with pytest.raises(jsonschema.ValidationError) as exc_info:
        jsonschema.validate(instance=invalid, schema=schema)
    assert exc_info.value.validator == "minimum"
