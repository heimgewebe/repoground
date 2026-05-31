import json
import hashlib
from pathlib import Path
import pytest
import jsonschema
from merger.lenskit.core.range_resolver import resolve_range_ref

@pytest.fixture
def manifest_env(tmp_path):
    # Setup dummy manifest and artifact
    manifest_path = tmp_path / "bundle.manifest.json"
    artifact_path = tmp_path / "code.md"

    content = b"Line 1\nLine 2\nLine 3\n"
    artifact_path.write_bytes(content)

    # We want to target "Line 2\n" -> bytes 7 to 14
    start_byte = 7
    end_byte = 14
    expected_sha256 = hashlib.sha256(content[start_byte:end_byte]).hexdigest()

    manifest_data = {
        "kind": "repolens.bundle.manifest",
        "run_id": "test-run",
        "generator": {
            "config_sha256": "dummy-config-hash"
        },
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "code.md"
            }
        ]
    }

    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    return {
        "manifest_path": manifest_path,
        "artifact_path": artifact_path,
        "content": content,
        "start_byte": start_byte,
        "end_byte": end_byte,
        "expected_sha256": expected_sha256
    }


def _build_v2_ref(manifest_env, source_file_path="src/code.md"):
    return {
        "range_ref_version": "2",
        "artifact_role": "canonical_md",
        "repo_id": "test-repo",
        "artifact_path": "code.md",
        "artifact_byte_start": manifest_env["start_byte"],
        "artifact_byte_end": manifest_env["end_byte"],
        "artifact_line_start": 2,
        "artifact_line_end": 2,
        "source_file_path": source_file_path,
        "source_line_start": 11,
        "source_line_end": 11,
        "content_sha256": hashlib.sha256(manifest_env["content"]).hexdigest(),
        "range_content_sha256": manifest_env["expected_sha256"],
        "file_path": "code.md",
        "start_byte": manifest_env["start_byte"],
        "end_byte": manifest_env["end_byte"],
        "start_line": 2,
        "end_line": 2,
    }

def test_valid_range_returns_exact_content(manifest_env):
    ref = {
        "artifact_role": "canonical_md",
        "repo_id": "test-repo",
        "file_path": "code.md",
        "start_byte": manifest_env["start_byte"],
        "end_byte": manifest_env["end_byte"],
        "start_line": 2,
        "end_line": 2,
        "content_sha256": manifest_env["expected_sha256"]
    }

    result = resolve_range_ref(manifest_env["manifest_path"], ref)
    assert result["text"] == "Line 2\n"
    assert result["sha256"] == manifest_env["expected_sha256"]
    assert result["bytes"] == 7


def test_range_ref_v2_schema(manifest_env):
    schema_path = Path(__file__).parent.parent / "contracts" / "range-ref.v2.schema.json"
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    ref = _build_v2_ref(manifest_env)
    jsonschema.validate(instance=ref, schema=schema)

    assert ref["artifact_line_start"] != ref["source_line_start"]
    assert ref["content_sha256"] != ref["range_content_sha256"]

    result = resolve_range_ref(manifest_env["manifest_path"], ref)
    assert result["text"] == "Line 2\n"
    assert result["sha256"] == manifest_env["expected_sha256"]
    assert result["lines"] == [2, 2]


def test_range_ref_v2_schema_missing_range_content_sha256_fails(manifest_env):
    schema_path = Path(__file__).parent.parent / "contracts" / "range-ref.v2.schema.json"
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    ref = _build_v2_ref(manifest_env)
    del ref["range_content_sha256"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=ref, schema=schema)


def test_range_ref_v2_schema_invalid_sha_pattern_fails(manifest_env):
    schema_path = Path(__file__).parent.parent / "contracts" / "range-ref.v2.schema.json"
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    ref = _build_v2_ref(manifest_env)
    ref["range_content_sha256"] = "not-a-sha"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=ref, schema=schema)


def test_range_ref_v2_wrong_artifact_hash_raises_error(manifest_env):
    ref = _build_v2_ref(manifest_env)
    ref["content_sha256"] = "d" * 64

    with pytest.raises(ValueError, match="Artifact content hash mismatch"):
        resolve_range_ref(manifest_env["manifest_path"], ref)


def test_range_ref_v2_wrong_range_hash_raises_error(manifest_env):
    ref = _build_v2_ref(manifest_env)
    ref["range_content_sha256"] = "e" * 64

    with pytest.raises(ValueError, match="Range content hash mismatch"):
        resolve_range_ref(manifest_env["manifest_path"], ref)

def test_wrong_sha256_raises_error(manifest_env):
    ref = {
        "artifact_role": "canonical_md",
        "repo_id": "test-repo",
        "file_path": "code.md",
        "start_byte": manifest_env["start_byte"],
        "end_byte": manifest_env["end_byte"],
        "start_line": 2,
        "end_line": 2,
        "content_sha256": "b"*64
    }
    with pytest.raises(ValueError, match="Hash mismatch"):
        resolve_range_ref(manifest_env["manifest_path"], ref)


def test_range_ref_v1_backwards_compatible(manifest_env):
    ref = {
        "artifact_role": "canonical_md",
        "repo_id": "test-repo",
        "file_path": "code.md",
        "start_byte": manifest_env["start_byte"],
        "end_byte": manifest_env["end_byte"],
        "start_line": 2,
        "end_line": 2,
        "content_sha256": manifest_env["expected_sha256"]
    }

    result = resolve_range_ref(manifest_env["manifest_path"], ref)
    assert result["text"] == "Line 2\n"
    assert result["sha256"] == manifest_env["expected_sha256"]

def test_unknown_role_raises_error(manifest_env):
    ref = {
        "artifact_role": "invalid_role",
        "repo_id": "test-repo",
        "file_path": "code.md",
        "start_byte": 0,
        "end_byte": 5,
        "start_line": 1,
        "end_line": 2,
        "content_sha256": "c"*64
    }
    with pytest.raises(ValueError, match="range_ref failed schema"):
        resolve_range_ref(manifest_env["manifest_path"], ref)

def test_out_of_bounds_range_fails(manifest_env):
    ref = {
        "artifact_role": "canonical_md",
        "repo_id": "test-repo",
        "file_path": "code.md",
        "start_byte": 100,
        "end_byte": 200,
        "start_line": 1,
        "end_line": 2,
        "content_sha256": "a"*64
    }
    with pytest.raises(ValueError, match="out of bounds"):
        resolve_range_ref(manifest_env["manifest_path"], ref)

def test_missing_role_in_manifest(manifest_env):
    ref = {
        "artifact_role": "index_sidecar_json",
        "repo_id": "test-repo",
        "file_path": "code.md",
        "start_byte": 0,
        "end_byte": 5,
        "start_line": 1,
        "end_line": 2,
        "content_sha256": "a"*64
    }
    with pytest.raises(ValueError, match="not found in manifest"):
        resolve_range_ref(manifest_env["manifest_path"], ref)

def test_cli_json_output_structure_valid(manifest_env, tmp_path, monkeypatch, capsys):
    from merger.lenskit.cli.main import main

    ref = {
        "artifact_role": "canonical_md",
        "repo_id": "test-repo",
        "file_path": "code.md",
        "start_byte": manifest_env["start_byte"],
        "end_byte": manifest_env["end_byte"],
        "start_line": 2,
        "end_line": 2,
        "content_sha256": manifest_env["expected_sha256"]
    }
    ref_path = tmp_path / "ref.json"
    ref_path.write_text(json.dumps(ref), encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["lenskit", "range", "get", "--manifest", str(manifest_env["manifest_path"]), "--ref", str(ref_path), "--format", "json"])

    ret = main()
    assert ret == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert "text" in output
    assert "sha256" in output
    assert "bytes" in output
    assert "lines" in output
    assert "provenance" in output

    assert output["text"] == "Line 2\n"
    assert output["sha256"] == manifest_env["expected_sha256"]
    assert output["provenance"]["artifact_role"] == "canonical_md"

def test_schema_validation_passes(manifest_env):
    ref = {
        "artifact_role": "canonical_md",
        "repo_id": "test-repo",
        "file_path": "code.md",
        "start_byte": manifest_env["start_byte"],
        "end_byte": manifest_env["end_byte"],
        "start_line": 2,
        "end_line": 2,
        "content_sha256": manifest_env["expected_sha256"]
    }

    # Valid ref
    result = resolve_range_ref(manifest_env["manifest_path"], ref)
    assert result["text"] == "Line 2\n"

    # Invalid ref missing required field
    ref_invalid = ref.copy()
    del ref_invalid["repo_id"]
    with pytest.raises(ValueError, match="range_ref failed schema"):
        resolve_range_ref(manifest_env["manifest_path"], ref_invalid)

    # Empty content_sha256 is invalid schema
    ref_invalid_sha = ref.copy()
    ref_invalid_sha["content_sha256"] = ""
    with pytest.raises(ValueError, match="range_ref failed schema"):
        resolve_range_ref(manifest_env["manifest_path"], ref_invalid_sha)

def test_source_file_path_traversal_prevention(tmp_path):
    hub_path = tmp_path / "hub"
    hub_path.mkdir()

    # Safe repo
    repo_dir = hub_path / "r1"
    repo_dir.mkdir()

    # Secret repo we want to attack
    secret_dir = hub_path / "r1-secrets"
    secret_dir.mkdir()
    secret_file = secret_dir / "key.txt"
    secret_file.write_bytes(b"SUPER_SECRET")

    merges_dir = hub_path / "merges"
    run_dir = merges_dir / "test-run"
    run_dir.mkdir(parents=True)
    manifest_path = run_dir / "bundle.manifest.json"

    manifest_data = {
        "kind": "repolens.bundle.manifest",
        "run_id": "test-run",
        "artifacts": []
    }
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Attacker tries to break out of r1 to r1-secrets
    ref_malicious_sibling = {
        "artifact_role": "source_file",
        "repo_id": "r1",
        "file_path": "../r1-secrets/key.txt",
        "start_byte": 0,
        "end_byte": 12,
        "start_line": 1,
        "end_line": 1,
        "content_sha256": "a" * 64  # Doesn't matter, should fail before this
    }

    with pytest.raises(ValueError, match="attempts to escape the repository directory"):
        resolve_range_ref(manifest_path, ref_malicious_sibling)

    # Attacker tries an absolute path
    ref_malicious_absolute = {
        "artifact_role": "source_file",
        "repo_id": "r1",
        "file_path": "/etc/passwd",
        "start_byte": 0,
        "end_byte": 10,
        "start_line": 1,
        "end_line": 1,
        "content_sha256": "a" * 64
    }

    with pytest.raises(ValueError, match="file_path must be a relative path"):
        resolve_range_ref(manifest_path, ref_malicious_absolute)


# ---------------------------------------------------------------------------
# Path traversal protection for non-source_file artifacts (bundle/dump-index)
# ---------------------------------------------------------------------------

def _make_dump_index_env(tmp_path, artifact_path_in_manifest: str):
    """
    Build a dump-index manifest that lists canonical_md with the given path.
    Returns (manifest_path, ref_dict).
    """
    dummy_sha = "a" * 64  # Will not pass hash check, but path guard fires first.
    manifest_path = tmp_path / "dump.json"
    manifest_path.write_text(json.dumps({
        "contract": "dump-index",
        "contract_version": "v1",
        "run_id": "test-run",
        "artifacts": {
            "canonical_md": {
                "role": "canonical_md",
                "path": artifact_path_in_manifest,
            }
        }
    }), encoding="utf-8")
    ref = {
        "artifact_role": "canonical_md",
        "repo_id": "testrepo",
        "file_path": artifact_path_in_manifest,
        "start_byte": 0,
        "end_byte": 4,
        "start_line": 1,
        "end_line": 1,
        "content_sha256": dummy_sha,
    }
    return manifest_path, ref


def test_non_source_file_absolute_path_rejected(tmp_path):
    """Artifact path '/etc/passwd' in a dump-index manifest must be rejected."""
    manifest_path, ref = _make_dump_index_env(tmp_path, "/etc/passwd")
    with pytest.raises(ValueError, match="Artifact path must be a relative path"):
        resolve_range_ref(manifest_path, ref)


def test_non_source_file_dotdot_path_rejected(tmp_path):
    """Artifact path '../secret.txt' in a dump-index manifest must be rejected."""
    manifest_path, ref = _make_dump_index_env(tmp_path, "../secret.txt")
    with pytest.raises(ValueError, match="attempts to escape the manifest directory"):
        resolve_range_ref(manifest_path, ref)


def test_non_source_file_safe_relative_path_accepted(tmp_path):
    """A safe relative path in a dump-index manifest must not be rejected by path guards."""
    import hashlib
    content = b"hello world\n"
    artifact = tmp_path / "canonical.md"
    artifact.write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()
    manifest_path = tmp_path / "dump.json"
    manifest_path.write_text(json.dumps({
        "contract": "dump-index",
        "contract_version": "v1",
        "run_id": "test-run",
        "artifacts": {
            "canonical_md": {
                "role": "canonical_md",
                "path": "canonical.md",
            }
        }
    }), encoding="utf-8")
    ref = {
        "artifact_role": "canonical_md",
        "repo_id": "testrepo",
        "file_path": "canonical.md",
        "start_byte": 0,
        "end_byte": len(content),
        "start_line": 1,
        "end_line": 1,
        "content_sha256": sha,
    }
    result = resolve_range_ref(manifest_path, ref)
    assert result["text"] == "hello world\n"


# ---------------------------------------------------------------------------
# Schema-load memoization (perf: avoid re-reading the immutable range-ref schema
# once per chunk on large bundles). Behaviour is unchanged; only the second and
# subsequent loads of the same schema path are served from cache.
# ---------------------------------------------------------------------------

def test_load_schema_is_memoized():
    from merger.lenskit.core import range_resolver

    range_resolver._load_schema.cache_clear()

    v2_path = range_resolver._RANGE_REF_V2_SCHEMA_PATH
    first = range_resolver._load_schema(v2_path)
    second = range_resolver._load_schema(v2_path)

    # Same object on the second call -> no re-read / re-parse.
    assert first is second
    assert isinstance(first, dict)
    assert range_resolver._load_schema.cache_info().hits >= 1


def test_load_schema_missing_file_not_negatively_cached(tmp_path):
    from merger.lenskit.core import range_resolver

    range_resolver._load_schema.cache_clear()

    missing = tmp_path / "does-not-exist.schema.json"
    with pytest.raises(RuntimeError, match="Schema file not found"):
        range_resolver._load_schema(missing)

    # The error path must not be memoized: creating the file then loading works.
    missing.write_text(json.dumps({"type": "object"}), encoding="utf-8")
    loaded = range_resolver._load_schema(missing)
    assert loaded == {"type": "object"}
