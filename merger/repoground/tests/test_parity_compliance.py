from merger.repoground.tests._test_constants import TEST_CONFIG_SHA256
import json

# Canonical import style (relying on pytest/PYTHONPATH to find the module)
from merger.repoground.core.merge import scan_repo, write_reports_v2, ExtrasConfig

def test_scan_repo_hidden_files_behavior(tmp_path):
    # Setup
    repo_root = tmp_path / "test_repo"
    repo_root.mkdir()
    (repo_root / "visible.txt").write_text("visible", encoding="utf-8")
    (repo_root / ".hidden_dir").mkdir()
    (repo_root / ".hidden_dir" / "hidden_file.txt").write_text("hidden", encoding="utf-8")
    (repo_root / "visible_dir").mkdir()
    (repo_root / "visible_dir" / ".dotfile").write_text("dotfile", encoding="utf-8")
    (repo_root / ".env.example").write_text("safe_env", encoding="utf-8")
    (repo_root / ".env.secret").write_text("secret_env", encoding="utf-8")

    # Case 1: include_hidden=True (default/repolens)
    summary_inc = scan_repo(repo_root, include_hidden=True)
    files_inc = [f.rel_path.as_posix() for f in summary_inc["files"]]
    assert "visible.txt" in files_inc
    assert ".hidden_dir/hidden_file.txt" in files_inc
    assert "visible_dir/.dotfile" in files_inc
    assert ".env.example" in files_inc
    # .env.secret should still be skipped by standard filters (startswith .env)
    # BUT wait, standard filters only skip .env* IF NOT in whitelist.
    # .env.secret is NOT in whitelist, so it should be skipped regardless of include_hidden.
    assert ".env.secret" not in files_inc

    # Case 2: include_hidden=False (strict)
    summary_exc = scan_repo(repo_root, include_hidden=False)
    files_exc = [f.rel_path.as_posix() for f in summary_exc["files"]]
    assert "visible.txt" in files_exc
    assert ".hidden_dir/hidden_file.txt" not in files_exc
    assert "visible_dir/.dotfile" not in files_exc
    # .env.example IS whitelisted, so it should be present even if include_hidden=False
    assert ".env.example" in files_exc
    assert ".env.secret" not in files_exc

def test_write_reports_parity_features(tmp_path):
    # Setup
    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()
    hub = tmp_path

    # Setup dummy repo
    repo_name = "repo"
    repo_root = tmp_path / repo_name
    repo_root.mkdir()

    # Create content file
    f = repo_root / "test.py"
    f.write_text("def hello(): pass\n", encoding="utf-8")

    # Use scan_repo to generate valid summary instead of manual FileInfo construction
    # This ensures FileInfo objects are complete and valid according to current codebase logic
    summary = scan_repo(repo_root, calculate_md5=False, include_hidden=True)

    gen_info = {"name": "parity_test", "version": "1.0", "platform": "test"}

    # Run with dual mode
    gen_info["config_sha256"] = TEST_CONFIG_SHA256
    write_reports_v2(
        merges_dir,
        hub,
        [summary],
        detail="max",
        mode="gesamt",
        max_bytes=0,
        plan_only=False,
        output_mode="dual", # Should generate architecture + chunk index
        generator_info=gen_info,
        extras=ExtrasConfig(json_sidecar=True)
    )

    # Verify Architecture Summary
    arch_files = list(merges_dir.glob("*_architecture.md"))
    assert len(arch_files) == 1, "Architecture summary not generated"

    # Verify Chunk Index Semantics
    chunk_files = list(merges_dir.glob("*.chunk_index.jsonl"))
    assert len(chunk_files) == 1, "Chunk index not generated"
    chunk_lines = chunk_files[0].read_text(encoding="utf-8").splitlines()
    assert len(chunk_lines) > 0
    chunk = json.loads(chunk_lines[0])

    # Check for semantic fields
    assert "section" in chunk
    assert "layer" in chunk
    assert "concepts" in chunk

    # Verify JSON Sidecar Metadata
    # Restrict candidate pool to likely sidecars
    json_files = list(merges_dir.glob("*.json"))
    sidecar = None
    for p in json_files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            # Strong signal check
            if data.get("meta", {}).get("contract") == "repolens-agent":
                sidecar = data
                break
        except Exception:
            continue

    assert sidecar is not None, "JSON sidecar not found"
    meta = sidecar["meta"]
    assert "generator" in meta
    assert meta["generator"]["name"] == "parity_test"
    assert "features" in meta
    assert "semantic_chunk_fields" in meta["features"]
    assert "architecture_summary" in meta["features"]
