import json
import sqlite3
from pathlib import Path
import tempfile
import contextlib
from io import StringIO

from merger.repoground.tests._test_constants import TEST_CONFIG_SHA256
from merger.repoground.core.merge import write_reports_v2, scan_repo, ExtrasConfig
from merger.repoground.cli import cmd_index, cmd_query
from merger.repoground.retrieval.query_core import build_context_bundle, execute_query

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


def test_retrieval_preserves_historical_source_authority_end_to_end():
    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        hub = tmp_dir / "hub"
        hub.mkdir()
        repo_root = hub / "test-repo"
        repo_root.mkdir()
        (repo_root / "legacytruthmarker.md").write_text(
            "---\nstatus: deprecated\ncanonicality: explanatory\n---\n"
            "# Historical architecture\nLegacy evidence only.\n",
            encoding="utf-8",
        )

        merges_dir = tmp_dir / "merges"
        merges_dir.mkdir()
        summary = scan_repo(repo_root, calculate_md5=True)
        artifacts = write_reports_v2(
            merges_dir=merges_dir,
            hub=hub,
            repo_summaries=[summary],
            detail="max",
            mode="gesamt",
            max_bytes=0,
            plan_only=False,
            output_mode="dual",
            extras=ExtrasConfig(json_sidecar=True),
            generator_info={
                "name": "test-stack",
                "platform": "test",
                "config_sha256": TEST_CONFIG_SHA256,
            },
        )

        assert artifacts.chunk_index is not None
        chunk_rows = [
            json.loads(line)
            for line in artifacts.chunk_index.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        source_rows = [
            row for row in chunk_rows
            if row.get("source_file", "").endswith("legacytruthmarker.md")
        ]
        assert source_rows
        assert all(
            row["source_authority"]["classification"] == "historical_only"
            for row in source_rows
        )

        index_path = merges_dir / "test.index.sqlite"

        class IndexArgs:
            dump = str(artifacts.dump_index)
            chunk_index = str(artifacts.chunk_index)
            out = str(index_path)
            rebuild = True
            verify = False

        assert cmd_index.run_index(IndexArgs()) == 0

        query = execute_query(index_path, "legacytruthmarker", k=5)
        assert query["count"] >= 1
        hit = next(
            item for item in query["results"]
            if item["path"].endswith("legacytruthmarker.md")
        )
        assert hit["source_authority"]["classification"] == "historical_only"
        assert hit["source_authority"]["establishes_current_state"] is False

        with sqlite3.connect(index_path) as conn:
            context = build_context_bundle(
                "legacytruthmarker",
                [hit],
                {},
                conn,
            )
        assert context["hits"][0]["source_authority"]["classification"] == "historical_only"
        assert (
            context["hits"][0]["epistemics"]["current_state_authority"]
            == "historical_only"
        )
