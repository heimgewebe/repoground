import json
import tempfile
import pytest
import subprocess
import sys
import hashlib
from pathlib import Path
from merger.repoground.core.extractor import generate_review_bundle

# Path to the verifier script
VERIFIER_SCRIPT = Path(__file__).parents[1] / "cli" / "pr_schau_verify.py"

def test_pr_schau_verify_tool():
    """
    Test that the pr-schau-verify CLI tool correctly validates a generated bundle.
    """
    if not VERIFIER_SCRIPT.exists():
        pytest.skip(f"Verifier script not found at {VERIFIER_SCRIPT}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        hub_dir = tmp_path / "hub"
        hub_dir.mkdir()

        # Create dummy repos
        old_repo = tmp_path / "old_repo"
        old_repo.mkdir()
        (old_repo / "README.md").write_text("Old Content")

        new_repo = tmp_path / "new_repo"
        new_repo.mkdir()
        (new_repo / "README.md").write_text("New Content")
        (new_repo / "extra.md").write_text("Extra Content")

        repo_name = "verify-test-repo"

        # 1. Generate a valid bundle
        generate_review_bundle(old_repo, new_repo, repo_name, hub_dir)

        pr_schau_dir = hub_dir / ".repoground" / "pr-schau" / repo_name
        assert pr_schau_dir.exists()
        bundle_dir = list(pr_schau_dir.iterdir())[0]
        bundle_json = bundle_dir / "bundle.json"

        # 2. Run Verifier (Basic)
        cmd_basic = [sys.executable, str(VERIFIER_SCRIPT), str(bundle_json), "--level", "basic"]
        result_basic = subprocess.run(cmd_basic, capture_output=True, text=True)
        assert result_basic.returncode == 0, "Basic verification failed"

        # 3. Run Verifier (Full)
        cmd_full = [sys.executable, str(VERIFIER_SCRIPT), str(bundle_json), "--level", "full"]
        result_full = subprocess.run(cmd_full, capture_output=True, text=True)
        assert result_full.returncode == 0, "Full verification failed"

        # 4. Tamper with the bundle (invalidate hash)
        review_md = bundle_dir / "review.md"
        original_content = review_md.read_text(encoding="utf-8")
        review_md.write_text(original_content + "\nTAMPERED", encoding="utf-8")

        cmd_tamper = [sys.executable, str(VERIFIER_SCRIPT), str(bundle_json), "--level", "full"]
        result_tamper = subprocess.run(cmd_tamper, capture_output=True, text=True)
        assert result_tamper.returncode != 0, "Verifier should fail on tampered content"
        assert "SHA256 mismatch" in result_tamper.stderr

        # 5. Tamper with truncation (add forbidden text)
        # Restore content first to fix hash mismatch (though hash check runs before guard, so order matters)
        # We'll fix the hash in bundle.json to match the new tampered content, but include the forbidden string

        # Need to preserve zones or next checks will fail, but truncation check happens before zone check
        # But wait, verifier logic order:
        # 1. Integrity (primary in parts)
        # 2. Integrity (parts map to artifacts)
        # 3. SHA256 Verification
        # 4. Guard: No-Truncate
        # 5. Zone Verification

        # So if we fail SHA, we stop.
        # We must update SHA to pass step 3, so we reach step 4.

        forbidden_text = "This Content truncated at 100 chars."
        review_md.write_text(forbidden_text, encoding="utf-8")

        # Update hash in json to pass hash check
        new_sha = hashlib.sha256(review_md.read_bytes()).hexdigest()

        with open(bundle_json, "r") as f:
            data = json.load(f)

        for art in data["artifacts"]:
            if art["basename"] == "review.md":
                art["sha256"] = new_sha
                # Also update bytes to avoid mismatch error in step 6 (though we expect failure in step 4)
                art["bytes"] = len(forbidden_text.encode("utf-8"))

        # Also need to update emitted_bytes to match file size
        data["completeness"]["emitted_bytes"] = len(forbidden_text.encode("utf-8"))
        # And expected_bytes to avoid step 6 error if we reached it
        data["completeness"]["expected_bytes"] = len(forbidden_text.encode("utf-8"))

        with open(bundle_json, "w") as f:
            json.dump(data, f)

        cmd_guard = [sys.executable, str(VERIFIER_SCRIPT), str(bundle_json), "--level", "full"]
        result_guard = subprocess.run(cmd_guard, capture_output=True, text=True)

        assert result_guard.returncode != 0, "Verifier should fail on forbidden truncation text"
        assert "Found truncation marker" in result_guard.stderr

        # 6. Test missing zones
        # Fix the guard violation first
        clean_text = "Clean content without truncation."
        review_md.write_text(clean_text, encoding="utf-8")
        # Re-calc hash for clean content
        clean_sha = hashlib.sha256(review_md.read_bytes()).hexdigest()

        with open(bundle_json, "r") as f:
            data = json.load(f)
        for art in data["artifacts"]:
            if art["basename"] == "review.md":
                art["sha256"] = clean_sha
                art["bytes"] = len(clean_text.encode("utf-8"))

        data["completeness"]["emitted_bytes"] = len(clean_text.encode("utf-8"))
        data["completeness"]["expected_bytes"] = len(clean_text.encode("utf-8"))

        with open(bundle_json, "w") as f:
            json.dump(data, f)

        # The content lacks zone markers now (generator added them, but we overwrote with "Clean content...")
        cmd_zones = [sys.executable, str(VERIFIER_SCRIPT), str(bundle_json), "--level", "full"]
        result_zones = subprocess.run(cmd_zones, capture_output=True, text=True)

        assert result_zones.returncode != 0, "Verifier should fail on missing zones"
        assert ("missing mandatory 'summary' zone" in result_zones.stderr) or ("missing mandatory" in result_zones.stderr)

if __name__ == "__main__":
    pytest.main([__file__])
