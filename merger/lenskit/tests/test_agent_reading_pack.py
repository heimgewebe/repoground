"""
Unit tests for core/agent_reading_pack.py (the agent_reading_pack producer).

Uses self-contained synthetic bundle manifests so the tests do not depend on the
full merge pipeline. The pipeline-level emission is covered separately in
test_bundle_manifest_integration.py.
"""
import hashlib
import json
import re
from pathlib import Path

from merger.lenskit.core.agent_reading_pack import (
    HealthSummary,
    PackModel,
    _md_cell,
    compute_top_files,
    produce_agent_reading_pack,
    render_agent_reading_pack,
    summarize_health,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _section(body: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing section {heading}"
    return match.group(1)


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


def _claim_evidence_map_doc() -> dict:
    return {
        "kind": "lenskit.claim_evidence_map",
        "version": "1.0",
        "authority": "navigation_index",
        "canonicality": "derived",
        "risk_class": "evidence_index",
        "source": {
            "registry_path": "docs/doc-freshness-registry.yml",
            "registry_sha256": "a" * 64,
            "generated_at": "2026-05-31T00:00:00Z",
        },
        "does_not_establish": [
            "truth",
            "sufficiency",
            "causality",
            "completeness",
            "freshness_beyond_last_verified",
        ],
        "claims": [
            {
                "id": "a",
                "claim": "A",
                "doc": "docs/a.md",
                "locator": "A",
                "status": "done",
                "normative": False,
                "owner": "x",
                "last_verified": "2026-05-31",
                "requires_live_check": False,
                "evidence_refs": [{"kind": "symbol", "target": "x.py::A"}],
                "relation": "declared_evidence_ref",
                "does_not_establish": [
                    "truth",
                    "sufficiency",
                    "causality",
                    "completeness",
                ],
            },
            {
                "id": "b",
                "claim": "B",
                "doc": "docs/b.md",
                "locator": "B",
                "status": "partial",
                "normative": False,
                "owner": "y",
                "last_verified": "2026-05-31",
                "requires_live_check": True,
                "evidence_refs": [
                    {
                        "kind": "text",
                        "target": "y.py::open marker",
                        "implies": "open",
                    }
                ],
                "relation": "declared_evidence_ref",
                "does_not_establish": [
                    "truth",
                    "sufficiency",
                    "causality",
                    "completeness",
                ],
            },
        ],
    }


def _make_bundle(
    tmp_path: Path,
    *,
    include_health: bool = True,
    include_canonical: bool = True,
    include_chunks: bool = True,
    include_claim_evidence_map: bool = False,
    claim_absence_reason: str | None = None,
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

    if include_claim_evidence_map:
        claim_map_bytes = json.dumps(_claim_evidence_map_doc(), indent=2).encode("utf-8")
        (tmp_path / "demo.claim_evidence_map.json").write_bytes(claim_map_bytes)
        artifacts.append({
            "role": "claim_evidence_map_json",
            "path": "demo.claim_evidence_map.json",
            "content_type": "application/json",
            "bytes": len(claim_map_bytes),
            "sha256": _sha256(claim_map_bytes),
            "authority": "navigation_index",
            "canonicality": "derived",
        })

    links = {}
    if claim_absence_reason is not None:
        links["claim_evidence_map_absence_reason"] = claim_absence_reason

    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "demo-run",
        "created_at": "2026-05-20T00:00:00Z",
        "generator": {"name": "test", "version": "1.0", "config_sha256": "a" * 64},
        "artifacts": artifacts,
        "links": links,
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

    assert body.startswith("<!-- ARTIFACT:agent_reading_pack VERSION:v1.1")
    assert "NAVIGATION, NOT TRUTH" in body
    for section in (
        "## BUNDLE_IDENTITY",
        "## READING_POLICY",
        "## REQUIRED_READING_BY_TASK",
        "## WHEN_CANONICAL_MD_ONLY_IS_INSUFFICIENT",
        "## SIDECAR_USAGE_RULES",
        "## ANSWER_COMPLIANCE_CHECKLIST",
        "## DO_NOT_CLAIM",
        "## ARTIFACT_ROLES",
        "## OUTPUT_HEALTH_SUMMARY",
        "## HOW_TO_SEARCH",
        "## TOP_CHUNK_SPANS",
        "## EPISTEMIC_EMPTINESS",
    ):
        assert section in body, f"missing section {section}"


def test_pack_front_door_task_profiles_and_artifact_roles(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()

    for task_profile in (
        "basic_repo_question",
        "pr_review",
        "roadmap_status_claim",
        "artifact_surface_review",
        "retrieval_quality_review",
    ):
        assert f"`{task_profile}`" in body

    for role in (
        "canonical_md",
        "citation_map_jsonl",
        "claim_evidence_map_json",
        "post_emit_health",
        "bundle_surface_validation",
        "output_health",
        "retrieval_eval_json",
        "chunk_index_jsonl",
        "sqlite_index",
    ):
        assert f"`{role}`" in body


def test_pack_front_door_preserves_authority_boundaries(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()

    assert "The only source of truth is `canonical_md`" in body
    assert "authority=navigation_index" in body
    assert "canonicality=derived" in body
    assert "`claim_evidence_map_json` is an evidence-navigation index, not truth" in body
    assert "`post_emit_health` is post-emit surface diagnosis, not repo understanding" in body
    assert "`bundle_surface_validation` is surface coherence validation, not claim truth" in body
    assert "`output_health` is a pre-/emit diagnostic signal" in body
    assert "`sqlite_index` is runtime cache/search support, not authority" in body


def test_agent_pack_retrieval_quality_review_mentions_miss_taxonomy(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()

    # The retrieval-quality-review profile and its required eval artifact stay intact.
    assert "`retrieval_quality_review`" in body
    required_section = _section(body, "REQUIRED_READING_BY_TASK")
    assert "`retrieval_quality_review`" in required_section
    assert "`retrieval_eval_json`" in required_section

    # The pack now points reviewers at the existing miss_taxonomy diagnostic and
    # keeps its boundary: the taxonomy is diagnostic only, not proof.
    rules = _section(body, "SIDECAR_USAGE_RULES")
    assert "`retrieval_eval_json`" in rules
    assert "miss_taxonomy" in rules
    assert "diagnostic only" in rules
    assert "does not prove" in rules


def test_pack_do_not_claim_lists_prohibited_claim_classes(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()
    section = _section(body, "DO_NOT_CLAIM")

    for claim_class in (
        "repo_understood",
        "claims_true",
        "answer_safe_without_citations",
        "test_sufficiency",
        "runtime_correctness",
        "review_complete",
        "change_impact",
        "forensic_ready",
        "all_relevant_context_used",
        "regression_absence",
    ):
        assert f"`{claim_class}`" in section

    assert "health reports" in section
    assert "surface validation" in section
    assert "sidecars do not prove" in section
    assert "relation or path proximity" in section
    assert "change impact" in section


def test_pack_answer_compliance_checklist_is_declarative(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()

    assert "Lenskit consumption:" in body
    for field in (
        "task_profile",
        "required_artifacts_checked",
        "sidecars_used",
        "canonical_ranges_or_citations_used",
        "sidecars_not_used_and_why",
        "epistemic_gaps",
        "does_not_establish",
    ):
        assert f"- {field}:" in body
    assert "declaration aid, not proof" in body


def test_agent_reading_pack_surfaces_agent_consumption_contract(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()

    assert "## AGENT_CONSUMPTION_CONTRACT" in body
    section = _section(body, "AGENT_CONSUMPTION_CONTRACT")
    # Backtick-insensitive: surfaces are rendered as inline code spans.
    flat = section.replace("`", "")
    for needle in (
        "agent_entry_manifest",
        "lenskit.agent_entry_manifest",
        "required_reading_protocol",
        "lenskit.required_reading_protocol",
        "agent_consumption_trace",
        "lenskit.agent_consumption_trace",
        "ANSWER_COMPLIANCE_CHECKLIST",
        "export_safety_report",
        "lenskit.export_safety_report",
        "canonical_md remains the only content truth",
    ):
        assert needle in flat, f"missing {needle!r} in AGENT_CONSUMPTION_CONTRACT"


def test_agent_reading_pack_consumption_contract_preserves_non_claims(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()
    section = _section(body, "AGENT_CONSUMPTION_CONTRACT")

    assert "does not establish" in section
    for token in (
        "repo_understood",
        "answer_safe_without_citations",
        "claims_true",
        "all_relevant_context_used",
        "secret_absence",
        "pii_absence",
        "forensic_ready",
    ):
        assert token in section, f"non-claim {token!r} missing from consumption contract"


def test_agent_reading_pack_consumption_contract_does_not_add_positive_truth_claims(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()
    section = _section(body, "AGENT_CONSUMPTION_CONTRACT")

    # Only positive machine-readable assertions are forbidden; negated prose is fine.
    for forbidden in (
        "repo_understood: true",
        "claims_true: true",
        "forensic_ready: true",
        "secret_absence: true",
        "pii_absence: true",
        "answer_safe_without_citations: true",
        "verified: true",
        "safe: true",
        "complete: true",
    ):
        assert forbidden not in section, f"unexpected positive claim {forbidden!r}"


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


def test_canonical_md_missing_sha_fails_hard(tmp_path):
    """A truth anchor without a verifiable expected hash must fail (missing check)."""
    manifest = _make_bundle(tmp_path)
    data = json.loads(manifest.read_text())
    for a in data["artifacts"]:
        if a["role"] == "canonical_md":
            del a["sha256"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    report = produce_agent_reading_pack(str(manifest))
    assert report["status"] == "fail"
    assert any("canonical_md" in e and "sha256" in e for e in report["errors"])
    assert not (tmp_path / "demo.agent_reading_pack.md").exists()


def test_chunk_index_invalid_sha_fails_hard(tmp_path):
    manifest = _make_bundle(tmp_path)
    data = json.loads(manifest.read_text())
    for a in data["artifacts"]:
        if a["role"] == "chunk_index_jsonl":
            a["sha256"] = "not-a-valid-hash"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    report = produce_agent_reading_pack(str(manifest))
    assert report["status"] == "fail"
    assert any("chunk_index" in e and "sha256" in e for e in report["errors"])


def test_how_to_search_resolves_range_against_bundle_manifest(tmp_path):
    """range get --manifest must point at the bundle manifest, never canonical_md."""
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()
    assert f'range get --manifest "{manifest.name}"' in body
    # canonical_md is not a manifest and must not be used as the range target.
    assert 'range get --manifest "demo.md"' not in body


def test_how_to_search_uses_absolute_manifest_when_output_is_elsewhere(tmp_path):
    """When --output is in a different directory, render the absolute manifest path."""
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    manifest = _make_bundle(bundle_dir)
    out_dir = tmp_path / "export"
    out_dir.mkdir()
    out = out_dir / "custom_pack.md"
    report = produce_agent_reading_pack(str(manifest), str(out))
    assert report["status"] == "ok"
    body = out.read_text(encoding="utf-8")
    assert f'range get --manifest "{manifest.resolve()}"' in body
    # The bare filename alone is not useful when co-location is gone.
    assert f'range get --manifest "{manifest.name}"' not in body


def test_stale_output_preserved_on_missing_manifest(tmp_path):
    """A pre-load input error must not delete an existing default output."""
    stale = tmp_path / "ghost.agent_reading_pack.md"
    stale.write_text("stale pack\n", encoding="utf-8")
    report = produce_agent_reading_pack(str(tmp_path / "ghost.bundle.manifest.json"))
    assert report["status"] == "fail"
    assert report["error_kind"] == "path_read_error"
    assert stale.exists(), "missing-manifest input error must not delete existing output"


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


def test_output_collision_with_unverified_manifest_artifact_is_rejected(tmp_path):
    """--output must not overwrite a manifest-listed artifact that fails soft verification."""
    manifest = _make_bundle(tmp_path)
    data = json.loads(manifest.read_text())
    output_health_path = None
    for a in data["artifacts"]:
        if a["role"] == "output_health":
            a["sha256"] = "not-a-valid-hash"  # soft-invalid → never added via verification
            output_health_path = tmp_path / a["path"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert output_health_path is not None
    report = produce_agent_reading_pack(str(manifest), str(output_health_path))
    assert report["status"] == "fail"
    assert any("collides with an input artifact" in e for e in report["errors"])
    # The protected input file must survive the rejected write.
    assert output_health_path.exists()


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
    body = Path(report["output_path"]).read_text(encoding="utf-8")
    assert "`output_health` is present but failed verification or parsing" in body
    assert "health summary suppressed" in body
    assert "`output_health` is absent" not in body


def _inject_artifact(manifest: Path, role: str, filename: str, content: bytes, *, bad_sha: bool = False) -> None:
    """Write a file and inject a manifest entry, optionally with a broken sha256."""
    path = manifest.parent / filename
    path.write_bytes(content)
    sha = ("c" * 64) if bad_sha else _sha256(content)
    data = json.loads(manifest.read_text())
    data["artifacts"].append({
        "role": role,
        "path": filename,
        "content_type": "application/octet-stream",
        "bytes": len(content),
        "sha256": sha,
        "authority": "runtime_cache",
        "canonicality": "derived",
    })
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_invalid_sqlite_index_suppresses_fts_command(tmp_path):
    """A sqlite_index with a bad sha256 must warn and suppress the FTS command."""
    manifest = _make_bundle(tmp_path)
    _inject_artifact(manifest, "sqlite_index", "demo.sqlite", b"fake-db", bad_sha=True)
    report = produce_agent_reading_pack(str(manifest))
    assert report["status"] == "ok"
    assert any("sqlite_index" in w and "sha256" in w for w in report["warnings"])
    body = Path(report["output_path"]).read_text(encoding="utf-8")
    assert "query --index" not in body
    assert "failed verification" in body
    assert "full-text search command suppressed" in body


def test_invalid_citation_map_suppresses_citation_guidance(tmp_path):
    """A citation_map_jsonl with a bad sha256 must warn and suppress stable-citation guidance."""
    manifest = _make_bundle(tmp_path)
    _inject_artifact(manifest, "citation_map_jsonl", "demo.citation_map.jsonl", b"", bad_sha=True)
    report = produce_agent_reading_pack(str(manifest))
    assert report["status"] == "ok"
    assert any("citation_map" in w and "sha256" in w for w in report["warnings"])
    body = Path(report["output_path"]).read_text(encoding="utf-8")
    assert "Stable citations" not in body
    assert "failed verification" in body
    assert "citation guidance suppressed" in body


def test_claim_evidence_map_summary_present_when_artifact_is_available(tmp_path):
    manifest = _make_bundle(tmp_path, include_claim_evidence_map=True)
    report = produce_agent_reading_pack(str(manifest))
    assert report["status"] == "ok"

    body = Path(report["output_path"]).read_text(encoding="utf-8")
    assert "## CLAIM_EVIDENCE_MAP_SUMMARY" in body
    assert "- claims: 2" in body
    assert "- evidence_refs: 2" in body
    assert "- requires_live_check: 1" in body
    assert "navigation/evidence index, not truth" in body
    assert "`claim_evidence_map` is absent in this bundle" not in body


def test_claim_evidence_map_absence_keeps_epistemic_note(tmp_path):
    manifest = _make_bundle(tmp_path, claim_absence_reason="no_registry")
    report = produce_agent_reading_pack(str(manifest))
    assert report["status"] == "ok"

    body = Path(report["output_path"]).read_text(encoding="utf-8")
    assert "`claim_evidence_map_json` is absent" in body
    assert "`claim_evidence_map` is absent in this bundle" in body
    assert "reason=no_registry" in body


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
        bundle_manifest_path="demo.bundle.manifest.json",
        canonical_md_path=None,
        chunk_index_path=None,
        dump_index_path=None,
        sqlite_index_path=None,
        citation_map_path=None,
        claim_evidence_map_path=None,
        claim_count=None,
        claim_evidence_ref_count=None,
        claim_requires_live_check_count=None,
        absent_notes=("note one",),
    )
    body = render_agent_reading_pack(model)
    assert "run_id: `r1`" in body
    assert "note one" in body
    assert body.endswith("\n")


def test_md_cell_none_renders_dash():
    assert _md_cell(None) == "—"


def test_md_cell_empty_string_renders_dash():
    assert _md_cell("") == "—"


def test_md_cell_whitespace_only_renders_dash():
    assert _md_cell("   ") == "—"


def test_md_cell_nonempty_preserved():
    assert _md_cell("hello") == "hello"


def test_md_cell_escapes_pipe_and_newline():
    assert _md_cell("a|b\nc") == "a\\|b c"


def test_compute_top_files_prefers_canonical_range_repo_id(tmp_path):
    """When canonical_range.repo_id and search_keys.repo_id agree, the repo_id is used."""
    # Both sources present, same value — non-conflict case with both present.
    chunk = _chunk("README.md", _README_START, _README_END, repo="shared-repo")
    chunk["canonical_range"]["repo_id"] = "shared-repo"
    chunk_path = tmp_path / "c.jsonl"
    chunk_path.write_text(json.dumps(chunk) + "\n")
    top, repos, count = compute_top_files(chunk_path, _CANONICAL, "demo.md")
    assert count == 1
    assert top[0].repo_id == "shared-repo"
    assert "shared-repo" in repos


def test_compute_top_files_uses_canonical_range_repo_id_when_no_fallback(tmp_path):
    """canonical_range.repo_id is used when search_keys is absent."""
    chunk = _chunk("README.md", _README_START, _README_END)
    del chunk["search_keys"]
    chunk["canonical_range"]["repo_id"] = "range-only-repo"
    chunk_path = tmp_path / "c.jsonl"
    chunk_path.write_text(json.dumps(chunk) + "\n")
    top, repos, count = compute_top_files(chunk_path, _CANONICAL, "demo.md")
    assert count == 1
    assert top[0].repo_id == "range-only-repo"
    assert "range-only-repo" in repos


def test_compute_top_files_conflict_repo_id_is_omitted(tmp_path):
    """Conflicting canonical_range.repo_id and search_keys.repo_id → repo_id=None."""
    chunk = _chunk("README.md", _README_START, _README_END, repo="fallback-repo")
    chunk["canonical_range"]["repo_id"] = "canonical-repo"
    chunk_path = tmp_path / "c.jsonl"
    chunk_path.write_text(json.dumps(chunk) + "\n")
    top, repos, count = compute_top_files(chunk_path, _CANONICAL, "demo.md")
    assert count == 1
    assert top[0].repo_id is None  # conflict → conservative omission
    assert "canonical-repo" in repos
    assert "fallback-repo" in repos


def test_compute_top_files_conflicting_fallback_repo_ids_are_omitted(tmp_path):
    """search_keys.repo_id and chunk.repo conflict without canonical_range.repo_id → repo_id=None."""
    chunk = _chunk("README.md", _README_START, _README_END, repo="search-repo")
    chunk["repo"] = "chunk-repo"  # different from search_keys.repo_id
    # No canonical_range.repo_id present.
    chunk_path = tmp_path / "c.jsonl"
    chunk_path.write_text(json.dumps(chunk) + "\n")
    top, repos, count = compute_top_files(chunk_path, _CANONICAL, "demo.md")
    assert count == 1
    assert top[0].repo_id is None  # fallback conflict — conservative
    # Both candidates are still tracked in the global repos set.
    assert "search-repo" in repos
    assert "chunk-repo" in repos


# ---------------------------------------------------------------------------
# A1 Begriffshärtung: TOP_FILES → TOP_CHUNK_SPANS + does_not_prove governance
# ---------------------------------------------------------------------------

def test_agent_pack_uses_top_chunk_spans(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()
    assert "## TOP_CHUNK_SPANS" in body


def test_agent_pack_no_top_files_heading(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()
    assert "## TOP_FILES" not in body


def test_agent_pack_declares_does_not_prove(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()
    assert "does_not_prove" in body
    assert "semantic_importance" in body
    assert "architecture_truth" in body
    assert "complete_context" in body


def test_agent_pack_governance_block_fields(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()
    assert '"risk_class": "navigation"' in body
    assert '"may_cite": false' in body
    assert '"must_resolve_to": "role_specific_authority"' in body


def test_agent_pack_no_important_language(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()
    for forbidden in ["most important", "wichtigste", "top-level architecture"]:
        assert forbidden not in body.lower(), f"forbidden phrase in pack: {forbidden!r}"


def test_agent_pack_has_no_top_level_architecture(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()
    assert "top-level architecture" not in body.lower()


def test_agent_pack_governance_block_is_valid_json(tmp_path):
    manifest = _make_bundle(tmp_path)
    body = Path(produce_agent_reading_pack(str(manifest))["output_path"]).read_text()
    match = re.search(r"```json\n(\{.*?\})\n```", body, re.DOTALL)
    assert match, "missing governance JSON block"
    data = json.loads(match.group(1))
    assert data["artifact"] == "agent_reading_pack"
    assert data["applies_to"] == "TOP_CHUNK_SPANS"
    assert data["authority"] == "navigation_index"
    assert data["canonicality"] == "derived"
    assert data["risk_class"] == "navigation"
    assert data["may_cite"] is False
    assert data["must_resolve_to"] == "role_specific_authority"
    assert data["does_not_prove"] == [
        "semantic_importance",
        "architecture_truth",
        "complete_context",
    ]
