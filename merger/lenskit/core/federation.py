import datetime
import json
from pathlib import Path
from typing import Any, Optional

try:
    import jsonschema
    from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
except ImportError:
    jsonschema = None
    JsonSchemaValidationError = None


def _require_jsonschema() -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required for federation schema validation but is not installed.")


FEDERATION_KIND = "repolens.federation.index"
FEDERATION_VERSION = "1.0"


def _resolve_new_federation_index(index_path: Path) -> Path:
    raw = str(index_path)
    if not raw.strip() or "\x00" in raw:
        raise ValueError("Invalid federation index path")
    if index_path.suffix.lower() != ".json":
        raise ValueError("Federation index must be a JSON file")
    try:
        parent = index_path.parent.resolve(strict=True)  # lgtm[py/path-injection]
    except (OSError, RuntimeError) as exc:
        raise FileNotFoundError("Federation index parent directory not found") from exc
    if not parent.is_dir():
        raise ValueError("Federation index parent must be a directory")
    return parent / index_path.name


def _resolve_existing_federation_index(index_path: Path) -> Path:
    raw = str(index_path)
    if not raw.strip() or "\x00" in raw:
        raise ValueError("Invalid federation index path")
    if index_path.suffix.lower() != ".json":
        raise ValueError("Federation index must be a JSON file")
    try:
        resolved = index_path.resolve(strict=True)  # lgtm[py/path-injection]
    except (OSError, RuntimeError) as exc:
        raise FileNotFoundError(f"Federation index not found at: {index_path}") from exc
    if not resolved.is_file():  # lgtm[py/path-injection]
        raise ValueError("Federation index path is not a regular file")
    return resolved

def load_federation_schema() -> Optional[dict]:
    """Loads the federation schema."""
    # Attempt to resolve from module path
    module_dir = Path(__file__).parent
    schema_path = module_dir.parent / "contracts" / "federation-index.v1.schema.json"
    if schema_path.exists():
        with schema_path.open() as f:
            return json.load(f)
    return None

def init_federation(federation_id: str, out_path: Path) -> dict:
    """
    Initializes a new empty federation index adhering to the federation-index.v1.schema.json contract.
    If the file already exists, it raises an exception to prevent accidental overwrites.
    """
    out_path = _resolve_new_federation_index(out_path)

    # We do a quick check to see if the schema exists
    # If not, we fail fast.
    schema = load_federation_schema()
    if not schema:
        raise RuntimeError("Federation schema missing at expected path (contracts/federation-index.v1.schema.json)")

    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()

    fed_data = {
        "kind": FEDERATION_KIND,
        "version": FEDERATION_VERSION,
        "federation_id": federation_id,
        "created_at": now,
        "updated_at": now,
        "bundles": []
    }

    # Validate against our own schema before writing (fail safe)
    _require_jsonschema()

    try:
        jsonschema.validate(instance=fed_data, schema=schema)
    except JsonSchemaValidationError as e:
        raise ValueError(f"Failed to generate valid federation index schema: {e}")

    try:
        # Exclusive creation prevents overwrite and rejects existing symlinks,
        # including dangling links, at the filesystem operation itself.
        with out_path.open("x", encoding="utf-8") as handle:  # lgtm[py/path-injection]
            json.dump(fed_data, handle, indent=2, sort_keys=True)
    except FileExistsError as exc:
        raise FileExistsError(
            f"Federation index already exists at: {out_path.as_posix()}"
        ) from exc

    return fed_data

def validate_federation_data(fed_data: dict[str, Any]) -> bool:
    """
    Validates a federation index object against its schema and logical constraints.

    This is shared by persisted federation_index.json files and transient, read-only
    bundle lists built by callers such as the CLI. It validates only structure and
    identifiers; it does not inspect bundle contents, run refreshes, touch Git or
    establish runtime correctness.
    """
    schema = load_federation_schema()
    if not schema:
        raise RuntimeError("Federation schema missing at expected path (contracts/federation-index.v1.schema.json)")

    _require_jsonschema()

    try:
        jsonschema.validate(instance=fed_data, schema=schema)
    except JsonSchemaValidationError as e:
        raise ValueError(f"Schema validation failed: {e.message} at path {list(e.path)}")

    bundles = fed_data.get("bundles", [])
    repo_ids = set()
    for b in bundles:
        repo_id = b.get("repo_id")
        bundle_path = b.get("bundle_path")

        if not repo_id:
            raise ValueError("Invalid bundle: missing 'repo_id'.")
        if not bundle_path:
            raise ValueError("Invalid bundle: missing 'bundle_path'.")

        if repo_id in repo_ids:
            raise ValueError(f"Duplicate 'repo_id' found: {repo_id}")
        repo_ids.add(repo_id)

    return True


def load_federation_index_data(index_path: Path) -> dict[str, Any]:
    """Load and validate a persisted federation index JSON file."""
    resolved_index = _resolve_existing_federation_index(index_path)
    with resolved_index.open("r", encoding="utf-8") as handle:  # lgtm[py/path-injection]
        fed_data = json.load(handle)

    validate_federation_data(fed_data)
    return fed_data


def validate_federation(index_path: Path) -> bool:
    """
    Validates a federation index against its schema and additional logical constraints.
    Returns True if valid, raises an exception otherwise.
    """
    load_federation_index_data(index_path)
    return True

def inspect_federation(index_path: Path) -> dict:
    """
    Returns a brief, readable summary of a federation index.
    """
    fed_data = load_federation_index_data(index_path)

    federation_id = fed_data.get("federation_id", "<unknown>")
    bundles = fed_data.get("bundles", [])
    updated_at = fed_data.get("updated_at", "<unknown>")

    repo_ids = [b.get("repo_id") for b in bundles if "repo_id" in b]

    return {
        "federation_id": federation_id,
        "bundle_count": len(bundles),
        "repo_ids": repo_ids,
        "updated_at": updated_at
    }

def add_bundle(index_path: Path, repo_id: str, bundle_path: str) -> dict:
    """
    Adds a bundle to an existing federation index.
    Ensures that repo_id is unique and valid before writing.
    """
    index_path = _resolve_existing_federation_index(index_path)

    schema = load_federation_schema()
    if not schema:
        raise RuntimeError("Federation schema missing at expected path (contracts/federation-index.v1.schema.json)")

    with index_path.open("r", encoding="utf-8") as handle:  # lgtm[py/path-injection]
        fed_data = json.load(handle)

    # Pre-validate existing data to prevent poor failure modes (e.g. KeyError on missing repo_id)
    _require_jsonschema()

    try:
        jsonschema.validate(instance=fed_data, schema=schema)
    except JsonSchemaValidationError as e:
        raise ValueError(f"Existing federation index is corrupt: schema validation failed: {e.message} at path {list(e.path)}")

    # Check for uniqueness of repo_id
    for bundle in fed_data.get("bundles", []):
        if bundle.get("repo_id") == repo_id:
            raise ValueError(f"repo_id '{repo_id}' already exists in federation index.")

    # Update state
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()

    new_bundle = {
        "repo_id": repo_id,
        "bundle_path": bundle_path # preserve exactly as passed (opaque string/URI)
    }

    if "bundles" not in fed_data:
        fed_data["bundles"] = []

    fed_data["bundles"].append(new_bundle)

    # Canonicalize bundle order for deterministic federation index output.
    fed_data["bundles"].sort(key=lambda x: x["repo_id"])

    fed_data["updated_at"] = now

    # Validate against our own schema before writing (fail safe)
    _require_jsonschema()

    try:
        jsonschema.validate(instance=fed_data, schema=schema)
    except JsonSchemaValidationError as e:
        raise ValueError(f"Failed to generate valid federation index schema after modification: {e}")

    with index_path.open("w", encoding="utf-8") as handle:  # lgtm[py/path-injection]
        json.dump(fed_data, handle, indent=2, sort_keys=True)

    return fed_data
