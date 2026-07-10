import json
from pathlib import Path
from typing import Any, Dict

try:
    import jsonschema
except ImportError:
    jsonschema = None


class EmbeddingPolicyError(RuntimeError):
    pass


def _resolve_policy_file(path: Path) -> Path:
    raw = str(path)
    if not raw.strip() or "\x00" in raw:
        raise EmbeddingPolicyError("Invalid embedding policy path")
    if path.suffix.lower() != ".json":
        raise EmbeddingPolicyError("Embedding policy must be a JSON file")
    try:
        resolved = path.resolve(strict=True)  # lgtm[py/path-injection]
    except (OSError, RuntimeError) as exc:
        raise EmbeddingPolicyError(f"Embedding policy file not found: {path}") from exc
    if not resolved.is_file():  # lgtm[py/path-injection]
        raise EmbeddingPolicyError("Embedding policy path is not a regular file")
    return resolved


def load_and_validate_embedding_policy(path: Path) -> Dict[str, Any]:
    """Load a local operator-selected policy and validate it against the contract."""
    resolved_policy = _resolve_policy_file(path)

    try:
        with resolved_policy.open("r", encoding="utf-8") as handle:  # lgtm[py/path-injection]
            policy_instance = json.load(handle)
    except json.JSONDecodeError as exc:
        raise EmbeddingPolicyError(
            f"Failed to parse embedding policy JSON: {exc}"
        ) from exc
    except OSError as exc:
        raise EmbeddingPolicyError("Could not read embedding policy file") from exc

    schema_path = (
        Path(__file__).resolve().parent.parent
        / "contracts"
        / "embedding-policy.v1.schema.json"
    )
    if not schema_path.exists():
        raise EmbeddingPolicyError(
            f"Embedding policy schema not found at: {schema_path}"
        )

    try:
        with schema_path.open("r", encoding="utf-8") as schema_handle:
            schema = json.load(schema_handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise EmbeddingPolicyError(
            "Could not load embedding policy schema for validation"
        ) from exc

    if jsonschema is None:
        raise EmbeddingPolicyError(
            "Schema validation requested but jsonschema is unavailable in this environment."
        )

    try:
        jsonschema.validate(instance=policy_instance, schema=schema)
    except jsonschema.ValidationError as exc:
        raise EmbeddingPolicyError(
            f"Embedding policy validation failed: {exc.message}"
        ) from exc

    return policy_instance
