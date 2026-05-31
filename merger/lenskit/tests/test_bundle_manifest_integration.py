import hashlib
import json
import re
import sqlite3
from pathlib import Path

import jsonschema
import pytest

from merger.lenskit.core.constants import ArtifactRole
from merger.lenskit.core.merge import FileInfo, write_reports_v2
from merger.lenskit.core.output_health import compute_output_health
from merger.lenskit.tests._test_constants import make_generator_info


_CONTRACTS_DIR = Path(__file__).parent.parent / "contracts"
_BUNDLE_MANIFEST_SCHEMA_PATH = (
    _CONTRACTS_DIR / "bundle-manifest.v1.schema.json"
)
_OUTPUT_HEALTH_SCHEMA_PATH = (
    _CONTRACTS_DIR / "output-health.v1.schema.json"
)
_CITATION_MAP_SCHEMA_PATH = _CONTRACTS_DIR / "citation-map.v1.schema.json"
_SHA256_HEX_LENGTH = 64


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _artifact_by_role(data: dict, role: str) -> dict | None:
    return next((e for e in data["artifacts"] if e["role"] == role), None)

class MockExtras:
    json_sidecar = True
    skip_md = False
    format = "markdown"
    augment_sidecar = False
    health = False
    organism_index = False
    fleet_panorama = False
    delta_reports = False
    heatmap = False

    @classmethod
    def none(cls):
        return cls()

def test_generate_bundle_manifest_integration(tmp_path):
    # Setup dummy source file
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    f1 = src_dir / "file1.txt"
    f1.write_text("Hello World", encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    hub_dir = tmp_path / "hub"
    hub_dir.mkdir()

    fi1 = FileInfo(
        root_label="test-repo",
        abs_path=f1,
        rel_path=Path("file1.txt"),
        size=11,
        is_text=True,
        md5="test",
        category="docs",
        tags=[],
        ext=".txt",
        skipped=False,
    )

    repo_summary = {
        "name": "test-repo",
        "path": str(src_dir),
        "root": src_dir,
        "files": [fi1],
        "source_files": [fi1]
    }

    artifacts = write_reports_v2(
        merges_dir=out_dir,
        hub=hub_dir,
        repo_summaries=[repo_summary],
        detail="test",
        mode="gesamt",
        max_bytes=1000,
        plan_only=False,
        code_only=False,
        extras=MockExtras(),
        output_mode="dual",
        generator_info=make_generator_info()
    )

    # bundle_manifest should exist
    assert artifacts.bundle_manifest is not None
    assert artifacts.bundle_manifest.exists()

    data = json.loads(artifacts.bundle_manifest.read_text(encoding="utf-8"))

    # Load schema
    schema = json.loads(_BUNDLE_MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))

    # Validate schema
    jsonschema.validate(instance=data, schema=schema)

    # Verify key roles are present and contracts are assigned for structured artifacts
    roles_map = {item["role"]: item for item in data["artifacts"]}
    assert ArtifactRole.CANONICAL_MD.value in roles_map

    sidecar_entry = roles_map.get(ArtifactRole.INDEX_SIDECAR_JSON.value)
    assert sidecar_entry and "contract" in sidecar_entry
    assert sidecar_entry["contract"]["id"] == "repolens-agent"
    assert sidecar_entry["interpretation"]["mode"] == "contract"

    dump_entry = roles_map.get(ArtifactRole.DUMP_INDEX_JSON.value)
    assert dump_entry and "contract" not in dump_entry
    assert dump_entry["interpretation"]["mode"] == "role_only"

    chunk_entry = roles_map.get(ArtifactRole.CHUNK_INDEX_JSONL.value)
    assert chunk_entry and "contract" not in chunk_entry
    assert chunk_entry["interpretation"]["mode"] == "role_only"

    citation_entry = roles_map.get(ArtifactRole.CITATION_MAP_JSONL.value)
    assert citation_entry and "contract" in citation_entry
    assert citation_entry["contract"]["id"] == "citation-map"
    assert citation_entry["contract"]["version"] == "v1"
    assert citation_entry["interpretation"]["mode"] == "contract"
    assert citation_entry["authority"] == "navigation_index"
    assert citation_entry["canonicality"] == "derived"
    assert citation_entry["regenerable"] is True
    assert citation_entry["staleness_sensitive"] is True
    assert citation_entry["path"].endswith(".citation_map.jsonl")

    claim_map_entry = roles_map.get(ArtifactRole.CLAIM_EVIDENCE_MAP_JSON.value)
    assert claim_map_entry and "contract" in claim_map_entry
    assert claim_map_entry["contract"]["id"] == "claim-evidence-map"
    assert claim_map_entry["contract"]["version"] == "v1"
    assert claim_map_entry["interpretation"]["mode"] == "contract"
    assert claim_map_entry["authority"] == "navigation_index"
    assert claim_map_entry["canonicality"] == "derived"
    assert claim_map_entry["regenerable"] is True
    assert claim_map_entry["staleness_sensitive"] is True
    assert claim_map_entry["path"].endswith(".claim_evidence_map.json")

    output_health_entry = roles_map.get(ArtifactRole.OUTPUT_HEALTH.value)
    assert output_health_entry and "contract" not in output_health_entry
    assert output_health_entry["interpretation"]["mode"] == "role_only"

    # Since it's 'dual' output mode, sqlite_index should exist if fts5_bm25 is true
    if data["capabilities"].get("fts5_bm25"):
        assert ArtifactRole.SQLITE_INDEX.value in roles_map


def test_full_bundle_manifest_contains_output_health(tmp_path):
    artifacts, _, _ = _make_minimal_bundle(tmp_path, output_mode="dual")

    assert artifacts.bundle_manifest is not None
    manifest = json.loads(artifacts.bundle_manifest.read_text(encoding="utf-8"))
    roles = {artifact["role"] for artifact in manifest["artifacts"]}

    assert ArtifactRole.OUTPUT_HEALTH.value in roles


def test_output_health_file_exists_and_schema_valid(tmp_path):
    artifacts, manifest, _ = _make_minimal_bundle(tmp_path, output_mode="dual")

    assert artifacts.output_health is not None
    assert artifacts.output_health.exists()

    health = json.loads(artifacts.output_health.read_text(encoding="utf-8"))
    output_health_schema = json.loads(_OUTPUT_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=health, schema=output_health_schema)

    manifest_schema = json.loads(_BUNDLE_MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=manifest, schema=manifest_schema)

    output_health_entry = _artifact_by_role(manifest, ArtifactRole.OUTPUT_HEALTH.value)
    assert output_health_entry is not None
    assert Path(output_health_entry["path"]).name == artifacts.output_health.name


def test_output_health_verdict_pass_for_healthy_dual_bundle(tmp_path):
    artifacts, _, _ = _make_minimal_bundle(tmp_path, output_mode="dual")

    assert artifacts.output_health is not None
    health = json.loads(artifacts.output_health.read_text(encoding="utf-8"))

    assert health["errors"] == []
    assert health["warnings"] == []
    assert health["verdict"] == "pass"
    assert health["checks"]["canonical_md_required"] is True
    assert health["checks"]["chunk_index_required"] is True
    assert health["checks"]["canonical_md_hash_ok"] is True
    assert health["checks"]["chunk_index_hash_ok"] is True
    assert health["checks"]["range_ref_resolution_ok"] is True
    assert health["checks"]["range_ref_resolution_status"] == "ok"


def test_output_health_broken_range_ref_is_fail_in_repo_near_flow(tmp_path):
    artifacts, _, _ = _make_minimal_bundle(tmp_path, output_mode="dual")

    assert artifacts.chunk_index is not None
    lines = artifacts.chunk_index.read_text(encoding="utf-8").splitlines()
    assert lines, "chunk_index must contain at least one chunk"

    first_chunk = json.loads(lines[0])
    assert isinstance(first_chunk, dict)
    assert isinstance(first_chunk.get("content_range_ref"), dict)
    first_chunk["content_range_ref"]["file_path"] = "totally_missing_artifact.md"
    first_chunk["content_range_ref"]["content_sha256"] = "0" * _SHA256_HEX_LENGTH
    lines[0] = json.dumps(first_chunk, ensure_ascii=False)
    artifacts.chunk_index.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert artifacts.canonical_md is not None
    assert artifacts.dump_index is not None
    canonical_sha = _sha256_file(artifacts.canonical_md)
    chunk_sha = _sha256_file(artifacts.chunk_index)

    health = compute_output_health(
        run_id="proof-range-ref-fail",
        stem="proof",
        primary_manifest_path=artifacts.dump_index,
        canonical_md_path=artifacts.canonical_md,
        chunk_index_path=artifacts.chunk_index,
        dump_index_path=artifacts.dump_index,
        sqlite_index_path=None,
        sqlite_index_required=False,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_sha,
        expected_chunk_index_sha256=chunk_sha,
    )

    assert health["checks"]["canonical_md_hash_ok"] is True
    assert health["checks"]["chunk_index_hash_ok"] is True
    assert health["checks"]["chunk_count"] > 0
    assert health["checks"]["range_ref_resolution_ok"] is False
    assert health["checks"]["range_ref_resolution_status"] == "fail"
    assert health["verdict"] == "fail"
    assert any("range_ref" in e.lower() for e in health["errors"])


def test_output_health_archive_mode_does_not_require_chunk_index(tmp_path):
    artifacts, _, _ = _make_minimal_bundle(tmp_path, output_mode="archive")

    assert artifacts.output_health is not None
    health = json.loads(artifacts.output_health.read_text(encoding="utf-8"))
    assert health["checks"]["chunk_index_required"] is False
    assert health["checks"]["chunk_index_hash_ok"] is None
    assert health["errors"] == []
    assert health["verdict"] == "pass"


def test_output_health_retrieval_mode_does_not_require_canonical_md(tmp_path):
    artifacts, _, _ = _make_minimal_bundle(tmp_path, output_mode="retrieval")

    assert artifacts.output_health is not None
    health = json.loads(artifacts.output_health.read_text(encoding="utf-8"))
    assert health["checks"]["canonical_md_required"] is False
    assert health["checks"]["canonical_md_hash_ok"] is None
    assert not any("canonical_md hash check failed" in e for e in health["errors"])


def test_dual_bundle_without_sqlite_is_health_fail(tmp_path, monkeypatch):
    monkeypatch.setattr("merger.lenskit.core.merge.build_derived_artifacts", lambda *args, **kwargs: [])

    artifacts, manifest, _ = _make_minimal_bundle(tmp_path, output_mode="dual")

    health = json.loads(artifacts.output_health.read_text(encoding="utf-8"))
    roles = {artifact["role"] for artifact in manifest["artifacts"]}

    assert ArtifactRole.SQLITE_INDEX.value not in roles
    assert health["verdict"] == "fail"
    assert health["checks"]["sqlite_checks_required"] is True
    assert any("sqlite_index expected but file is missing" in e for e in health["errors"])


def test_dual_bundle_jsonschema_missing_still_materializes_sqlite(tmp_path, monkeypatch):
    monkeypatch.setattr("merger.lenskit.core.range_resolver.jsonschema", None)

    artifacts, manifest, _ = _make_minimal_bundle(tmp_path, output_mode="dual")

    roles = {artifact["role"] for artifact in manifest["artifacts"]}
    assert ArtifactRole.SQLITE_INDEX.value in roles
    assert artifacts.sqlite_index is not None

    conn = sqlite3.connect(str(artifacts.sqlite_index))
    try:
        chunk_count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        meta = dict(conn.execute("SELECT key, value FROM index_meta").fetchall())
    finally:
        conn.close()

    health = json.loads(artifacts.output_health.read_text(encoding="utf-8"))
    assert chunk_count > 0
    assert fts_count == chunk_count
    assert int(meta.get("ingest.fts_hydrated_from_canonical_range", "0")) > 0
    assert health["checks"]["sqlite_present"] is True
    assert health["checks"]["sqlite_row_count"] == chunk_count
    assert health["checks"]["fts_content_non_empty"] is True
    assert health["checks"]["range_ref_resolution_status"] == "environment_error"
    assert health["verdict"] == "warn"


def test_invalid_config_sha256_raises_error(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    f1 = src_dir / "file1.txt"
    f1.write_text("Hello", encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    hub_dir = tmp_path / "hub"
    hub_dir.mkdir()

    fi1 = FileInfo(
        root_label="test-repo",
        abs_path=f1,
        rel_path=Path("file1.txt"),
        size=5,
        is_text=True,
        md5="test",
        category="docs",
        tags=[],
        ext=".txt",
        skipped=False,
    )

    repo_summary = {
        "name": "test-repo",
        "path": str(src_dir),
        "root": src_dir,
        "files": [fi1],
        "source_files": [fi1]
    }

    with pytest.raises(ValueError, match="generator_info.config_sha256 \\(64 hex lowercase\\) is required"):
        write_reports_v2(
            merges_dir=out_dir,
            hub=hub_dir,
            repo_summaries=[repo_summary],
            detail="test",
            mode="gesamt",
            max_bytes=1000,
            plan_only=False,
            code_only=False,
            extras=MockExtras(),
            output_mode="dual",
            generator_info={"name": "test", "version": "1.0", "config_sha256": "invalid_hash"}
        )

def test_missing_config_sha256_is_computed_and_manifest_contains_valid_hash(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    f1 = src_dir / "file1.txt"
    f1.write_text("Hello", encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    hub_dir = tmp_path / "hub"
    hub_dir.mkdir()

    fi1 = FileInfo(
        root_label="test-repo",
        abs_path=f1,
        rel_path=Path("file1.txt"),
        size=5,
        is_text=True,
        md5="test",
        category="docs",
        tags=[],
        ext=".txt",
        skipped=False,
    )

    repo_summary = {
        "name": "test-repo",
        "path": str(src_dir),
        "root": src_dir,
        "files": [fi1],
        "source_files": [fi1]
    }

    artifacts = write_reports_v2(
        merges_dir=out_dir,
        hub=hub_dir,
        repo_summaries=[repo_summary],
        detail="test",
        mode="gesamt",
        max_bytes=1000,
        plan_only=False,
        code_only=False,
        extras=MockExtras(),
        output_mode="dual",
        generator_info={"name": "test", "version": "1.0"}
    )

    assert artifacts.bundle_manifest is not None
    assert artifacts.bundle_manifest.exists()

    data = json.loads(artifacts.bundle_manifest.read_text(encoding="utf-8"))

    assert "generator" in data
    assert "config_sha256" in data["generator"]
    assert re.fullmatch(r"[a-f0-9]{64}", data["generator"]["config_sha256"])


def test_producer_emits_authority_metadata_per_role(tmp_path):
    """Phase 1 of Artifact Integrity blueprint: the producer must annotate
    well-defined roles with authority/canonicality/regenerable/staleness_sensitive
    so consumers can distinguish content, index, cache and diagnostic artifacts
    without parsing role strings by hand."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    f1 = src_dir / "file1.txt"
    f1.write_text("Hello World", encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    hub_dir = tmp_path / "hub"
    hub_dir.mkdir()

    fi1 = FileInfo(
        root_label="test-repo",
        abs_path=f1,
        rel_path=Path("file1.txt"),
        size=11,
        is_text=True,
        md5="test",
        category="docs",
        tags=[],
        ext=".txt",
        skipped=False,
    )

    repo_summary = {
        "name": "test-repo",
        "path": str(src_dir),
        "root": src_dir,
        "files": [fi1],
        "source_files": [fi1]
    }

    artifacts = write_reports_v2(
        merges_dir=out_dir,
        hub=hub_dir,
        repo_summaries=[repo_summary],
        detail="test",
        mode="gesamt",
        max_bytes=1000,
        plan_only=False,
        code_only=False,
        extras=MockExtras(),
        output_mode="dual",
        generator_info=make_generator_info()
    )

    assert artifacts.bundle_manifest is not None
    assert artifacts.bundle_manifest.exists()

    data = json.loads(artifacts.bundle_manifest.read_text(encoding="utf-8"))

    # Schema guard: emitted manifest still validates with the new fields present.
    schema = json.loads(_BUNDLE_MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=schema)

    roles_map = {item["role"]: item for item in data["artifacts"]}

    # canonical_md is the single canonical content authority in the bundle.
    can_md = roles_map.get(ArtifactRole.CANONICAL_MD.value)
    assert can_md is not None, "canonical_md must be present in the manifest"
    assert can_md["authority"] == "canonical_content"
    assert can_md["canonicality"] == "content_source"
    assert can_md["regenerable"] is True
    assert can_md["staleness_sensitive"] is False

    # index_sidecar_json is navigation, not content.
    sidecar = roles_map.get(ArtifactRole.INDEX_SIDECAR_JSON.value)
    assert sidecar is not None
    assert sidecar["authority"] == "navigation_index"
    assert sidecar["canonicality"] == "index_only"
    assert sidecar["staleness_sensitive"] is True

    # dump_index_json is navigation/index_only as well.
    dump_idx = roles_map.get(ArtifactRole.DUMP_INDEX_JSON.value)
    assert dump_idx is not None
    assert dump_idx["authority"] == "navigation_index"
    assert dump_idx["canonicality"] == "index_only"

    # chunk_index_jsonl is the derived retrieval index input.
    chunk_idx = roles_map.get(ArtifactRole.CHUNK_INDEX_JSONL.value)
    assert chunk_idx is not None
    assert chunk_idx["authority"] == "retrieval_index"
    assert chunk_idx["canonicality"] == "derived"

    # derived_manifest_json (file: <base>.derived_index.json) is a navigation
    # artifact linking derived artifacts back to their dump_index source —
    # not a retrieval index itself.
    derived_manifest = roles_map.get(ArtifactRole.DERIVED_MANIFEST_JSON.value)
    assert derived_manifest is not None
    assert derived_manifest["authority"] == "navigation_index"
    assert derived_manifest["canonicality"] == "derived"
    assert derived_manifest["regenerable"] is True
    assert derived_manifest["staleness_sensitive"] is True

    # sqlite_index is a runtime cache rebuilt from chunk_index_jsonl;
    # it must never be advertised as canonical content.
    if data["capabilities"].get("fts5_bm25"):
        sqlite_idx = roles_map.get(ArtifactRole.SQLITE_INDEX.value)
        assert sqlite_idx is not None
        assert sqlite_idx["authority"] == "runtime_cache"
        assert sqlite_idx["canonicality"] == "cache"
        assert sqlite_idx["regenerable"] is True
        assert sqlite_idx["staleness_sensitive"] is True


def test_generator_info_none_is_supported_and_hash_is_computed(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir(exist_ok=True)
    f1 = src_dir / "file1.txt"
    f1.write_text("Hello", encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    hub_dir = tmp_path / "hub"
    hub_dir.mkdir(exist_ok=True)

    fi1 = FileInfo(
        root_label="test-repo",
        abs_path=f1,
        rel_path=Path("file1.txt"),
        size=5,
        is_text=True,
        md5="test",
        category="docs",
        tags=[],
        ext=".txt",
        skipped=False,
    )

    repo_summary = {
        "name": "test-repo",
        "path": str(src_dir),
        "root": src_dir,
        "files": [fi1],
        "source_files": [fi1]
    }

    artifacts = write_reports_v2(
        merges_dir=out_dir,
        hub=hub_dir,
        repo_summaries=[repo_summary],
        detail="test",
        mode="gesamt",
        max_bytes=1000,
        plan_only=False,
        code_only=False,
        extras=MockExtras(),
        output_mode="dual",
        generator_info=None
    )

    assert artifacts.bundle_manifest is not None
    assert artifacts.bundle_manifest.exists()

    data = json.loads(artifacts.bundle_manifest.read_text(encoding="utf-8"))

    assert "generator" in data
    assert "config_sha256" in data["generator"]
    assert re.fullmatch(r"[a-f0-9]{64}", data["generator"]["config_sha256"])


def _make_minimal_bundle(tmp_path, *, output_mode: str = "dual"):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    f1 = src_dir / "file1.txt"
    f1.write_text("Hello World", encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    hub_dir = tmp_path / "hub"
    hub_dir.mkdir()

    fi1 = FileInfo(
        root_label="test-repo",
        abs_path=f1,
        rel_path=Path("file1.txt"),
        size=11,
        is_text=True,
        md5="test",
        category="docs",
        tags=[],
        ext=".txt",
        skipped=False,
    )

    repo_summary = {
        "name": "test-repo",
        "path": str(src_dir),
        "root": src_dir,
        "files": [fi1],
        "source_files": [fi1],
    }

    artifacts = write_reports_v2(
        merges_dir=out_dir,
        hub=hub_dir,
        repo_summaries=[repo_summary],
        detail="test",
        mode="gesamt",
        max_bytes=1000,
        plan_only=False,
        code_only=False,
        extras=MockExtras(),
        output_mode=output_mode,
        generator_info=make_generator_info(),
    )
    data = json.loads(artifacts.bundle_manifest.read_text(encoding="utf-8"))
    manifest_dir = artifacts.bundle_manifest.parent
    return artifacts, data, manifest_dir


def test_bundle_manifest_artifact_hashes_match_files(tmp_path):
    """Every artifact entry's sha256 and bytes must match the file on disk."""
    _, data, manifest_dir = _make_minimal_bundle(tmp_path)

    assert data["artifacts"], "manifest must contain at least one artifact"
    for entry in data["artifacts"]:
        p = manifest_dir / entry["path"]
        assert p.exists(), f"artifact file missing: {entry['path']}"
        assert p.stat().st_size == entry["bytes"], (
            f"bytes mismatch for {entry['path']}: "
            f"manifest={entry['bytes']} file={p.stat().st_size}"
        )
        assert _sha256_file(p) == entry["sha256"], (
            f"sha256 mismatch for {entry['path']}"
        )


def test_citation_map_artifact_integrity_and_schema(tmp_path):
    artifacts, data, manifest_dir = _make_minimal_bundle(tmp_path)

    manifest_schema = json.loads(_BUNDLE_MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
    citation_schema = json.loads(_CITATION_MAP_SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.validate(instance=data, schema=manifest_schema)

    roles_map = {item["role"]: item for item in data["artifacts"]}
    citation_entry = roles_map[ArtifactRole.CITATION_MAP_JSONL.value]
    chunk_entry = roles_map[ArtifactRole.CHUNK_INDEX_JSONL.value]
    canonical_entry = roles_map[ArtifactRole.CANONICAL_MD.value]

    citation_path = manifest_dir / citation_entry["path"]
    chunk_path = manifest_dir / chunk_entry["path"]

    assert citation_path.exists()
    assert citation_entry["bytes"] == citation_path.stat().st_size
    assert citation_entry["sha256"] == _sha256_file(citation_path)

    with citation_path.open(encoding="utf-8") as f:
        citation_rows = [json.loads(line) for line in f if line.strip()]
    with chunk_path.open(encoding="utf-8") as f:
        chunk_rows = [json.loads(line) for line in f if line.strip()]

    assert len(citation_rows) == len(chunk_rows)
    assert len(citation_rows) > 0
    assert citation_entry["bytes"] == citation_path.stat().st_size
    assert canonical_entry["sha256"] == citation_rows[0]["snapshot"]["canonical_md_sha256"]

    citation_ids = set()
    chunk_ids = {row.get("chunk_id") for row in chunk_rows if row.get("chunk_id") is not None}
    for row in citation_rows:
        jsonschema.validate(instance=row, schema=citation_schema)
        assert row["citation_id"] not in citation_ids
        citation_ids.add(row["citation_id"])
        if "chunk_id" in row:
            assert row["chunk_id"] in chunk_ids

    assert len(citation_ids) == len(citation_rows)


def test_agent_reading_pack_emitted_schema_valid_and_hashed(tmp_path):
    artifacts, data, manifest_dir = _make_minimal_bundle(tmp_path, output_mode="dual")

    manifest_schema = json.loads(_BUNDLE_MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=manifest_schema)

    pack_entry = _artifact_by_role(data, ArtifactRole.AGENT_READING_PACK.value)
    assert pack_entry is not None, "agent_reading_pack must be emitted into the bundle manifest"

    # Governance contract: navigation aid, derived, role_only, markdown.
    assert pack_entry["content_type"] == "text/markdown"
    assert pack_entry["authority"] == "navigation_index"
    assert pack_entry["canonicality"] == "derived"
    assert pack_entry["regenerable"] is True
    assert pack_entry["staleness_sensitive"] is True
    assert "contract" not in pack_entry
    assert pack_entry["interpretation"]["mode"] == "role_only"
    assert pack_entry["path"].endswith(".agent_reading_pack.md")

    # MergeArtifacts exposes the pack and the file is hash-consistent with the manifest.
    assert artifacts.agent_reading_pack is not None
    assert artifacts.agent_reading_pack.exists()
    pack_path = manifest_dir / pack_entry["path"]
    assert pack_path == artifacts.agent_reading_pack
    assert pack_entry["bytes"] == pack_path.stat().st_size
    assert pack_entry["sha256"] == _sha256_file(pack_path)

    body = pack_path.read_text(encoding="utf-8")
    assert body.startswith("<!-- ARTIFACT:agent_reading_pack VERSION:v1")
    assert "NAVIGATION, NOT TRUTH" in body
    assert data["run_id"] in body
    # The pack must never list its own role as bundle content.
    assert "| agent_reading_pack |" not in body
    # It should reference the bundle's truth anchor and health verdict.
    assert "## OUTPUT_HEALTH_SUMMARY" in body
    assert "## TOP_CHUNK_SPANS" in body


def test_bundle_manifest_canonical_dump_index_sha_matches_dump_index_artifact(tmp_path):
    """links.canonical_dump_index_sha256 must equal the dump_index_json artifact sha256."""
    _, data, manifest_dir = _make_minimal_bundle(tmp_path)

    assert "canonical_dump_index_sha256" in data["links"], (
        "links.canonical_dump_index_sha256 must be present"
    )
    link_sha = data["links"]["canonical_dump_index_sha256"]

    dump_entry = _artifact_by_role(data, ArtifactRole.DUMP_INDEX_JSON.value)
    assert dump_entry is not None, "dump_index_json artifact must be present"

    dump_path = manifest_dir / dump_entry["path"]
    assert dump_path.exists(), f"dump_index_json file missing: {dump_entry['path']}"

    assert link_sha == dump_entry["sha256"], (
        "links.canonical_dump_index_sha256 must equal dump_index_json artifact sha256"
    )
    assert link_sha == _sha256_file(dump_path), (
        "links.canonical_dump_index_sha256 must equal recomputed hash of dump_index_json file"
    )


def test_bundle_manifest_hash_recompute_detects_artifact_drift(tmp_path):
    """Mutating an artifact after manifest creation must cause a sha256 mismatch on recompute."""
    _, data, manifest_dir = _make_minimal_bundle(tmp_path)

    # Prefer dump_index_json or index_sidecar_json as the target; fall back to first artifact.
    target_role = ArtifactRole.DUMP_INDEX_JSON.value
    entry = _artifact_by_role(data, target_role)
    if entry is None:
        entry = _artifact_by_role(data, ArtifactRole.INDEX_SIDECAR_JSON.value)
    if entry is None:
        entry = data["artifacts"][0]

    target_path = manifest_dir / entry["path"]
    assert target_path.exists()

    recorded_sha = entry["sha256"]
    assert _sha256_file(target_path) == recorded_sha, "precondition: hash matches before mutation"

    # Mutate the file — append a single byte so the hash changes.
    with open(target_path, "ab") as f:
        f.write(b"\x00")

    assert _sha256_file(target_path) != recorded_sha, (
        "recomputed hash must differ from manifest after artifact mutation"
    )


def test_manifest_coherence_check_accepts_coherent_manifest(tmp_path):
    from merger.lenskit.core.citation_map import check_manifest_coherence_for_citation_map

    artifacts, manifest_data, _ = _make_minimal_bundle(tmp_path)
    manifest_path = artifacts.bundle_manifest
    assert manifest_path is not None and manifest_path.exists()

    assert any(a["role"] == "canonical_md" for a in manifest_data["artifacts"])
    assert any(a["role"] == "chunk_index_jsonl" for a in manifest_data["artifacts"])

    coherence = check_manifest_coherence_for_citation_map(manifest_path)
    assert coherence.coherent is True
    assert coherence.skip_allowed is False
    assert coherence.reason in ("coherent", "coherent_empty_chunk_index")


def test_manifest_coherence_check_marks_path_mismatch_as_skippable(tmp_path):
    from merger.lenskit.core.citation_map import check_manifest_coherence_for_citation_map

    artifacts, manifest_data, manifest_dir = _make_minimal_bundle(tmp_path)
    manifest_path = artifacts.bundle_manifest
    assert manifest_path is not None and manifest_path.exists()

    chunk_index_entry = next(
        (a for a in manifest_data["artifacts"] if a["role"] == "chunk_index_jsonl"), None
    )
    assert chunk_index_entry is not None

    chunk_index_path = manifest_dir / chunk_index_entry["path"]
    rows = []
    with chunk_index_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    assert rows
    rows[0]["canonical_range"]["file_path"] = "wrong_file.md"
    with chunk_index_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    coherence = check_manifest_coherence_for_citation_map(manifest_path)
    assert coherence.coherent is False
    assert coherence.skip_allowed is True
    assert coherence.reason == "range_file_path_mismatch"


def test_manifest_coherence_check_marks_invalid_json_as_hard_error(tmp_path):
    from merger.lenskit.core.citation_map import check_manifest_coherence_for_citation_map

    artifacts, manifest_data, manifest_dir = _make_minimal_bundle(tmp_path)
    manifest_path = artifacts.bundle_manifest
    assert manifest_path is not None and manifest_path.exists()

    chunk_index_entry = next(
        (a for a in manifest_data["artifacts"] if a["role"] == "chunk_index_jsonl"), None
    )
    assert chunk_index_entry is not None

    chunk_index_path = manifest_dir / chunk_index_entry["path"]
    chunk_index_path.write_text("{not-json}\n", encoding="utf-8")

    coherence = check_manifest_coherence_for_citation_map(manifest_path)
    assert coherence.coherent is False
    assert coherence.skip_allowed is False
    assert coherence.reason == "invalid_chunk_index_json"


def test_manifest_coherence_check_accepts_empty_chunk_index(tmp_path):
    from merger.lenskit.core.citation_map import check_manifest_coherence_for_citation_map

    artifacts, manifest_data, manifest_dir = _make_minimal_bundle(tmp_path)
    manifest_path = artifacts.bundle_manifest
    assert manifest_path is not None and manifest_path.exists()

    chunk_index_entry = next(
        (a for a in manifest_data["artifacts"] if a["role"] == "chunk_index_jsonl"), None
    )
    assert chunk_index_entry is not None

    chunk_index_path = manifest_dir / chunk_index_entry["path"]
    chunk_index_path.write_text("", encoding="utf-8")

    coherence = check_manifest_coherence_for_citation_map(manifest_path)
    assert coherence.coherent is True
    assert coherence.skip_allowed is False
    assert coherence.reason == "coherent_empty_chunk_index"


def test_manifest_coherence_check_marks_unsafe_path_as_hard_error(tmp_path):
    from merger.lenskit.core.citation_map import check_manifest_coherence_for_citation_map

    artifacts, manifest_data, manifest_dir = _make_minimal_bundle(tmp_path)
    manifest_path = artifacts.bundle_manifest
    assert manifest_path is not None and manifest_path.exists()

    chunk_index_entry = next(
        (a for a in manifest_data["artifacts"] if a["role"] == "chunk_index_jsonl"), None
    )
    assert chunk_index_entry is not None

    chunk_index_path = manifest_dir / chunk_index_entry["path"]
    rows = []
    with chunk_index_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    assert rows
    rows[0]["canonical_range"]["file_path"] = "../escape.md"
    with chunk_index_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    coherence = check_manifest_coherence_for_citation_map(manifest_path)
    assert coherence.coherent is False
    assert coherence.skip_allowed is False
    assert coherence.reason == "unsafe_range_file_path"


# ── C2.2 — per-role risk_class + output_health authority branch ──────────────
#
# These tests cover the additive, optional bundle-manifest.v1 normalization:
#   * legacy manifests without risk_class stay valid,
#   * correct per-role risk_class consts validate,
#   * wrong per-role risk_class consts are rejected,
#   * the output_health role gains an authority/canonicality/risk_class branch,
#   * retrieval_index roles actively reject any risk_class until C1 defines one (STOP).

_BUNDLE_SCHEMA = json.loads(_BUNDLE_MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))


def _manifest_with(artifact: dict) -> dict:
    return {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "c2-2-test",
        "created_at": "2026-05-25T00:00:00Z",
        "generator": {"name": "t", "version": "1", "config_sha256": "a" * 64},
        "artifacts": [artifact],
        "links": {},
        "capabilities": {},
    }


def _artifact(role: str, **extra) -> dict:
    base = {
        "role": role,
        "path": f"x.{role}",
        "content_type": "application/json",
        "bytes": 1,
        "sha256": "a" * 64,
    }
    base.update(extra)
    return base


def _validate(artifact: dict) -> None:
    jsonschema.validate(instance=_manifest_with(artifact), schema=_BUNDLE_SCHEMA)


def test_c22_legacy_manifest_without_risk_class_stays_valid():
    # No risk_class on any role: must still validate (additive, optional).
    _validate(_artifact("canonical_md", authority="canonical_content",
                        canonicality="content_source"))
    _validate(_artifact("output_health"))
    _validate(_artifact("sqlite_index"))


def test_c22_correct_per_role_risk_class_is_valid():
    # Covers all roles for which C2.2 defines a per-role risk_class const.
    # This is contract-schema validation only; producer emission of risk_class
    # is deliberately NOT part of C2.2.
    cases = {
        "canonical_md":        ("content",     {}),
        "index_sidecar_json":  ("navigation",  {"contract": {"id": "x", "version": "v1"},
                                                "interpretation": {"mode": "contract"}}),
        "dump_index_json":     ("navigation",  {}),
        "derived_manifest_json":("navigation", {}),
        "sqlite_index":        ("cache",       {}),
        "architecture_summary":("diagnostic",  {"contract": {"id": "x", "version": "v1"},
                                                "interpretation": {"mode": "contract"}}),
        "retrieval_eval_json": ("diagnostic",  {"contract": {"id": "x", "version": "v1"},
                                                "interpretation": {"mode": "contract"}}),
        "delta_json":          ("diagnostic",  {"contract": {"id": "x", "version": "v1"},
                                                "interpretation": {"mode": "contract"}}),
        "citation_map_jsonl":  ("navigation",  {"contract": {"id": "citation-map", "version": "v1"},
                                                "interpretation": {"mode": "contract"},
                                                "content_type": "application/x-ndjson",
                                                "authority": "navigation_index",
                                                "canonicality": "derived",
                                                "regenerable": True,
                                                "staleness_sensitive": True}),
        "claim_evidence_map_json": ("evidence_index", {"contract": {"id": "claim-evidence-map", "version": "v1"},
                            "interpretation": {"mode": "contract"},
                            "content_type": "application/json",
                            "authority": "navigation_index",
                            "canonicality": "derived",
                            "regenerable": True,
                            "staleness_sensitive": True}),
        "agent_reading_pack":  ("navigation",  {"content_type": "text/markdown",
                                                "authority": "navigation_index",
                                                "canonicality": "derived"}),
        "output_health":       ("diagnostic",  {}),
    }
    for role, (risk, extra) in cases.items():
        artifact = _artifact(role, risk_class=risk, **extra)
        _validate(artifact)


def test_c22_wrong_per_role_risk_class_is_invalid():
    wrong_no_extra = {
        "canonical_md": "navigation",
        "dump_index_json": "diagnostic",
        "sqlite_index": "content",
        "output_health": "navigation",
    }
    for role, risk in wrong_no_extra.items():
        with pytest.raises(jsonschema.ValidationError):
            _validate(_artifact(role, risk_class=risk))

    # Roles that require contract+interpretation: wrong risk_class still invalid.
    for role in ("architecture_summary", "delta_json"):
        artifact = _artifact(role, risk_class="navigation",
                             contract={"id": "x", "version": "v1"},
                             interpretation={"mode": "contract"})
        with pytest.raises(jsonschema.ValidationError):
            _validate(artifact)


def test_c22_output_health_correct_authority_canonicality_is_valid():
    _validate(_artifact(
        "output_health",
        authority="diagnostic_signal",
        canonicality="diagnostic",
        risk_class="diagnostic",
    ))


def test_c22_output_health_wrong_authority_is_invalid():
    with pytest.raises(jsonschema.ValidationError):
        _validate(_artifact("output_health", authority="navigation_index"))
    with pytest.raises(jsonschema.ValidationError):
        _validate(_artifact("output_health", canonicality="content_source"))


def test_c22_retrieval_index_roles_reject_any_risk_class_until_c1_defines_it():
    # STOP: C1 documents no risk_class for retrieval_index, so the schema actively
    # forbids any risk_class on these roles — an absent field is a real stop, not a sign.
    for role in ("chunk_index_jsonl", "graph_index_json"):
        artifact = _artifact(role, authority="retrieval_index",
                             canonicality="derived")
        if role == "graph_index_json":
            artifact["contract"] = {"id": "x", "version": "v1"}
            artifact["interpretation"] = {"mode": "contract"}
        _validate(dict(artifact))  # absent risk_class: valid
        for risk in ("content", "navigation", "diagnostic", "cache",
                     "observation", "derived", "external"):
            with pytest.raises(jsonschema.ValidationError):
                _validate({**artifact, "risk_class": risk})


# ── C2.2 follow-up — producer-side risk_class emission ──────────────────────
#
# Schema slice (C2.2) is content-only; the manifest schema already permits the
# optional per-role risk_class const. The producer now emits risk_class for
# roles whose risk_class is unambiguously documented in the C1 authority/risk
# matrix:
#   * canonical_content   → content
#   * navigation_index    → navigation
#   * runtime_cache       → cache
#   * diagnostic_signal   → diagnostic
# retrieval_index roles (chunk_index_jsonl, graph_index_json) stay silent
# until C1 normalizes a risk_class for retrieval_index.


_EXPECTED_RISK_CLASS_BY_ROLE = {
    ArtifactRole.CANONICAL_MD.value: "content",
    ArtifactRole.INDEX_SIDECAR_JSON.value: "navigation",
    ArtifactRole.DUMP_INDEX_JSON.value: "navigation",
    ArtifactRole.DERIVED_MANIFEST_JSON.value: "navigation",
    ArtifactRole.SQLITE_INDEX.value: "cache",
    ArtifactRole.RETRIEVAL_EVAL_JSON.value: "diagnostic",
    ArtifactRole.OUTPUT_HEALTH.value: "diagnostic",
    ArtifactRole.CITATION_MAP_JSONL.value: "navigation",
    ArtifactRole.CLAIM_EVIDENCE_MAP_JSON.value: "evidence_index",
    ArtifactRole.AGENT_READING_PACK.value: "navigation",
}

_RETRIEVAL_INDEX_ROLES = (
    ArtifactRole.CHUNK_INDEX_JSONL.value,
    ArtifactRole.GRAPH_INDEX_JSON.value,
)


def test_c22_producer_emits_risk_class_for_classified_roles(tmp_path):
    _, data, _ = _make_minimal_bundle(tmp_path, output_mode="dual")

    # Schema guard: emitted manifest must still validate with risk_class present.
    schema = json.loads(_BUNDLE_MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=schema)

    roles_map = {item["role"]: item for item in data["artifacts"]}

    for role, expected_risk in _EXPECTED_RISK_CLASS_BY_ROLE.items():
        entry = roles_map.get(role)
        if entry is None:
            # Some roles are profile-dependent (e.g. sqlite_index requires fts5_bm25).
            # The producer test only asserts the contract for roles actually emitted.
            continue
        assert entry.get("risk_class") == expected_risk, (
            f"role {role}: expected risk_class={expected_risk!r}, "
            f"got {entry.get('risk_class')!r}"
        )


def test_c22_producer_does_not_emit_risk_class_for_retrieval_index_roles(tmp_path):
    _, data, _ = _make_minimal_bundle(tmp_path, output_mode="dual")

    schema = json.loads(_BUNDLE_MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=schema)

    roles_map = {item["role"]: item for item in data["artifacts"]}

    for role in _RETRIEVAL_INDEX_ROLES:
        entry = roles_map.get(role)
        if entry is None:
            continue
        assert "risk_class" not in entry, (
            f"role {role}: retrieval_index roles must not carry risk_class "
            f"until C1 normalizes one; got {entry.get('risk_class')!r}"
        )
