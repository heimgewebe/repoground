import json
import hashlib
from unittest.mock import patch

import pytest

from merger.lenskit.cli.pr_schau_verify import (
    load_schema,
    _compute_sha256,
    _fail,
    _pass,
)

def test_compute_sha256(tmp_path):
    """Verify _compute_sha256 correctly computes SHA256 of a file."""
    content = b"hello world"
    file_path = tmp_path / "test.txt"
    file_path.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()
    assert _compute_sha256(file_path) == expected_hash

def test_fail(capsys):
    """Verify _fail prints to stderr and exits with code 1."""
    with pytest.raises(SystemExit) as excinfo:
        _fail("test error")

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "❌ FAIL: test error" in captured.err

def test_pass(capsys):
    """Verify _pass prints to stdout."""
    _pass("test success")
    captured = capsys.readouterr()
    assert "✅ PASS: test success" in captured.out

def test_load_schema_success(tmp_path):
    """Verify load_schema returns the correct dictionary on success."""
    schema_content = {"type": "object", "properties": {"foo": {"type": "string"}}}
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema_content), encoding="utf-8")

    # We patch candidates inside load_schema by patching SCHEMA_PATH which is used to initialize it
    with patch("merger.lenskit.cli.pr_schau_verify.SCHEMA_PATH", schema_file):
        assert load_schema() == schema_content

def test_load_schema_missing_file(tmp_path, capsys):
    """Verify load_schema calls _fail (exits) and prints error when the schema file is missing."""
    missing_file = tmp_path / "missing.json"

    with patch("merger.lenskit.cli.pr_schau_verify.SCHEMA_PATH", missing_file):
        with pytest.raises(SystemExit) as excinfo:
            load_schema()
        assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Schema not found" in captured.err

def test_load_schema_invalid_json(tmp_path, capsys):
    """Verify load_schema calls _fail (exits) and prints error when the schema file contains invalid JSON."""
    invalid_file = tmp_path / "invalid.json"
    invalid_file.write_text("not json", encoding="utf-8")

    with patch("merger.lenskit.cli.pr_schau_verify.SCHEMA_PATH", invalid_file):
        with pytest.raises(SystemExit) as excinfo:
            load_schema()
        assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Failed to load schema" in captured.err

def test_verify_full_zone_dual_read(tmp_path, capsys):
    """Verify that verify_full accepts both quoted and unquoted zone markers."""
    from merger.lenskit.cli.pr_schau_verify import verify_full

    # 1. Setup a valid bundle data
    bundle_data = {
        "completeness": {
            "parts": ["review.md"],
            "primary_part": "review.md",
            "is_complete": True,
            "policy": "split",
            "expected_bytes": 100,
            "emitted_bytes": 100
        },
        "artifacts": [
            {"role": "canonical_md", "basename": "review.md", "sha256": "dummy"}
        ]
    }

    # Helper to run verification with specific content
    def check_content(content):
        review_md = tmp_path / "review.md"
        review_md.write_text(content, encoding="utf-8")

        # Update emitted_bytes to match actual file size
        bundle_data["completeness"]["emitted_bytes"] = len(content.encode("utf-8"))
        bundle_data["completeness"]["expected_bytes"] = bundle_data["completeness"]["emitted_bytes"]

        # Patch SHA256 check to always pass for simplicity
        with patch("merger.lenskit.cli.pr_schau_verify._compute_sha256", return_value="dummy"):
            verify_full(tmp_path / "bundle.json", bundle_data)

    # A: Standard Quoted
    check_content('<!-- zone:begin type="summary" -->\n<!-- zone:begin type="files_manifest" -->')
    # B: Legacy Unquoted
    check_content('<!-- zone:begin type=summary -->\n<!-- zone:begin type=files_manifest -->')
    # C: Mixed and extra whitespace
    check_content('<!--  zone:begin  type=summary  -->\n<!-- zone:begin type="files_manifest" id="x" -->')

    # D: Missing summary should fail
    with pytest.raises(SystemExit):
        check_content('<!-- zone:begin type="files_manifest" -->')

def test_run_verify_invalid_level(capsys):
    """Verify run_verify returns exit code 2 for invalid level parameter."""
    from merger.lenskit.cli.pr_schau_verify import run_verify

    result = run_verify("/nonexistent/bundle.json", level="banana")

    assert result == 2
    captured = capsys.readouterr()
    assert "Invalid verification level: 'banana'" in captured.err
    assert "Expected one of: basic, full" in captured.err

def test_main_verify_dispatches_to_run_verify(tmp_path, monkeypatch):
    """Verify that lenskit main() correctly dispatches verify command to run_verify."""
    from merger.lenskit.cli.main import main as lenskit_main
    from merger.lenskit.cli import pr_schau_verify

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()

    calls = {}

    def fake_run_verify(bundle, level):
        calls["bundle"] = bundle
        calls["level"] = level
        return 23

    monkeypatch.setattr(pr_schau_verify, "run_verify", fake_run_verify)

    rc = lenskit_main(["verify", str(bundle_dir), "--level", "basic"])

    assert rc == 23
    assert calls == {"bundle": str(bundle_dir), "level": "basic"}




