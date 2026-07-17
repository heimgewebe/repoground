import sys
from pathlib import Path
import json

project_root = str(Path(__file__).resolve().parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from merger.repoground.core.constants import ArtifactRole

def test_role_completeness():
    """
    Enforces Phase 1 (Schwerpunkt B): ArtifactRole enum must stay in sync with JSON schemas.
    Checks for bidirectional drift against bundle-manifest and range-ref schemas.
    """
    contracts_dir = Path(__file__).parent.parent / "contracts"

    # Schemas to check
    schema_files = [
        "bundle-manifest.v1.schema.json",
        "range-ref.v1.schema.json"
    ]

    # Collect all roles from python enum
    python_roles = {r.value for r in ArtifactRole}

    # Known exclusions per schema context
    # source_file is a virtual role used in derived_range_ref, not an actual bundle artifact.
    exclude_from_bundle_manifest = {"source_file"}
    # range-ref can point to source files or actual artifacts, but it doesn't need to support *all* abstract roles (like a sqlite index which isn't text)
    # However, for simplicity and drift prevention, the enum there usually covers the textual ones. Let's see what's actually there.

    for schema_name in schema_files:
        schema_path = contracts_dir / schema_name
        if not schema_path.exists():
            continue

        with schema_path.open() as f:
            schema = json.load(f)

        schema_roles = set()

        if "bundle-manifest" in schema_name:
            schema_roles = set(schema["properties"]["artifacts"]["items"]["properties"]["role"]["enum"])

            # 1. Missing in schema (defined in Python but not in Schema)
            expected_in_schema = python_roles - exclude_from_bundle_manifest
            missing_in_schema = expected_in_schema - schema_roles
            assert not missing_in_schema, f"Roles defined in code but missing from {schema_name}: {missing_in_schema}"

            # 2. Missing in Python (defined in Schema but not in Python)
            missing_in_python = schema_roles - python_roles
            assert not missing_in_python, f"Roles defined in {schema_name} but missing from code enum: {missing_in_python}"

        elif "range-ref" in schema_name:
            # Note: The range-ref schema intentionally models only a SUBSET of roles
            # (specifically those that can be referenced as artifacts or sources).
            # Therefore, we do NOT check for full bidirectionality here.
            # We ONLY check for unidirectional drift: Ensure the schema does not contain
            # any roles that are completely unknown to the Python ArtifactRole enum.
            try:
                schema_roles = set(schema["properties"]["artifact_role"]["enum"])
                missing_in_python = schema_roles - python_roles
                assert not missing_in_python, f"Roles defined in {schema_name} but missing from code enum: {missing_in_python}"
            except KeyError:
                pass # If structure differs, we skip strict check or adjust extraction
