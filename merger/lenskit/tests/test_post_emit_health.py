"""
Unit tests for core/post_emit_health.py (the post-emit bundle validator, PR A4).

Uses self-contained synthetic bundle manifests so the tests do not depend on the
full merge pipeline. The defining property: post_emit_health validates the FINAL
bundle surface (including the agent_reading_pack, which the in-pipeline
output_health cannot see) and is independent of the pre-emit output_health verdict.
"""
import hashlib
import json
from pathlib import Path

import jsonschema

from merger.lenskit.core.post_emit_health import (
    DOES_NOT_MEAN,
    compute_post_emit_health,
    derive_post_health_path,
    write_post_emit_health,
)

_CONTRACTS_DIR = Path(__file__).parent.parent / "contracts"
_POST_HEALTH_SCHEMA_PATH = _CONTRACTS_DIR / "post-emit-health.v1.schema.json"

_CANONICAL = b"# repo: demo\n\n## file: a.py\nx = 1\n"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_bundle(
    tmp_path: Path,
    *,
    include_pack: bool = True,
    include_health: bool = True,
    include_citation: bool = False,
    health_verdict: str = "pass",
    redaction: bool = False,
    pack_authority: str = "navigation_index",
    pack_canonicality: str = "derived",
    range_key: str = "canonical_range",
) -> Path:
    """Build a synthetic bundle on disk and return the manifest path."""
    artifacts = []

    (tmp_path / "demo.md").write_bytes(_CANONICAL)
    artifacts.append({
        "role": "canonical_md", "path": "demo.md", "content_type": "text/markdown",
        "bytes": len(_CANONICAL), "sha256": _sha256(_CANONICAL),
        "authority": "canonical_content", "canonicality": "content_source",
    })

    _start = _CANONICAL.index(b"x = 1")
    chunk = {
        "chunk_id": "c0",
        "path": "a.py",
        range_key: {
            "artifact_role": "canonical_md",
            "repo_id": "demo",
            "file_path": "demo.md",
            "start_byte": _start,
            "end_byte": len(_CANONICAL),
            "start_line": 4,
            "end_line": 4,
            "content_sha256": _sha256(_CANONICAL[_start:]),
        },
    }
    chunk_bytes = (json.dumps(chunk) + "\n").encode("utf-8")
    (tmp_path / "demo.chunk_index.jsonl").write_bytes(chunk_bytes)
    artifacts.append({
        "role": "chunk_index_jsonl", "path": "demo.chunk_index.jsonl",
        "content_type": "application/x-ndjson", "bytes": len(chunk_bytes),
        "sha256": _sha256(chunk_bytes),
        "authority": "retrieval_index", "canonicality": "derived",
    })

    if include_health:
        health_doc = {
            "kind": "lenskit.output_health", "version": "1.0", "run_id": "demo-run",
            "created_at": "2026-05-20T00:00:00Z", "stem": "demo",
            "checks": {"chunk_count": 1}, "diagnostic_artifacts": {},
            "warnings": [], "errors": [], "verdict": health_verdict,
        }
        health_bytes = json.dumps(health_doc, indent=2).encode("utf-8")
        (tmp_path / "demo.output_health.json").write_bytes(health_bytes)
        artifacts.append({
            "role": "output_health", "path": "demo.output_health.json",
            "content_type": "application/json", "bytes": len(health_bytes),
            "sha256": _sha256(health_bytes),
            "authority": "diagnostic_signal", "canonicality": "diagnostic",
        })

    if include_pack:
        pack_bytes = b"<!-- ARTIFACT:agent_reading_pack VERSION:v1 -->\n# Pack\nNAVIGATION, NOT TRUTH\n"
        (tmp_path / "demo.agent_reading_pack.md").write_bytes(pack_bytes)
        artifacts.append({
            "role": "agent_reading_pack", "path": "demo.agent_reading_pack.md",
            "content_type": "text/markdown", "bytes": len(pack_bytes),
            "sha256": _sha256(pack_bytes),
            "authority": pack_authority, "canonicality": pack_canonicality,
        })

    if include_citation:
        cit_bytes = b'{"citation_id":"cit_0000000000000000"}\n'
        (tmp_path / "demo.citation_map.jsonl").write_bytes(cit_bytes)
        artifacts.append({
            "role": "citation_map_jsonl", "path": "demo.citation_map.jsonl",
            "content_type": "application/x-ndjson", "bytes": len(cit_bytes),
            "sha256": _sha256(cit_bytes),
            "authority": "navigation_index", "canonicality": "derived",
            "regenerable": True, "staleness_sensitive": True,
            "contract": {"id": "citation-map", "version": "v1"},
        })

    manifest = {
        "kind": "repolens.bundle.manifest", "version": "1.0", "run_id": "demo-run",
        "created_at": "2026-05-20T00:00:00Z",
        "generator": {"name": "test", "version": "1.0", "config_sha256": "a" * 64},
        "artifacts": artifacts, "links": {},
        "capabilities": {"fts5_bm25": False, "redaction": redaction},
    }
    manifest_path = tmp_path / "demo.bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


# ---------------------------------------------------------------------------
# Required tests
# ---------------------------------------------------------------------------

def test_post_emit_health_requires_agent_pack(tmp_path):
    """A bundle without an agent_reading_pack must not silently pass."""
    manifest = _make_bundle(tmp_path, include_pack=False)
    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "blocked"
    assert report["status"] != "pass"
    assert report["agent_pack"]["present"] is False
    pack_check = next(c for c in report["checks"] if c["name"] == "agent_pack_present")
    assert pack_check["status"] == "blocked"


def test_post_emit_health_independent_of_pre_health(tmp_path):
    """output_health.verdict=pass must never imply post_emit_health.status=pass."""
    manifest = _make_bundle(tmp_path, health_verdict="pass")
    # Introduce a post-emit-only defect: corrupt the pack so its hash mismatches.
    (tmp_path / "demo.agent_reading_pack.md").write_bytes(b"tampered content not in manifest hash\n")

    report = compute_post_emit_health(str(manifest))

    # The pre-emit verdict is recorded as an observation ...
    assert report["output_health_verdict"] == "pass"
    # ... but the post-emit status is computed independently and fails.
    assert report["status"] == "fail"
    assert report["hash_mismatch_count"] >= 1
    assert report["independence_note"] == (
        "output_health.verdict=pass does not imply post_emit_health.status=pass"
    )


def test_post_emit_health_reports_evidence_level(tmp_path):
    """Evidence level is reported using the existing vocabulary."""
    manifest = _make_bundle(tmp_path)
    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "pass"
    # canonical_md + agent_reading_pack + chunk_index => navigable (no citation_map).
    assert report["evidence_level"] == "navigable"
    assert "readable" in report["evidence_levels_reached"]
    assert "navigable" in report["evidence_levels_reached"]
    assert "citable" not in report["evidence_levels_reached"]


def test_post_emit_health_detects_missing_artifact(tmp_path):
    """A manifest-declared artifact whose file is missing => fail."""
    manifest = _make_bundle(tmp_path)
    (tmp_path / "demo.chunk_index.jsonl").unlink()

    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "fail"
    assert report["missing_artifact_count"] >= 1
    paths_check = next(c for c in report["checks"] if c["name"] == "artifact_paths_exist")
    assert paths_check["status"] == "fail"


def test_post_emit_health_detects_hash_mismatch(tmp_path):
    """A file whose content no longer matches the manifest hash => fail."""
    manifest = _make_bundle(tmp_path)
    (tmp_path / "demo.md").write_bytes(_CANONICAL + b"DRIFT\n")

    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "fail"
    assert report["hash_mismatch_count"] >= 1
    hashes_check = next(c for c in report["checks"] if c["name"] == "artifact_hashes_match")
    assert hashes_check["status"] == "fail"


# ---------------------------------------------------------------------------
# Supporting coverage
# ---------------------------------------------------------------------------

def test_post_emit_health_clean_bundle_passes(tmp_path):
    manifest = _make_bundle(tmp_path)
    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "pass"
    assert report["errors"] == []
    assert report["agent_pack"]["self_role_ok"] is True
    # A clean bundle whose chunks carry canonical_range resolves a real range path.
    assert report["range_ref_resolution_status"] == "ok"
    assert "repo_understood" in report["does_not_mean"]
    assert "answer_safe_without_citations" in report["does_not_mean"]
    assert set(DOES_NOT_MEAN).issubset(set(report["does_not_mean"]))


def test_post_emit_health_range_ref_legacy_content_range_ref(tmp_path):
    """Legacy chunks using content_range_ref still resolve via the fallback."""
    manifest = _make_bundle(tmp_path, range_key="content_range_ref")
    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "pass"
    assert report["range_ref_resolution_status"] == "ok"


def test_post_emit_health_output_health_must_be_validated_not_declared(tmp_path):
    """A declared but tampered output_health must not be trusted nor boost coverage."""
    manifest = _make_bundle(tmp_path)  # includes a declared, hash-valid output_health
    # Tamper the file after the manifest (and its recorded hash) were written.
    (tmp_path / "demo.output_health.json").write_bytes(
        b'{"kind":"lenskit.output_health","verdict":"pass","tampered":true}\n'
    )

    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "fail"
    assert report["hash_mismatch_count"] >= 1
    # The verdict must NOT be read from the hash-mismatched artifact.
    assert report["output_health_verdict"] is None
    # A corrupted output_health must not contribute diagnostic coverage.
    assert "diagnostic_full" not in report["evidence_levels_reached"]


def test_post_emit_health_output_validates_against_schema(tmp_path):
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    # Build distinct bundles in fresh dirs and validate each report against schema.
    for i, kwargs in enumerate(({}, {"include_pack": False}, {"include_citation": True})):
        sub = tmp_path / f"bundle_{i}"
        sub.mkdir()
        manifest = _make_bundle(sub, **kwargs)
        report = compute_post_emit_health(str(manifest))
        jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_reports_redaction_without_enforcing(tmp_path):
    """redaction=false must be reported but must NOT cause a fail (no enforcement)."""
    manifest = _make_bundle(tmp_path, redaction=False)
    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "pass"
    assert report["redaction_status"]["redact_secrets_enabled"] is False
    assert report["redaction_status"]["enforced"] is False


def test_post_emit_health_blocked_on_missing_manifest(tmp_path):
    report = compute_post_emit_health(str(tmp_path / "nope.bundle.manifest.json"))
    assert report["status"] == "blocked"
    assert report["bundle_run_id"] is None
    # Even the early-exit blocked report must be a schema-valid artifact.
    schema = json.loads(_POST_HEALTH_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_post_emit_health_self_role_misdeclared_fails(tmp_path):
    """A pack that declares itself as a canonical/content source is a defect."""
    manifest = _make_bundle(
        tmp_path, pack_authority="canonical_content", pack_canonicality="content_source"
    )
    report = compute_post_emit_health(str(manifest))

    assert report["status"] == "fail"
    assert report["agent_pack"]["self_role_ok"] is False


def test_post_emit_health_no_require_agent_pack_relaxes_block(tmp_path):
    manifest = _make_bundle(tmp_path, include_pack=False)
    report = compute_post_emit_health(str(manifest), agent_pack_required=False)

    # Without the pack requirement the absence is not blocking; the rest is clean.
    assert report["status"] != "blocked"
    assert report["agent_pack"]["present"] is False


def test_post_emit_health_blocked_precedes_fail(tmp_path):
    """blocked takes precedence over fail: even when an inspectable defect exists,
    the absence of agent_reading_pack from the manifest makes the status blocked."""
    # Build without pack; also corrupt canonical so a hash defect is detectable.
    manifest = _make_bundle(tmp_path, include_pack=False)
    (tmp_path / "demo.md").write_bytes(_CANONICAL + b"CORRUPTION\n")

    report = compute_post_emit_health(str(manifest))

    # The hash defect is inspectable but the required certification surface is absent.
    assert report["status"] == "blocked"
    # The hash mismatch should still be captured in errors for transparency.
    assert report["hash_mismatch_count"] >= 1
    assert len(report["errors"]) >= 1


def test_write_post_emit_health_persists_unregistered_artifact(tmp_path):
    manifest = _make_bundle(tmp_path)
    manifest_before = manifest.read_text(encoding="utf-8")

    out, report = write_post_emit_health(str(manifest))

    assert out == derive_post_health_path(manifest.resolve())
    assert out.exists()
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["status"] == report["status"] == "pass"

    # Persistence must NOT mutate the bundle manifest (no registration).
    assert manifest.read_text(encoding="utf-8") == manifest_before
    data = json.loads(manifest_before)
    assert all(a["role"] != "post_emit_health" for a in data["artifacts"])
