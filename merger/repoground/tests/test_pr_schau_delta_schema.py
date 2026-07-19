import pytest
import json
import jsonschema
from pathlib import Path
from merger.repoground.core.extractor import generate_review_bundle

SCHEMA_PATH = Path(__file__).parent.parent / "contracts" / "pr-schau-delta.v1.schema.json"

@pytest.fixture
def schema():
    if not SCHEMA_PATH.exists():
        pytest.skip("Schema file not found")
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

def validate(data, schema):
    jsonschema.validate(instance=data, schema=schema)

def test_valid_delta(schema):
    data = {
        "kind": "repolens.pr_schau.delta",
        "version": 1,
        "repo": "test-repo",
        "generated_at": "2024-02-14T12:00:00Z",
        "summary": {
            "added": 1,
            "changed": 1,
            "removed": 1
        },
        "files": [
            {
                "path": "added.py",
                "status": "added",
                "size_bytes": 100,
                "sha256": "a" * 64,
                "sha256_status": "ok"
            },
            {
                "path": "changed.py",
                "status": "changed",
                "size_bytes": 200,
                "sha256": None,
                "sha256_status": "missing"
            },
            {
                "path": "removed.py",
                "status": "removed",
                "size_bytes": 50,
                "sha256": None,
                "sha256_status": "skipped"
            }
        ]
    }
    validate(data, schema)

def test_invalid_removed_with_sha(schema):
    data = {
        "kind": "repolens.pr_schau.delta",
        "version": 1,
        "repo": "test-repo",
        "generated_at": "2024-02-14T12:00:00Z",
        "summary": {"added": 0, "changed": 0, "removed": 1},
        "files": [
            {
                "path": "removed.py",
                "status": "removed",
                "size_bytes": 50,
                "sha256": "a" * 64, # SHOULD BE NULL
                "sha256_status": "skipped"
            }
        ]
    }
    with pytest.raises(jsonschema.ValidationError):
        validate(data, schema)

def test_invalid_added_with_skipped(schema):
    data = {
        "kind": "repolens.pr_schau.delta",
        "version": 1,
        "repo": "test-repo",
        "generated_at": "2024-02-14T12:00:00Z",
        "summary": {"added": 1, "changed": 0, "removed": 0},
        "files": [
            {
                "path": "added.py",
                "status": "added",
                "size_bytes": 100,
                "sha256": None,
                "sha256_status": "skipped" # SHOULD NOT BE SKIPPED
            }
        ]
    }
    with pytest.raises(jsonschema.ValidationError):
        validate(data, schema)

def test_additional_properties_forbidden(schema):
    data = {
        "kind": "repolens.pr_schau.delta",
        "version": 1,
        "repo": "test-repo",
        "generated_at": "2024-02-14T12:00:00Z",
        "summary": {"added": 0, "changed": 0, "removed": 0},
        "files": [],
        "extra": "junk" # FORBIDDEN
    }
    with pytest.raises(jsonschema.ValidationError):
        validate(data, schema)

def test_generated_delta_compliance(schema, tmp_path):
    """
    Integration test: verify that generate_review_bundle produces a delta.json
    compliant with pr-schau-delta.v1.schema.json.
    """
    hub_dir = tmp_path / "hub"
    hub_dir.mkdir()

    old_repo = tmp_path / "old_repo"
    old_repo.mkdir()
    (old_repo / "removed.py").write_text("print('gone')", encoding="utf-8")
    (old_repo / "changed.py").write_text("print('v1')", encoding="utf-8")

    new_repo = tmp_path / "new_repo"
    new_repo.mkdir()
    (new_repo / "changed.py").write_text("print('v2')", encoding="utf-8")
    (new_repo / "added.py").write_text("print('hello')", encoding="utf-8")

    repo_name = "integration-test-repo"

    # Run generator
    generate_review_bundle(old_repo, new_repo, repo_name, hub_dir)

    # Locate output
    pr_schau_dir = hub_dir / ".repoground" / "pr-schau" / repo_name
    assert pr_schau_dir.exists()

    # Filter for directories only (defensive)
    ts_folders = [p for p in pr_schau_dir.iterdir() if p.is_dir()]
    assert len(ts_folders) >= 1, "Expected at least one bundle directory"

    # Pick the newest folder if multiple exist
    bundle_dir = max(ts_folders, key=lambda p: p.stat().st_mtime)

    delta_json_path = bundle_dir / "delta.json"
    assert delta_json_path.exists(), "delta.json must be generated"

    delta_data = json.loads(delta_json_path.read_text(encoding="utf-8"))

    # Validate against schema
    jsonschema.validate(instance=delta_data, schema=schema)

    # Verify content logic (briefly)
    summary = delta_data["summary"]
    assert summary["added"] == 1
    assert summary["changed"] == 1
    assert summary["removed"] == 1

    files = delta_data["files"]
    assert len(files) == 3

    def _find(files_list, status):
        hit = next((f for f in files_list if f["status"] == status), None)
        assert hit is not None, (
            f"Expected file with status='{status}'. "
            f"Found statuses={[x.get('status') for x in files_list]}, "
            f"paths={[x.get('path') for x in files_list]}"
        )
        return hit

    added = _find(files, "added")
    assert added["path"] == "added.py"
    assert added["sha256_status"] == "ok"
    assert added["sha256"] is not None

    removed = _find(files, "removed")
    assert removed["path"] == "removed.py"
    assert removed["sha256_status"] == "skipped"
    assert removed["sha256"] is None

    changed = _find(files, "changed")
    assert changed["path"] == "changed.py"
    assert changed["sha256_status"] == "ok"
    assert changed["sha256"] is not None
