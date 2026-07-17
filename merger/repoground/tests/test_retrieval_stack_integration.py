import json
from pathlib import Path
import tempfile
import contextlib
from io import StringIO

from merger.repoground.tests._test_constants import TEST_CONFIG_SHA256
from merger.repoground.core.merge import write_reports_v2, scan_repo, ExtrasConfig
from merger.repoground.cli import cmd_index, cmd_query

def test_retrieval_stack_integration():
    """
    Integration test proving the full retrieval stack:
    Scan -> Merge -> Index -> Query (via path token)
    """
    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        hub = tmp_dir / "hub"
        hub.mkdir()

        repo_name = "test-repo"
        repo_root = hub / repo_name
        repo_root.mkdir()

        # Create some files
        (repo_root / "src").mkdir()
        (repo_root / "src" / "main.py").write_text("def main():\n    print('Hello Index')\n", encoding="utf-8")
        (repo_root / "README.md").write_text("# Test Repo\nThis is a test.\n", encoding="utf-8")

        # 1. Generate Artifacts (Dump + Chunk + Sidecar)
        merges_dir = tmp_dir / "merges"
        merges_dir.mkdir()

        summary = scan_repo(repo_root, calculate_md5=True)
        extras = ExtrasConfig(json_sidecar=True)

        artifacts = write_reports_v2(
            merges_dir=merges_dir,
            hub=hub,
            repo_summaries=[summary],
            detail="max",
            mode="gesamt",
            max_bytes=0,
            plan_only=False,
            output_mode="dual",
            extras=extras,
            generator_info={"name": "test-stack", "platform": "test", "config_sha256": TEST_CONFIG_SHA256}
        )

        dump_path = artifacts.dump_index
        chunk_path = artifacts.chunk_index
        index_path = merges_dir / "test.index.sqlite"

        assert dump_path and dump_path.exists()
        assert chunk_path and chunk_path.exists()

        # 2. Build Index (CLI simulation)
        class IndexArgs:
            dump = str(dump_path)
            chunk_index = str(chunk_path)
            out = str(index_path)
            rebuild = True
            verify = False

        ret = cmd_index.run_index(IndexArgs())
        assert ret == 0, "Index build failed"
        assert index_path.exists()

        # 3. Run Query (Sanity) - search for "main" (path token), robust without content indexing
        class QueryArgs:
            index = str(index_path)
            q = "main"
            k = 5
            repo = None
            path = None
            ext = None
            layer = None
            emit = "json"

        # Capture stdout using contextlib
        capture = StringIO()
        with contextlib.redirect_stdout(capture):
            ret = cmd_query.run_query(QueryArgs())

        assert ret == 0

        raw_output = capture.getvalue()
        assert raw_output.lstrip().startswith("{"), f"Expected JSON output, got: {raw_output[:50]}"
        output = json.loads(raw_output)

        assert output["count"] >= 1
        assert output["results"][0]["path"].endswith("main.py")
