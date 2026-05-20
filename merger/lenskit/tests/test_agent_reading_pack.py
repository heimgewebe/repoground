"""
Unit tests for core/agent_reading_pack.py (the agent_reading_pack producer).

Uses self-contained synthetic bundle manifests so the tests do not depend on the
full merge pipeline. The pipeline-level emission is covered separately in
test_bundle_manifest_integration.py.
"""
import hashlib
import json
from pathlib import Path

from merger.lenskit.core.agent_reading_pack import (
    HealthSummary,
    PackModel,
    compute_top_files,
    produce_agent_reading_pack,
    render_agent_reading_pack,
    summarize_health,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_CANONICAL = (
    b"<!-- merge -->\n"
    b"# repo: demo\n\n"
    b"## file: README.md\n"
    b"# Demo\n\nDemo repo body.\n\n"
    b"## file: src/app.py\n"
    b"def main():\n    return 0\n"
)

# Byte spans of the two file bodies inside _CANONICAL.
_README_START = _CANONICAL.index(b"# Demo")
_README_END = _CANONICAL.index(b"\n\n## file: src/app.py")
_APP_START = _CANONICAL.index(b"def main():")
_APP_END = len(_CANONICAL)


def _chunk(path: str, start: int, end: int, repo: str = "demo") -> dict:
    return {
        "chunk_id": f"{path}:{start}",
        "path": path,
        "search_keys": {"repo_id": repo},
        "canonical_range": {
            "artifact_role": "canonical_md",
            "file_path": "demo.md",
            "start_byte": start,
            "end_byte": end,
            "content_sha256": _sha256(_CANONICAL[start:end]),
        },
    }


def _health_doc(verdict: str = "pass") -> dict:
    return {
        "kind": "lenskit.output_health",
        "version": "1.0",
        "run_id": "demo-run",
        "created_at": "2026-05-20T00:00:00Z",
        "stem": "demo",
        "checks": {
            "chunk_count": 2,
            "sqlite_row_count": 2,
            "fts_content_non_empty": True,
            "range_ref_resolution_status": "ok",
        },
        "diagnostic_artifacts": {},
        "warnings": [],
        "errors": [],
        "verdict": verdict,
    }


def _make_bundle(
    tmp_path: Path,
    *,
    include_health: bool = True,
    include_canonical: bool = True,
    include_chunks: bool = True,
    manifest_name: str = "demo.bundle.manifest.json",
    break_canonical_sha: bool = False,
) -> Path:
    artifacts = []

    if include_canonical:
        (tmp_path / "demo.md").write_bytes(_CANONICAL)
        sha = "0" * 64 if break_canonical_sha else _sha256(_CANONICAL)
        artifacts.append({
            "role": "canonical_md",
            "path": "demo.md",
            "content_type": "text/markdown",
            "bytes": len(_CANONICAL),
            "sha256": sha,
            "authority": "canonical_content",
            "canonicality": "content_source",
        })

    if include_chunks:
        chunks = [
            _chunk("README.md", _README_START, _README_END),
            _chunk("src/app.py", _APP_START, _APP_END),
        ]
        chunk_bytes = ("\n".join(json.dumps(c) for c in chunks) + "\n").encode("utf-8")
        (tmp_path / "demo.chunk_index.jsonl").write_bytes(chunk_bytes)
        artifacts.append({
            "role": "chunk_index_jsonl",
            "path": "demo.chunk_index.jsonl",
            "content_type": "application/x-ndjson",
            "bytes": len(chunk_bytes),
            "sha256": _sha256(chunk_bytes),
            "authority": "retrieval_index",
            "canonicality": "derived",
        })

    if include_health:
        health_bytes = json.dumps(_health_doc(), indent=2).encode("utf-8")
        (tmp_path / "demo.output_health.json").write_bytes(health_bytes)
        artifacts.append({
            "role": "output_health",
            "path": "demo.output_health.json",
            "content_type": "application/json",
            "bytes": len(health_bytes),
            "sha256": _sha256(health_bytes),
            "authority": "diagnostic_signal",
            "canonicality": "diagnostic",
        })

    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "demo-run",
        "created_at": "2026-05-20T00:00:00Z",
        "generator": {"name": "test", "version": "1.0", "config_sha256": "a" * 64},
        "artifacts": artifacts,
        "links": {},
        "capabilities": {"fts5_bm25": True, "redaction": False},
    }
    manifest_path = tmp_path / manifest_name
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

def test_produce_ok_writes_pack(tmp_path):
    manifest = _make_bundle(tmp_path)
    report = produce_agent_reading_pack(str(manifest))

    assert report["status"] == "ok"
    assert report["error_kind"] == "ok"
    assert report["errors"] == []
    out = Path(report["output_path"])
    assert out.exists()
    assert out.name == "demo.agent_reading_pack.md"
    assert report["output_sha256"] == _sha256(out.read_bytes())
    assert report["output_bytes"] == out.stat().st_size
    assert report["health_verdict"] == "pass"
    assert report["top_file_count"] == 2
    assert report["indexed_chunk_count"] == 2


def test_pack_has_governance_and_sentinel(tmp_path):
    manifest = _make_bundle(tmp_path)
    report = produce_agent_reading_pack(str(manifest))
    body = Path(report["output_path"]).read_text(encoding="utf-8")

    assert body.startswith("<!-- ARTIFACT:agent_reading_pack VERSION:v1")
    assert "NAVIGATION, NOT TRUTH" in body
    for section in (
        "## BUNDLE_IDENTITY",
        "## READING_POLICY",
        "## ARTIFACT_ROLES",
        "## OUTPUT_HEALTH_SUMMARY",
        "## HOW_TO_SEARCH",
        "## TOP_FILES",
        "## EPISTEMIC_EMPTINESS",
    ):
        assert section in body, f"missing section {section}"


def test_pack_lists_present_artifact_roles(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()
    assert "| canonical_md | canonical_content | content_source |" in body
    assert "| chunk_index_jsonl | retrieval_index | derived |" in body
    assert "| output_health | diagnostic_signal | diagnostic |" in body


def test_pack_top_files_carry_canonical_line_ranges(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()
    assert "`README.md`" in body
    assert "`src/app.py`" in body
    # The README body starts on the canonical_md line containing "# Demo".
    expected_readme_start = _CANONICAL.count(b"\n", 0, _README_START) + 1
    assert f"[{_README_START}, {_README_END})" in body
    assert f"{expected_readme_start}–" in body  # en-dash separator


def test_pack_is_byte_deterministic(tmp_path):
    manifest = _make_bundle(tmp_path)
    r1 = produce_agent_reading_pack(str(manifest))
    r2 = produce_agent_reading_pack(str(manifest))
    assert r1["output_sha256"] == r2["output_sha256"]


def test_pack_excludes_its_own_role_on_rerun(tmp_path):
    """A re-run over a manifest that already lists the pack must not list itself."""
    manifest = _make_bundle(tmp_path)
    first = produce_agent_reading_pack(str(manifest))
    first_sha = first["output_sha256"]

    # Inject an agent_reading_pack entry into the manifest, as the pipeline does.
    data = json.loads(manifest.read_text())
    out = Path(first["output_path"])
    data["artifacts"].append({
        "role": "agent_reading_pack",
        "path": out.name,
        "content_type": "text/markdown",
        "bytes": out.stat().st_size,
        "sha256": _sha256(out.read_bytes()),
        "authority": "navigation_index",
        "canonicality": "derived",
    })
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")

    second = produce_agent_reading_pack(str(manifest))
    body = out.read_text(encoding="utf-8")
    # Self role never appears as a table row.
    assert "| agent_reading_pack |" not in body
    # And the output is byte-identical to the first run (idempotent).
    assert second["output_sha256"] == first_sha


# ---------------------------------------------------------------------------
# Integrity failures
# ---------------------------------------------------------------------------

def test_canonical_md_sha_mismatch_fails_hard(tmp_path):
    manifest = _make_bundle(tmp_path, break_canonical_sha=True)
    report = produce_agent_reading_pack(str(manifest))
    assert report["status"] == "fail"
    assert any("canonical_md" in e and "sha256 mismatch" in e for e in report["errors"])
    # No pack must be written on hard failure.
    assert not (tmp_path / "demo.agent_reading_pack.md").exists()


def test_missing_manifest_is_path_read_error(tmp_path):
    report = produce_agent_reading_pack(str(tmp_path / "nope.bundle.manifest.json"))
    assert report["status"] == "fail"
    assert report["error_kind"] == "path_read_error"


def test_empty_run_id_fails(tmp_path):
    manifest = _make_bundle(tmp_path)
    data = json.loads(manifest.read_text())
    data["run_id"] = ""
    manifest.write_text(json.dumps(data), encoding="utf-8")
    report = produce_agent_reading_pack(str(manifest))
    assert report["status"] == "fail"
    assert any("run_id" in e for e in report["errors"])


def test_manifest_without_suffix_needs_explicit_output(tmp_path):
    manifest = _make_bundle(tmp_path, manifest_name="weird_name.json")
    report = produce_agent_reading_pack(str(manifest))
    assert report["status"] == "fail"
    assert any("does not end with" in e for e in report["errors"])

    # With an explicit --output it succeeds.
    out = tmp_path / "pack.md"
    report2 = produce_agent_reading_pack(str(manifest), str(out))
    assert report2["status"] == "ok"
    assert out.exists()


def test_output_collision_with_input_is_rejected(tmp_path):
    manifest = _make_bundle(tmp_path)
    report = produce_agent_reading_pack(str(manifest), str(tmp_path / "demo.md"))
    assert report["status"] == "fail"
    assert any("collides with an input artifact" in e for e in report["errors"])


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

def test_retrieval_only_bundle_without_canonical_md(tmp_path):
    manifest = _make_bundle(tmp_path, include_canonical=False, include_health=False)
    report = produce_agent_reading_pack(str(manifest))
    assert report["status"] == "ok"
    assert report["top_file_count"] == 0
    body = Path(report["output_path"]).read_text()
    assert "`canonical_md` is absent" in body
    assert "No canonical file spans available" in body


def test_output_health_sha_mismatch_warns_not_fails(tmp_path):
    manifest = _make_bundle(tmp_path)
    data = json.loads(manifest.read_text())
    for a in data["artifacts"]:
        if a["role"] == "output_health":
            a["sha256"] = "b" * 64
    manifest.write_text(json.dumps(data), encoding="utf-8")
    report = produce_agent_reading_pack(str(manifest))
    assert report["status"] == "ok"
    assert any("output_health" in w and "sha256 mismatch" in w for w in report["warnings"])


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def test_compute_top_files_pure(tmp_path):
    chunks = [
        _chunk("README.md", _README_START, _README_END),
        _chunk("src/app.py", _APP_START, _APP_END),
        _chunk("src/app.py", _APP_START, _APP_START + 5),  # second chunk for app.py
    ]
    chunk_path = tmp_path / "c.jsonl"
    chunk_path.write_text("\n".join(json.dumps(c) for c in chunks) + "\n")

    top, repos, count = compute_top_files(chunk_path, _CANONICAL, "demo.md")
    assert count == 3
    assert repos == ["demo"]
    # app.py has 2 chunks → ranks first.
    assert top[0].path == "src/app.py"
    assert top[0].chunk_count == 2
    assert top[0].start_byte == _APP_START
    assert top[0].end_byte == _APP_END


def test_summarize_health_extracts_fields():
    summary = summarize_health(_health_doc(verdict="warn"))
    assert summary.present is True
    assert summary.verdict == "warn"
    assert summary.chunk_count == 2
    assert summary.fts_content_non_empty is True


def test_render_is_pure_from_model():
    model = PackModel(
        run_id="r1",
        created_at="2026-05-20T00:00:00Z",
        generator_name="g",
        generator_version="1",
        redaction=False,
        fts5_bm25=True,
        artifacts=(),
        health=HealthSummary(present=False),
        top_files=(),
        indexed_chunk_count=0,
        repo_ids=(),
        canonical_md_path=None,
        chunk_index_path=None,
        dump_index_path=None,
        sqlite_index_path=None,
        citation_map_path=None,
        absent_notes=("note one",),
    )
    body = render_agent_reading_pack(model)
    assert "run_id: `r1`" in body
    assert "note one" in body
    assert body.endswith("\n")
