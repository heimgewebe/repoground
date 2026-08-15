"""Validate component-delta artifacts against their registered RepoGround contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from merger.repoground.core.agent_benchmark_common import (
    AgentBenchmarkError,
    is_repository_relative_path,
    sha256_bytes,
)
from merger.repoground.core.bounded_artifact_read import (
    MAX_REGISTERED_ARTIFACT_BYTES,
    read_stable_regular_file_bytes,
)
from merger.repoground.core.bundle_identity import bundle_identity


_COMPONENT_CONTRACTS = {
    "language_structure_json": {
        "contract": {"id": "language-structure", "version": "v1"},
        "schema": "language-structure.v1.schema.json",
    }
}


def _sha256_digest(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _stable_bytes(path: Path, *, label: str) -> bytes:
    raw, _identity, failure, detail = read_stable_regular_file_bytes(
        path, max_bytes=MAX_REGISTERED_ARTIFACT_BYTES
    )
    if failure is not None or raw is None:
        suffix = f": {detail}" if detail else ""
        raise AgentBenchmarkError(f"{label} {failure or 'unreadable'}{suffix}")
    return raw


def _json_object(raw: bytes, *, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentBenchmarkError(f"{label} is not one UTF-8 JSON object") from exc
    if not isinstance(value, Mapping):
        raise AgentBenchmarkError(f"{label} must be one JSON object")
    return value


def _validate_schema(
    document: Mapping[str, Any], *, schema_name: str, label: str
) -> None:
    try:
        import jsonschema
    except ModuleNotFoundError as exc:
        raise AgentBenchmarkError(
            f"{label} schema validation unavailable: jsonschema is not installed"
        ) from exc
    schema_path = Path(__file__).resolve().parents[1] / "contracts" / schema_name
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft7Validator.check_schema(schema)
        errors = sorted(
            jsonschema.Draft7Validator(schema).iter_errors(document),
            key=lambda item: list(item.path),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        raise AgentBenchmarkError(
            f"{label} schema validation unavailable: {exc}"
        ) from exc
    if errors:
        raise AgentBenchmarkError(f"{label} contract invalid: {errors[0].message}")


def _load_bound_manifest(
    binding: Mapping[str, Any], *, repository_id: str, label: str
) -> tuple[Path, Mapping[str, Any]]:
    manifest_value = binding.get("manifest")
    manifest_sha256 = binding.get("manifest_sha256")
    if (
        not isinstance(manifest_value, str)
        or not manifest_value
        or not Path(manifest_value).is_absolute()
        or not _sha256_digest(manifest_sha256)
    ):
        raise AgentBenchmarkError(
            f"{label} requires an absolute digest-bound manifest for {repository_id}"
        )
    manifest_path = Path(manifest_value)
    manifest_raw = _stable_bytes(manifest_path, label=f"{label} for {repository_id}")
    if sha256_bytes(manifest_raw) != manifest_sha256:
        raise AgentBenchmarkError(f"{label} SHA-256 mismatch for {repository_id}")
    manifest = _json_object(manifest_raw, label=f"{label} for {repository_id}")
    if bundle_identity(manifest) is None:
        raise AgentBenchmarkError(f"{label} identity is invalid for {repository_id}")
    return manifest_path, manifest


def _registered_artifact(
    manifest: Mapping[str, Any],
    *,
    component: str,
    artifact_path: str,
    expected_sha256: str,
) -> Mapping[str, Any]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise AgentBenchmarkError("component manifest has no artifact registry")
    matches = [
        item
        for item in artifacts
        if isinstance(item, Mapping) and item.get("role") == component
    ]
    if len(matches) != 1:
        raise AgentBenchmarkError(
            f"component manifest must register exactly one {component} artifact"
        )
    registered = matches[0]
    if registered.get("path") != artifact_path:
        raise AgentBenchmarkError("component manifest artifact path mismatch")
    if registered.get("sha256") != expected_sha256:
        raise AgentBenchmarkError("component manifest artifact SHA-256 mismatch")
    return registered


def verify_component_artifact_binding(
    repository_binding: Mapping[str, Any],
    *,
    repository_id: str,
    repository_commit: str,
    component: str,
    artifact_path: str,
    expected_sha256: str,
) -> None:
    """Verify manifest membership, component contract, provenance, and exact bytes."""

    contract = _COMPONENT_CONTRACTS.get(component)
    if contract is None:
        raise AgentBenchmarkError(f"unsupported component_delta contract: {component}")
    if not is_repository_relative_path(artifact_path) or not _sha256_digest(
        expected_sha256
    ):
        raise AgentBenchmarkError(
            f"component artifact binding is invalid for {repository_id}"
        )

    manifest_path, manifest = _load_bound_manifest(
        repository_binding,
        repository_id=repository_id,
        label="component manifest",
    )
    registered = _registered_artifact(
        manifest,
        component=component,
        artifact_path=artifact_path,
        expected_sha256=expected_sha256,
    )
    if registered.get("contract") != contract["contract"]:
        raise AgentBenchmarkError(
            f"component manifest contract mismatch for {repository_id}"
        )

    artifact_root = manifest_path.parent.resolve(strict=False)
    candidate = artifact_root / artifact_path
    try:
        candidate.resolve(strict=False).relative_to(artifact_root)
    except ValueError as exc:
        raise AgentBenchmarkError(
            f"component artifact escapes manifest root for {repository_id}"
        ) from exc
    artifact_raw = _stable_bytes(
        candidate, label=f"component artifact for {repository_id}"
    )
    if sha256_bytes(artifact_raw) != expected_sha256:
        raise AgentBenchmarkError(
            f"component artifact SHA-256 mismatch for {repository_id}"
        )
    document = _json_object(
        artifact_raw, label=f"component artifact for {repository_id}"
    )
    _validate_schema(
        document,
        schema_name=str(contract["schema"]),
        label=f"component artifact for {repository_id}",
    )
    source = document.get("source")
    if (
        not isinstance(source, Mapping)
        or source.get("repository_commit") != repository_commit
        or source.get("bundle_manifest") != manifest_path.name
    ):
        raise AgentBenchmarkError(
            f"component artifact provenance mismatch for {repository_id}"
        )

def verify_component_free_manifest_binding(
    repository_binding: Mapping[str, Any],
    *,
    repository_id: str,
    component: str,
) -> None:
    """Verify the baseline manifest cannot expose the tested component."""

    _path, manifest = _load_bound_manifest(
        repository_binding,
        repository_id=repository_id,
        label="component-free baseline manifest",
    )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise AgentBenchmarkError("component-free baseline manifest has no artifact registry")
    if any(
        isinstance(item, Mapping) and item.get("role") == component
        for item in artifacts
    ):
        raise AgentBenchmarkError(
            f"component-free baseline manifest still registers {component} for {repository_id}"
        )


def verify_component_manifest_delta(
    baseline_binding: Mapping[str, Any],
    treatment_binding: Mapping[str, Any],
    *,
    repository_id: str,
    repository_commit: str,
    component: str,
    artifact_path: str,
    expected_sha256: str,
) -> None:
    """Prove baseline and treatment manifests differ only by the component artifact."""

    verify_component_artifact_binding(
        treatment_binding,
        repository_id=repository_id,
        repository_commit=repository_commit,
        component=component,
        artifact_path=artifact_path,
        expected_sha256=expected_sha256,
    )
    verify_component_free_manifest_binding(
        baseline_binding, repository_id=repository_id, component=component
    )
    _baseline_path, baseline_manifest = _load_bound_manifest(
        baseline_binding,
        repository_id=repository_id,
        label="component-free baseline manifest",
    )
    _treatment_path, treatment_manifest = _load_bound_manifest(
        treatment_binding,
        repository_id=repository_id,
        label="component manifest",
    )
    treatment_artifacts = treatment_manifest.get("artifacts")
    if not isinstance(treatment_artifacts, list):
        raise AgentBenchmarkError("component manifest has no artifact registry")
    expected_baseline = dict(treatment_manifest)
    expected_baseline["artifacts"] = [
        item
        for item in treatment_artifacts
        if not (isinstance(item, Mapping) and item.get("role") == component)
    ]
    if baseline_manifest != expected_baseline:
        raise AgentBenchmarkError(
            f"baseline/treatment manifests differ beyond {component} for {repository_id}"
        )


__all__ = [
    "verify_component_artifact_binding",
    "verify_component_free_manifest_binding",
    "verify_component_manifest_delta",
]
