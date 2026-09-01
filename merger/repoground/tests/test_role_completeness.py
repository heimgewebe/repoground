import json
from pathlib import Path

import pytest

from merger.repoground.core.constants import ArtifactRole


def _extract_enum_roles(schema: object, keys: tuple[str, ...], schema_name: str) -> set[str]:
    node = schema
    try:
        for key in keys:
            if not isinstance(node, dict):
                raise TypeError(f"expected object before {key!r}")
            node = node[key]
    except (KeyError, TypeError) as exc:
        path = ".".join(keys)
        raise AssertionError(
            f"{schema_name} no longer exposes the expected role enum at {path}"
        ) from exc

    if not isinstance(node, list) or not node or not all(isinstance(role, str) for role in node):
        path = ".".join(keys)
        raise AssertionError(
            f"{schema_name} role enum at {path} must be a non-empty list of strings"
        )
    return set(node)


def test_role_completeness():
    """
    Enforces Phase 1 (Schwerpunkt B): ArtifactRole enum must stay in sync with JSON schemas.
    Checks for bidirectional drift against bundle-manifest and range-ref schemas.
    """
    contracts_dir = Path(__file__).parent.parent / "contracts"
    python_roles = {role.value for role in ArtifactRole}

    bundle_schema_path = contracts_dir / "bundle-manifest.v1.schema.json"
    range_ref_schema_path = contracts_dir / "range-ref.v1.schema.json"
    assert bundle_schema_path.is_file(), f"Required schema is missing: {bundle_schema_path}"
    assert range_ref_schema_path.is_file(), f"Required schema is missing: {range_ref_schema_path}"

    with bundle_schema_path.open() as handle:
        bundle_schema = json.load(handle)
    with range_ref_schema_path.open() as handle:
        range_ref_schema = json.load(handle)

    bundle_roles = _extract_enum_roles(
        bundle_schema,
        ("properties", "artifacts", "items", "properties", "role", "enum"),
        bundle_schema_path.name,
    )
    # source_file is a virtual role used in derived_range_ref, not an actual bundle artifact.
    expected_bundle_roles = python_roles - {"source_file"}
    missing_in_bundle_schema = expected_bundle_roles - bundle_roles
    assert not missing_in_bundle_schema, (
        f"Roles defined in code but missing from {bundle_schema_path.name}: "
        f"{missing_in_bundle_schema}"
    )
    missing_in_python = bundle_roles - python_roles
    assert not missing_in_python, (
        f"Roles defined in {bundle_schema_path.name} but missing from code enum: "
        f"{missing_in_python}"
    )

    # range-ref intentionally supports only a subset of ArtifactRole values, but every
    # role it names must still exist in the Python enum. Structural schema drift must
    # fail closed instead of silently skipping this check.
    range_ref_roles = _extract_enum_roles(
        range_ref_schema,
        ("properties", "artifact_role", "enum"),
        range_ref_schema_path.name,
    )
    missing_in_python = range_ref_roles - python_roles
    assert not missing_in_python, (
        f"Roles defined in {range_ref_schema_path.name} but missing from code enum: "
        f"{missing_in_python}"
    )


@pytest.mark.parametrize(
    ("schema", "keys"),
    [
        ({"properties": {}}, ("properties", "artifact_role", "enum")),
        ({"properties": {"artifact_role": {"enum": []}}}, ("properties", "artifact_role", "enum")),
    ],
)
def test_role_enum_extraction_fails_closed(schema: object, keys: tuple[str, ...]):
    with pytest.raises(AssertionError, match="role enum"):
        _extract_enum_roles(schema, keys, "range-ref.v1.schema.json")
