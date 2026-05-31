import json
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import jsonschema
except ImportError:
    jsonschema = None

from .constants import ArtifactRole


_CONTRACTS_DIR = Path(__file__).parent.parent / "contracts"
_RANGE_REF_V1_SCHEMA_PATH = _CONTRACTS_DIR / "range-ref.v1.schema.json"
_RANGE_REF_V2_SCHEMA_PATH = _CONTRACTS_DIR / "range-ref.v2.schema.json"

def _require_jsonschema() -> None:
    if jsonschema is None:
        raise RuntimeError(
            "Schema validation requested but jsonschema is unavailable in this environment."
        )


@lru_cache(maxsize=8)
def _load_schema(schema_path: Path) -> Dict[str, Any]:
    """Load and parse a range-ref JSON schema, memoized per path.

    Range-ref schemas are immutable, version-pinned files shipped in the repo
    (``range-ref.v1.schema.json`` / ``range-ref.v2.schema.json``). Before this
    cache, ``resolve_range_ref`` re-read and re-parsed the schema on every call,
    i.e. once per chunk when resolving large bundles. ``lru_cache`` does not
    memoize the raised ``RuntimeError``, so a missing file is re-checked on the
    next call rather than negatively cached.

    The returned dict MUST be treated as read-only: it is shared across calls and
    is only ever passed to ``jsonschema.validate()``, which does not mutate it.
    """
    if not schema_path.exists():
        raise RuntimeError(f"Schema file not found: {schema_path}")

    with schema_path.open("r", encoding="utf-8") as f:
        return json.load(f)

def build_explicit_range_ref(
    artifact_role: str,
    repo_id: str,
    file_path: str,
    start_byte: int,
    end_byte: int,
    start_line: int,
    end_line: int,
    content_sha256: str
) -> Dict[str, Any]:
    """
    Builds a dictionary representing an explicit, bundle-backed range reference.
    """
    return {
        "artifact_role": artifact_role,
        "repo_id": repo_id,
        "file_path": file_path,
        "start_byte": start_byte,
        "end_byte": end_byte,
        "start_line": start_line,
        "end_line": end_line,
        "content_sha256": content_sha256
    }


def build_explicit_range_ref_v2(
    artifact_role: str,
    artifact_path: str,
    artifact_byte_start: int,
    artifact_byte_end: int,
    artifact_line_start: int,
    artifact_line_end: int,
    source_file_path: str,
    source_line_start: int,
    source_line_end: int,
    content_sha256: str,
    range_content_sha256: str,
    repo_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "range_ref_version": "2",
        "artifact_role": artifact_role,
        "repo_id": repo_id,
        "artifact_path": artifact_path,
        "artifact_byte_start": artifact_byte_start,
        "artifact_byte_end": artifact_byte_end,
        "artifact_line_start": artifact_line_start,
        "artifact_line_end": artifact_line_end,
        "source_file_path": source_file_path,
        "source_line_start": source_line_start,
        "source_line_end": source_line_end,
        "content_sha256": content_sha256,
        "range_content_sha256": range_content_sha256,
        "file_path": artifact_path,
        "start_byte": artifact_byte_start,
        "end_byte": artifact_byte_end,
        "start_line": artifact_line_start,
        "end_line": artifact_line_end,
    }


def build_derived_range_ref(
    repo_id: str,
    file_path: str,
    start_byte: int,
    end_byte: int,
    start_line: int,
    end_line: int,
    content_sha256: str
) -> Dict[str, Any]:
    """
    Builds a dictionary representing a derived, source-backed range reference.
    """
    return {
        "artifact_role": ArtifactRole.SOURCE_FILE.value,
        "repo_id": repo_id,
        "file_path": file_path,
        "start_byte": start_byte,
        "end_byte": end_byte,
        "start_line": start_line,
        "end_line": end_line,
        "content_sha256": content_sha256
    }


def build_derived_range_ref_v2(
    repo_id: str,
    artifact_path: str,
    artifact_byte_start: int,
    artifact_byte_end: int,
    artifact_line_start: int,
    artifact_line_end: int,
    source_file_path: str,
    source_line_start: int,
    source_line_end: int,
    content_sha256: str,
    range_content_sha256: str,
) -> Dict[str, Any]:
    """
    Builds a v2 derived, source-backed range reference.

    Caller contract:
    - content_sha256 must be the SHA-256 of the full artifact/source file bytes.
    - range_content_sha256 must be the SHA-256 of the extracted byte range.
    - Do not pass the same chunk hash to both fields unless the full artifact bytes
      exactly equal the extracted range bytes.
    """
    return {
        "range_ref_version": "2",
        "artifact_role": ArtifactRole.SOURCE_FILE.value,
        "repo_id": repo_id,
        "artifact_path": artifact_path,
        "artifact_byte_start": artifact_byte_start,
        "artifact_byte_end": artifact_byte_end,
        "artifact_line_start": artifact_line_start,
        "artifact_line_end": artifact_line_end,
        "source_file_path": source_file_path,
        "source_line_start": source_line_start,
        "source_line_end": source_line_end,
        "content_sha256": content_sha256,
        "range_content_sha256": range_content_sha256,
        "file_path": artifact_path,
        "start_byte": artifact_byte_start,
        "end_byte": artifact_byte_end,
        "start_line": artifact_line_start,
        "end_line": artifact_line_end,
    }


def resolve_range_ref(manifest_path: Path, ref: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolves a range_ref against a bundle.manifest.json or dump_index.json to extract
    exact bytes and verify content_sha256.
    """
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    is_v2 = ref.get("range_ref_version") == "2"
    schema_path = _RANGE_REF_V2_SCHEMA_PATH if is_v2 else _RANGE_REF_V1_SCHEMA_PATH
    schema = _load_schema(schema_path)

    _require_jsonschema()

    try:
        jsonschema.validate(instance=ref, schema=schema)
    except jsonschema.ValidationError as e:
        raise ValueError(f"range_ref failed schema: {schema_path.name}: {e.message}")

    role_str = ref.get("artifact_role")

    try:
        role = ArtifactRole(role_str)
    except ValueError:
        raise ValueError(f"Unknown artifact_role: {role_str}")

    target_path_str = None

    if is_v2:
        artifact_path = ref.get("artifact_path")
        if not artifact_path:
            raise ValueError("artifact_path is required when resolving a range_ref v2")

        def _ensure_legacy_alias(legacy_key: str, expected_value: Any) -> None:
            legacy_value = ref.get(legacy_key)
            if legacy_value is not None and legacy_value != expected_value:
                raise ValueError(f"{legacy_key} mismatch: ref={legacy_value} v2={expected_value}")

        _ensure_legacy_alias("file_path", artifact_path)
        _ensure_legacy_alias("start_byte", ref.get("artifact_byte_start"))
        _ensure_legacy_alias("end_byte", ref.get("artifact_byte_end"))
        _ensure_legacy_alias("start_line", ref.get("artifact_line_start"))
        _ensure_legacy_alias("end_line", ref.get("artifact_line_end"))

        if role == ArtifactRole.SOURCE_FILE:
            # Resolve directly against the hub workspace (assuming manifest is in hub/merges/run_id/)
            hub_path = manifest_path.parent.parent.parent
            repo_id = ref.get("repo_id")
            if not repo_id:
                raise ValueError("repo_id is required when resolving a source_file range_ref v2")

            source_file_path = ref.get("source_file_path") or artifact_path
            if not source_file_path:
                raise ValueError("source_file_path is required when resolving a source_file range_ref v2")
            if artifact_path != source_file_path:
                raise ValueError(f"artifact_path mismatch: ref={artifact_path} source={source_file_path}")

            if Path(source_file_path).is_absolute():
                raise ValueError("source_file_path must be a relative path")

            base_repo_path = (hub_path / repo_id).resolve()
            target_path = (base_repo_path / source_file_path).resolve()

            try:
                target_path.relative_to(base_repo_path)
            except ValueError:
                raise ValueError(
                    f"source_file_path '{source_file_path}' attempts to escape the repository directory"
                )
        else:
            if manifest.get("kind") == "repolens.bundle.manifest":
                for artifact in manifest.get("artifacts", []):
                    if artifact.get("role") == role.value:
                        target_path_str = artifact.get("path")
                        break
            elif manifest.get("contract") == "dump-index":
                artifacts = manifest.get("artifacts", {})
                if role.value in artifacts and isinstance(artifacts[role.value], dict):
                    target_path_str = artifacts[role.value].get("path")
                else:
                    for _, artifact in artifacts.items():
                        if isinstance(artifact, dict) and artifact.get("role") == role.value:
                            target_path_str = artifact.get("path")
                            break
            else:
                raise ValueError("Unsupported manifest format (must be bundle.manifest or dump_index)")

            if not target_path_str:
                raise ValueError(f"Artifact with role '{role_str}' not found in manifest")
            if artifact_path != target_path_str:
                raise ValueError(f"artifact_path mismatch: ref={artifact_path} manifest={target_path_str}")

            if Path(target_path_str).is_absolute():
                raise ValueError(
                    f"Artifact path must be a relative path, got: {target_path_str!r}"
                )

            base_dir = manifest_path.parent.resolve()
            target_path = (base_dir / target_path_str).resolve()

            try:
                target_path.relative_to(base_dir)
            except ValueError:
                raise ValueError(
                    f"Artifact path '{target_path_str}' attempts to escape the manifest directory"
                )

        if not target_path.exists():
            raise FileNotFoundError(f"Resolved artifact file not found: {target_path}")

        artifact_byte_start = ref.get("artifact_byte_start")
        artifact_byte_end = ref.get("artifact_byte_end")
        content_sha256 = ref.get("content_sha256")
        range_content_sha256 = ref.get("range_content_sha256")

        if artifact_byte_start is None or artifact_byte_end is None:
            raise ValueError("range_ref v2 must include 'artifact_byte_start' and 'artifact_byte_end'")
        if not content_sha256:
            raise ValueError("range_ref v2 must include a valid 'content_sha256'")
        if not range_content_sha256:
            raise ValueError("range_ref v2 must include a valid 'range_content_sha256'")

        file_bytes = target_path.read_bytes()
        actual_artifact_sha256 = hashlib.sha256(file_bytes).hexdigest()
        if actual_artifact_sha256 != content_sha256:
            raise ValueError(
                f"Artifact content hash mismatch. Expected: {content_sha256}, Actual: {actual_artifact_sha256}"
            )

        file_size = len(file_bytes)
        if artifact_byte_start < 0 or artifact_byte_end > file_size or artifact_byte_start > artifact_byte_end:
            raise ValueError(
                f"Range [{artifact_byte_start}:{artifact_byte_end}] is out of bounds for file size {file_size}"
            )

        content_bytes = file_bytes[artifact_byte_start:artifact_byte_end]
        actual_range_sha256 = hashlib.sha256(content_bytes).hexdigest()
        if actual_range_sha256 != range_content_sha256:
            raise ValueError(
                f"Range content hash mismatch. Expected: {range_content_sha256}, Actual: {actual_range_sha256}"
            )

        try:
            text = content_bytes.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(f"Extracted range could not be decoded as UTF-8: {e}")

        provenance = {
            "run_id": manifest.get("run_id"),
            "artifact_role": role.value,
        }

        if "generator" in manifest and "config_sha256" in manifest["generator"]:
            provenance["config_sha256"] = manifest["generator"]["config_sha256"]

        return {
            "text": text,
            "sha256": actual_range_sha256,
            "bytes": len(content_bytes),
            "lines": [ref.get("artifact_line_start", -1), ref.get("artifact_line_end", -1)],
            "provenance": provenance,
        }

    if role == ArtifactRole.SOURCE_FILE:
        # Resolve directly against the hub workspace (assuming manifest is in hub/merges/run_id/)
        # `manifest_path` is e.g. /hub/merges/test-run/bundle.manifest.json
        # `manifest_path.parent` is /hub/merges/test-run
        # `manifest_path.parent.parent` is /hub/merges
        # `manifest_path.parent.parent.parent` is /hub
        hub_path = manifest_path.parent.parent.parent
        repo_id = ref.get("repo_id")
        if not repo_id:
            raise ValueError("repo_id is required when resolving a source_file range_ref")
        target_path_str = ref.get("file_path")
        if not target_path_str:
            raise ValueError("file_path is required when resolving a source_file range_ref")

        # Path Traversal Protection
        if Path(target_path_str).is_absolute():
            raise ValueError("file_path must be a relative path")

        base_repo_path = (hub_path / repo_id).resolve()
        target_path = (base_repo_path / target_path_str).resolve()

        try:
            target_path.relative_to(base_repo_path)
        except ValueError:
            raise ValueError(f"file_path '{target_path_str}' attempts to escape the repository directory")

    else:
        # Try resolving via bundle manifest format
        if manifest.get("kind") == "repolens.bundle.manifest":
            for artifact in manifest.get("artifacts", []):
                if artifact.get("role") == role.value:
                    target_path_str = artifact.get("path")
                    break
        # Try resolving via dump_index format
        elif manifest.get("contract") == "dump-index":
            artifacts = manifest.get("artifacts", {})
            # O(1) resolution first
            if role.value in artifacts and isinstance(artifacts[role.value], dict):
                target_path_str = artifacts[role.value].get("path")
            else:
                # Fallback to iteration for older formats
                for _, artifact in artifacts.items():
                    if isinstance(artifact, dict) and artifact.get("role") == role.value:
                        target_path_str = artifact.get("path")
                        break
        else:
            raise ValueError("Unsupported manifest format (must be bundle.manifest or dump_index)")

        if not target_path_str:
            raise ValueError(f"Artifact with role '{role_str}' not found in manifest")

        ref_file_path = ref.get("file_path")
        if ref_file_path and ref_file_path != target_path_str:
            raise ValueError(f"file_path mismatch: ref={ref_file_path} manifest={target_path_str}")

        # Path Traversal Protection for non-source_file artifacts
        if Path(target_path_str).is_absolute():
            raise ValueError(
                f"Artifact path must be a relative path, got: {target_path_str!r}"
            )

        base_dir = manifest_path.parent.resolve()
        target_path = (base_dir / target_path_str).resolve()

        try:
            target_path.relative_to(base_dir)
        except ValueError:
            raise ValueError(
                f"Artifact path '{target_path_str}' attempts to escape the manifest directory"
            )

    if not target_path.exists():
        raise FileNotFoundError(f"Resolved artifact file not found: {target_path}")

    start_byte = ref.get("start_byte")
    end_byte = ref.get("end_byte")
    expected_sha256 = ref.get("content_sha256")

    # Since we schema validate, expected_sha256 is guaranteed to be present,
    # but we assert it to satisfy type checkers and prevent logic bypasses
    if not expected_sha256:
        raise ValueError("range_ref must include a valid 'content_sha256'")

    if start_byte is None or end_byte is None:
        raise ValueError("range_ref must include 'start_byte' and 'end_byte'")

    with target_path.open("rb") as f:
        file_size = target_path.stat().st_size
        if start_byte < 0 or end_byte > file_size or start_byte > end_byte:
            raise ValueError(f"Range [{start_byte}:{end_byte}] is out of bounds for file size {file_size}")

        f.seek(start_byte)
        content_bytes = f.read(end_byte - start_byte)

    actual_sha256 = hashlib.sha256(content_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(f"Hash mismatch. Expected: {expected_sha256}, Actual: {actual_sha256}")

    try:
        text = content_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"Extracted range could not be decoded as UTF-8: {e}")

    provenance = {
        "run_id": manifest.get("run_id"),
        "artifact_role": role.value
    }

    if "generator" in manifest and "config_sha256" in manifest["generator"]:
        provenance["config_sha256"] = manifest["generator"]["config_sha256"]

    return {
        "text": text,
        "sha256": actual_sha256,
        "bytes": len(content_bytes),
        "lines": [ref.get("start_line", -1), ref.get("end_line", -1)],
        "provenance": provenance
    }
