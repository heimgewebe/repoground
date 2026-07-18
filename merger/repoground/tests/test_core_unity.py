import sys
from pathlib import Path
import pytest
import os
import json

# Ensure we can import from root
# We assume the test runner runs from root, but we make sure.
# merger/repoground/tests/test_core_unity.py -> ../../../..
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

def test_core_version_exists():
    import merger.repoground.core
    assert hasattr(merger.repoground.core, "__core_version__")
    assert isinstance(merger.repoground.core.__core_version__, str)
    # We set it to 2.4.0
    assert merger.repoground.core.__core_version__ == "2.4.0"

def test_repo_ground_imports_correct_core():
    # Wrap in try-except to avoid CI failures if Pythonista dependencies (ui, etc.) are missing
    try:
        from merger.repoground.frontends.pythonista import repo_ground
    except ImportError as e:
        pytest.skip(f"Skipping pythonista import check: {e}")
    except Exception as e:
        # Some other initialization error (e.g. ui module missing)
        pytest.skip(f"Skipping pythonista import check: {e}")

    # Check what 'scan_repo' it uses
    import merger.repoground.core.merge as core_merge

    assert repo_ground.scan_repo is core_merge.scan_repo
    assert repo_ground.write_reports_v2 is core_merge.write_reports_v2

    assert "merger.repoground.core" in sys.modules

def test_service_imports_correct_core():
    from merger.repoground.service import app
    import merger.repoground.core.merge as core_merge

    # Check imports in app.py
    assert app.prescan_repo is core_merge.prescan_repo

    from merger.repoground.service import jobstore
    assert jobstore.get_merges_dir is core_merge.get_merges_dir

def test_generator_info_version(tmp_path):
    from merger.repoground.tests._test_constants import TEST_CONFIG_SHA256
    from merger.repoground.core.merge import write_reports_v2, AGENT_CONTRACT_NAME
    from merger.repoground.core import __core_version__

    # Create dummy repo content
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "file.txt").write_text("content", encoding="utf-8")

    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()

    # Mock summary
    from merger.repoground.core.merge import scan_repo
    summary = scan_repo(repo_dir)

    # Temporarily unset REPOGROUND_VERSION env var if set
    old_env = os.environ.get("REPOGROUND_VERSION")
    if old_env is not None:
        del os.environ["REPOGROUND_VERSION"]

    # Need to enable json_sidecar in extras
    from merger.repoground.core.merge import ExtrasConfig
    extras = ExtrasConfig(json_sidecar=True)

    try:
        write_reports_v2(
            merges_dir=merges_dir,
            hub=tmp_path,
            repo_summaries=[summary],
            detail="max",
            mode="pro-repo",
            max_bytes=1000,
            plan_only=False,
            output_mode="dual", # generates json sidecar
            extras=extras,
            generator_info={"name": "test", "version": __core_version__, "config_sha256": TEST_CONFIG_SHA256}
        )

        # Find sidecar
        # In single repo mode, filename structure is deterministic
        # but let's just find *.json excluding dump_index
        json_files = [p for p in merges_dir.glob("*.json") if "dump_index" not in p.name]

        found = False
        for p in json_files:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("meta", {}).get("contract") == AGENT_CONTRACT_NAME:
                found = True
                # Verify version
                gen_ver = data["meta"]["generator"]["version"]
                assert gen_ver == __core_version__
                break

        if not found:
            pytest.fail("No agent contract JSON found")

    finally:
        if old_env is not None:
            os.environ["REPOGROUND_VERSION"] = old_env
