import sys
import os
import subprocess
import json
import hashlib
from pathlib import Path

# Deterministically test the degraded Pythonista/iPad-like runtime where jsonschema is missing.
# We run these tests in a separate subprocess to avoid polluting the global sys.modules
# state and pytest's cache.

def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]

def get_test_env() -> dict:
    env = os.environ.copy()
    repo_root = str(get_repo_root())
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = repo_root
    return env

def _utf8_bytes(text: str) -> bytes:
    return text.encode("utf-8")

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _write_bytes(path: Path, data: bytes) -> None:
    path.write_bytes(data)

def _path_literal(path: Path) -> str:
    return json.dumps(str(path))

def test_output_health_degraded_without_jsonschema(tmp_path):
    """
    Test A: Verify that output health is degraded (warn) when jsonschema is missing.
    Verify that checks.range_ref_resolution uses skipped_unavailable, and dependencies
    correctly reflect availability=False and validation_degraded effect.
    """
    primary_manifest = tmp_path / "primary.manifest.json"
    primary_manifest_bytes = b"{}"
    _write_bytes(primary_manifest, primary_manifest_bytes)
    
    canonical_md = tmp_path / "canonical.md"
    canonical_md_bytes = b"Hello World"
    _write_bytes(canonical_md, canonical_md_bytes)
    expected_md_sha = _sha256(canonical_md_bytes)
    
    chunk_index = tmp_path / "chunks.jsonl"
    chunk = {
        "chunk_id": "chunk_1",
        "canonical_range": {
            "artifact_role": "canonical_md",
            "repo_id": "testrepo",
            "file_path": "canonical.md",
            "start_byte": 0,
            "end_byte": len(canonical_md_bytes),
            "start_line": 1,
            "end_line": 1,
            "content_sha256": expected_md_sha,
        }
    }
    chunk_bytes = _utf8_bytes(json.dumps(chunk) + "\n")
    _write_bytes(chunk_index, chunk_bytes)
    expected_chunk_sha = _sha256(chunk_bytes)

    primary_manifest_lit = _path_literal(primary_manifest)
    canonical_md_lit = _path_literal(canonical_md)
    chunk_index_lit = _path_literal(chunk_index)
    
    code = f"""
import sys
sys.modules['jsonschema'] = None

from pathlib import Path
from merger.lenskit.core.output_health import compute_output_health

report = compute_output_health(
    run_id="test-run",
    stem="test-stem",
    primary_manifest_path=Path({primary_manifest_lit}),
    canonical_md_path=Path({canonical_md_lit}),
    chunk_index_path=Path({chunk_index_lit}),
    dump_index_path=Path({primary_manifest_lit}),
    sqlite_index_path=None,
    redact_secrets=False,
    canonical_md_required=True,
    chunk_index_required=True,
    sqlite_index_required=False,
    expected_canonical_md_sha256="{expected_md_sha}",
    expected_chunk_index_sha256="{expected_chunk_sha}"
)

assert report["verdict"] == "warn", f"Expected verdict to be 'warn', got {{report['verdict']}}"
assert not report["errors"], f"Expected no errors, got {{report['errors']}}"
assert report["warnings"], "Expected warning(s) about jsonschema missing"
assert any("jsonschema unavailable" in w for w in report["warnings"]), f"Expected jsonschema warning, got {{report['warnings']}}"

deps = report["dependencies"]
assert deps["jsonschema"]["available"] is False
assert deps["jsonschema"]["effect"] == "validation_degraded"

checks = report["checks"]
rr = checks["range_ref_resolution"]
assert rr["status"] == "environment_error"
assert rr["validation"]["mode"] == "skipped_unavailable"
assert rr["validation"]["reason"] == "dependency_unavailable"

print("Success")
"""
    repo_root = get_repo_root()
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=get_test_env(), cwd=repo_root)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "Success" in result.stdout

def test_post_emit_health_degraded_without_jsonschema(tmp_path):
    """
    Test B: Verify that post-emit health is degraded (warn) when jsonschema is missing.
    Verify that checks like manifest_schema_valid, range_ref_resolution, and claim_evidence_map_schema_valid
    use skipped_unavailable and status=warn (no errors).
    """
    manifest_path = tmp_path / "x.bundle.manifest.json"
    
    canonical_md = tmp_path / "x.md"
    canonical_md_bytes = b"Hello World"
    _write_bytes(canonical_md, canonical_md_bytes)
    expected_md_sha = _sha256(canonical_md_bytes)
    
    pack_md = tmp_path / "x.pack.md"
    pack_text = (
        "<!-- ARTIFACT:agent_reading_pack VERSION:v1.1 "
        "AUTHORITY:navigation_index CANONICALITY:derived -->\n"
        "## REQUIRED_READING_BY_TASK\n"
        "## WHEN_CANONICAL_MD_ONLY_IS_INSUFFICIENT\n"
        "## SIDECAR_USAGE_RULES\n"
        "## ANSWER_COMPLIANCE_CHECKLIST\n"
        "## DO_NOT_CLAIM\n"
        "- `change_impact` — relation or path proximity alone does not prove change impact.\n"
    )
    pack_bytes = _utf8_bytes(pack_text)
    _write_bytes(pack_md, pack_bytes)
    expected_pack_sha = _sha256(pack_bytes)
    
    chunk_index = tmp_path / "x.chunks.jsonl"
    chunk = {
        "chunk_id": "chunk_1",
        "canonical_range": {
            "artifact_role": "canonical_md",
            "repo_id": "testrepo",
            "file_path": "x.md",
            "start_byte": 0,
            "end_byte": len(canonical_md_bytes),
            "start_line": 1,
            "end_line": 1,
            "content_sha256": expected_md_sha,
        }
    }
    chunk_bytes = _utf8_bytes(json.dumps(chunk) + "\n")
    _write_bytes(chunk_index, chunk_bytes)
    expected_chunk_sha = _sha256(chunk_bytes)
    
    # Let's also create an optional claim_evidence_map_json to test when it is present
    cem_json = tmp_path / "x.cem.json"
    cem_bytes = b"{}"
    _write_bytes(cem_json, cem_bytes)
    expected_cem_sha = _sha256(cem_bytes)

    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-xyz",
        "created_at": "2026-06-02T00:00:00Z",
        "generator": {
            "name": "rlens",
            "version": "dev",
            "config_sha256": "a" * 64,
            "runtime": {
                "module": "merger.lenskit.core.merge",
                "python_version": "3.11.0",
            }
        },
        "artifacts": [
            {"role": "canonical_md", "path": "x.md", "sha256": expected_md_sha, "bytes": len(canonical_md_bytes)},
            {"role": "agent_reading_pack", "path": "x.pack.md", "sha256": expected_pack_sha, "bytes": len(pack_bytes)},
            {"role": "chunk_index_jsonl", "path": "x.chunks.jsonl", "sha256": expected_chunk_sha, "bytes": len(chunk_bytes)},
            {"role": "claim_evidence_map_json", "path": "x.cem.json", "sha256": expected_cem_sha, "bytes": len(cem_bytes)},
        ],
        "links": {},
        "capabilities": {"redaction": False},
    }
    manifest_bytes = _utf8_bytes(json.dumps(manifest, indent=2))
    _write_bytes(manifest_path, manifest_bytes)

    manifest_path_lit = _path_literal(manifest_path)
    
    code = f"""
import sys
sys.modules['jsonschema'] = None

from pathlib import Path
from merger.lenskit.core.post_emit_health import compute_post_emit_health

report = compute_post_emit_health(
    {manifest_path_lit},
    agent_pack_required=True,
    run_id="test-post-run"
)

assert report["status"] == "warn", f"Expected status to be 'warn', got {{report['status']}}"
assert not report["errors"], f"Expected no errors, got {{report['errors']}}"
assert report["warnings"], "Expected warning(s) about jsonschema missing"
assert any("schema validation skipped" in w for w in report["warnings"]), f"Expected schema warning, got {{report['warnings']}}"

deps = report["dependencies"]
assert deps["jsonschema"]["available"] is False
assert deps["jsonschema"]["effect"] == "validation_degraded"

checks = report["checks"]
by_name = {{c["name"]: c for c in checks}}

# manifest_schema_valid check when jsonschema is None
assert by_name["manifest_schema_valid"]["status"] == "skipped"
assert by_name["manifest_schema_valid"]["validation"]["mode"] == "skipped_unavailable"
assert by_name["manifest_schema_valid"]["validation"]["reason"] == "dependency_unavailable"

# range_ref_resolution check when jsonschema is None
assert by_name["range_ref_resolution"]["status"] == "skipped"
assert by_name["range_ref_resolution"]["validation"]["mode"] == "skipped_unavailable"
assert by_name["range_ref_resolution"]["validation"]["reason"] == "dependency_unavailable"

# claim_evidence_map_schema_valid check when claim map is present but jsonschema is None
assert by_name["claim_evidence_map_schema_valid"]["status"] == "skipped"
assert by_name["claim_evidence_map_schema_valid"]["validation"]["mode"] == "skipped_unavailable"
assert by_name["claim_evidence_map_schema_valid"]["validation"]["reason"] == "dependency_unavailable"

print("Success")
"""
    repo_root = get_repo_root()
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=get_test_env(), cwd=repo_root)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "Success" in result.stdout

def test_bundle_surface_validate_is_unaffected_by_jsonschema(tmp_path):
    """
    Test C: Verify that bundle surface validation is unaffected by jsonschema absence,
    because it only performs structural prechecks (coherence/surface checks).
    Verify that validation modes remain 'structural_precheck' and do not change or claim
    to perform full schema validation.
    """
    manifest_path = tmp_path / "x.bundle.manifest.json"
    
    canonical_md = tmp_path / "x.md"
    canonical_md_bytes = b"Hello World"
    _write_bytes(canonical_md, canonical_md_bytes)
    expected_md_sha = _sha256(canonical_md_bytes)
    
    pack_md = tmp_path / "x.pack.md"
    pack_text = (
        "<!-- ARTIFACT:agent_reading_pack VERSION:v1.1 "
        "AUTHORITY:navigation_index CANONICALITY:derived -->\n"
        "## REQUIRED_READING_BY_TASK\n"
        "## WHEN_CANONICAL_MD_ONLY_IS_INSUFFICIENT\n"
        "## SIDECAR_USAGE_RULES\n"
        "## ANSWER_COMPLIANCE_CHECKLIST\n"
        "## DO_NOT_CLAIM\n"
        "- `change_impact` — relation or path proximity alone does not prove change impact.\n"
        "## CLAIM_EVIDENCE_MAP_SUMMARY\n"
        "- artifact: `x.claim_evidence_map.json`\n"
        "- claims: 0\n"
    )
    pack_bytes = _utf8_bytes(pack_text)
    _write_bytes(pack_md, pack_bytes)
    expected_pack_sha = _sha256(pack_bytes)
    
    cem_json = tmp_path / "x.cem.json"
    cem_bytes = b"{}"
    _write_bytes(cem_json, cem_bytes)
    expected_cem_sha = _sha256(cem_bytes)

    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-xyz",
        "created_at": "2026-06-02T00:00:00Z",
        "generator": {
            "name": "rlens",
            "version": "dev",
            "config_sha256": "a" * 64,
            "runtime": {
                "module": "merger.lenskit.core.merge",
                "python_version": "3.11.0",
            }
        },
        "artifacts": [
            {"role": "canonical_md", "path": "x.md", "sha256": expected_md_sha, "bytes": len(canonical_md_bytes)},
            {"role": "agent_reading_pack", "path": "x.pack.md", "sha256": expected_pack_sha, "bytes": len(pack_bytes)},
            {"role": "claim_evidence_map_json", "path": "x.cem.json", "sha256": expected_cem_sha, "bytes": len(cem_bytes)},
        ],
        "links": {},
        "capabilities": {"redaction": False},
    }
    manifest_bytes = _utf8_bytes(json.dumps(manifest, indent=2))
    _write_bytes(manifest_path, manifest_bytes)
    
    # We write a mock post_emit_health sidecar with status "pass"
    post_health_sidecar = tmp_path / "x.bundle_health.post.json"
    post_health_bytes = _utf8_bytes(json.dumps({
        "kind": "lenskit.post_emit_health",
        "version": "1.0",
        "status": "pass"
    }))
    _write_bytes(post_health_sidecar, post_health_bytes)

    manifest_path_lit = _path_literal(manifest_path)

    code = f"""
import sys
sys.modules['jsonschema'] = None

from pathlib import Path
from merger.lenskit.core.bundle_surface_validate import validate_bundle_surface

report = validate_bundle_surface(
    Path({manifest_path_lit}),
    require_claim_evidence_map=True,
    run_id="test-surface-run"
)

if report["status"] != "pass":
    import json
    print(f"FAILED REPORT: {{json.dumps(report, indent=2)}}")
assert report["status"] == "pass", f"Expected status to be 'pass', got {{report['status']}}"

# Verify that all validation modes are 'structural_precheck' and engine is 'bundle_surface_validate'
for check in report["checks"]:
    val = check.get("validation")
    if val:
        assert val["mode"] == "structural_precheck", f"Expected mode 'structural_precheck', got {{val['mode']}} in {{check['name']}}"
        assert val["engine"] == "bundle_surface_validate", f"Expected engine 'bundle_surface_validate', got {{val['engine']}} in {{check['name']}}"

print("Success")
"""
    repo_root = get_repo_root()
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=get_test_env(), cwd=repo_root)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "Success" in result.stdout
