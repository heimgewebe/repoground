
import json
import tempfile
from pathlib import Path

from merger.repoground.tests._test_constants import make_generator_info
from merger.repoground.core.merge import write_reports_v2, scan_repo, ExtrasConfig

def test_sidecar_contracts_and_dump_index():
    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        hub = tmp_dir / "hub"
        hub.mkdir()

        repo_name = "test-repo-contracts"
        repo_root = hub / repo_name
        repo_root.mkdir()
        (repo_root / "file1.txt").write_text("content", encoding="utf-8")

        summary = scan_repo(repo_root)
        summaries = [summary]
        merges_dir = tmp_dir / "merges"
        merges_dir.mkdir()
        extras = ExtrasConfig(json_sidecar=True)

        # 1. Test DUAL mode (Chunk Index enabled)
        artifacts_dual = write_reports_v2(generator_info=make_generator_info(),
            merges_dir=merges_dir,
            hub=hub,
            repo_summaries=summaries,
            detail="max",
            mode="gesamt",
            max_bytes=0,
            plan_only=False,
            extras=extras,
            output_mode="dual"
        )

        assert artifacts_dual.index_json.exists()
        sidecar_dual = json.loads(artifacts_dual.index_json.read_text(encoding="utf-8"))

        # Verify Contracts
        meta_dual = sidecar_dual["meta"]
        assert "chunk_index_contract" in meta_dual, "chunk_index_contract should be present in dual mode"
        assert meta_dual["chunk_index_contract"]["version"] == "v2"
        assert "dump_index_contract" in meta_dual, "dump_index_contract should be present"
        assert meta_dual["dump_index_contract"]["version"] == "v1"

        # Verify Dump Index
        assert artifacts_dual.dump_index.exists()
        dump_dual = json.loads(artifacts_dual.dump_index.read_text(encoding="utf-8"))
        assert dump_dual["contract"] == "dump-index"
        assert "artifacts" in dump_dual
        assert "chunk_index_jsonl" in dump_dual["artifacts"]

        # Strict hash check
        chunk_sha = dump_dual["artifacts"]["chunk_index_jsonl"]["sha256"]
        assert chunk_sha, "Chunk Index SHA256 missing"
        assert chunk_sha != "ERROR", "Chunk Index SHA256 is ERROR"
        assert len(chunk_sha) == 64, f"Chunk Index SHA256 invalid length: {len(chunk_sha)}"
        # Optionally, check valid hex
        int(chunk_sha, 16)

        # 2. Test ARCHIVE mode (Chunk Index disabled)
        artifacts_archive = write_reports_v2(generator_info=make_generator_info(),
            merges_dir=merges_dir,
            hub=hub,
            repo_summaries=summaries,
            detail="max",
            mode="gesamt",
            max_bytes=0,
            plan_only=False,
            extras=extras,
            output_mode="archive"
        )

        assert artifacts_archive.index_json.exists()
        sidecar_archive = json.loads(artifacts_archive.index_json.read_text(encoding="utf-8"))

        # Verify Contracts
        meta_archive = sidecar_archive["meta"]
        assert "chunk_index_contract" not in meta_archive, "chunk_index_contract should NOT be present in archive mode"
        assert "dump_index_contract" in meta_archive, "dump_index_contract should be present"

        # Verify Dump Index
        assert artifacts_archive.dump_index.exists()
        dump_archive = json.loads(artifacts_archive.dump_index.read_text(encoding="utf-8"))
        # In archive mode, chunk_index path in artifacts map might be None or not created
        # Let's check logic: generate_chunk_artifacts returns None if not retrieval/dual.
        # So chunk_index in artifacts map is None.
        # generate_dump_index iterates items and checks if path and path.exists().
        assert "chunk_index" not in dump_archive["artifacts"], "chunk_index should not be in dump index artifacts if not generated"

        # Verify architecture summary hash
        assert "architecture_summary" in dump_archive["artifacts"]
        arch_sha = dump_archive["artifacts"]["architecture_summary"]["sha256"]
        assert arch_sha, "Architecture Summary SHA256 missing"
        assert arch_sha != "ERROR", "Architecture Summary SHA256 is ERROR"
        assert len(arch_sha) == 64, f"Architecture Summary SHA256 invalid length: {len(arch_sha)}"
        int(arch_sha, 16)

if __name__ == "__main__":
    test_sidecar_contracts_and_dump_index()
