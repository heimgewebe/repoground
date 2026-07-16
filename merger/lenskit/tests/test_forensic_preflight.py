import hashlib
import json
import shutil
from pathlib import Path

from merger.lenskit.cli.main import main
from merger.lenskit.core import forensic_preflight as forensic_preflight_module
from merger.lenskit.core.forensic_preflight import compute_forensic_preflight
from merger.lenskit.core.post_emit_health import compute_post_emit_health, derive_post_health_path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_bundle(
    tmp_path: Path,
    *,
    include_claim_map: bool,
    include_citation_map: bool = True,
    redaction: bool = True,
    claim_absence_reason: str | None = None,
) -> Path:
    canonical = b"# repo: demo\n\n## file: a.py\nx = 1\n"
    (tmp_path / "demo.md").write_bytes(canonical)
    start = canonical.index(b"x = 1")
    chunk = {
        "chunk_id": "c0",
        "path": "a.py",
        "canonical_range": {
            "artifact_role": "canonical_md",
            "repo_id": "demo",
            "file_path": "demo.md",
            "start_byte": start,
            "end_byte": len(canonical),
            "start_line": 4,
            "end_line": 4,
            "content_sha256": _sha256(canonical[start:]),
        },
    }
    chunk_bytes = (json.dumps(chunk) + "\n").encode("utf-8")
    (tmp_path / "demo.chunk_index.jsonl").write_bytes(chunk_bytes)

    artifacts = [
        {
            "role": "canonical_md",
            "path": "demo.md",
            "content_type": "text/markdown",
            "bytes": len(canonical),
            "sha256": _sha256(canonical),
            "authority": "canonical_content",
            "canonicality": "content_source",
        },
        {
            "role": "chunk_index_jsonl",
            "path": "demo.chunk_index.jsonl",
            "content_type": "application/x-ndjson",
            "bytes": len(chunk_bytes),
            "sha256": _sha256(chunk_bytes),
            "authority": "retrieval_index",
            "canonicality": "derived",
        },
    ]

    if include_citation_map:
        citation = b'{"citation_id":"cit_0000000000000000"}\n'
        (tmp_path / "demo.citation_map.jsonl").write_bytes(citation)
        artifacts.append(
            {
                "role": "citation_map_jsonl",
                "path": "demo.citation_map.jsonl",
                "content_type": "application/x-ndjson",
                "bytes": len(citation),
                "sha256": _sha256(citation),
                "authority": "navigation_index",
                "canonicality": "derived",
                "regenerable": True,
                "staleness_sensitive": True,
                "contract": {"id": "citation-map", "version": "v1"},
                "interpretation": {"mode": "contract"},
            }
        )

    if include_claim_map:
        claim_doc = {
            "kind": "lenskit.claim_evidence_map",
            "version": "1.0",
            "authority": "navigation_index",
            "canonicality": "derived",
            "risk_class": "evidence_index",
            "source": {
                "registry_path": "docs/doc-freshness-registry.yml",
                "registry_sha256": "a" * 64,
                "generated_at": "2026-05-20T00:00:00Z",
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
                    "id": "claim-001",
                    "claim": "x = 1",
                    "doc": "a.py",
                    "locator": "line:4",
                    "status": "done",
                    "normative": False,
                    "owner": "lenskit",
                    "last_verified": "2026-05-20",
                    "requires_live_check": True,
                    "evidence_refs": [{"kind": "symbol", "target": "a.py::line-4"}],
                    "relation": "declared_evidence_ref",
                    "does_not_establish": [
                        "truth",
                        "sufficiency",
                        "causality",
                        "completeness",
                    ],
                }
            ],
        }
        claim_bytes = json.dumps(claim_doc, indent=2).encode("utf-8")
        (tmp_path / "demo.claim_evidence_map.json").write_bytes(claim_bytes)
        artifacts.append(
            {
                "role": "claim_evidence_map_json",
                "path": "demo.claim_evidence_map.json",
                "content_type": "application/json",
                "bytes": len(claim_bytes),
                "sha256": _sha256(claim_bytes),
                "authority": "navigation_index",
                "canonicality": "derived",
                "regenerable": True,
                "staleness_sensitive": True,
                "contract": {"id": "claim-evidence-map", "version": "v1"},
                "interpretation": {"mode": "contract"},
            }
        )

    pack = b"# pack\nNAVIGATION, NOT TRUTH\n"
    (tmp_path / "demo.agent_reading_pack.md").write_bytes(pack)
    artifacts.append(
        {
            "role": "agent_reading_pack",
            "path": "demo.agent_reading_pack.md",
            "content_type": "text/markdown",
            "bytes": len(pack),
            "sha256": _sha256(pack),
            "authority": "navigation_index",
            "canonicality": "derived",
        }
    )

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
        "capabilities": {"fts5_bm25": False, "redaction": redaction},
    }
    out = tmp_path / "demo.bundle.manifest.json"
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out


def _write_post_health(manifest: Path) -> Path:
    post = compute_post_emit_health(str(manifest))
    out = derive_post_health_path(manifest)
    out.write_text(json.dumps(post, indent=2), encoding="utf-8")
    return out


def test_forensic_strict_blocked_without_claim_evidence_map(tmp_path):
    manifest = _make_bundle(tmp_path, include_claim_map=False, claim_absence_reason="no_registry")
    _write_post_health(manifest)
    report = compute_forensic_preflight(str(manifest))

    assert report["status"] == "blocked"
    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["claim_evidence_map_present"]["status"] == "blocked"
    detail = by_name["claim_evidence_map_present"]["detail"]
    assert "claim_evidence_map_json missing" in detail
    assert "reason=no_registry" in detail
    assert "registry missing" in detail


def test_forensic_strict_blocked_without_citation_map(tmp_path):
    manifest = _make_bundle(tmp_path, include_claim_map=True, include_citation_map=False)
    _write_post_health(manifest)
    report = compute_forensic_preflight(str(manifest))

    assert report["status"] == "blocked"
    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["citation_map_hash_ok"]["status"] == "blocked"


def test_forensic_strict_blocked_without_post_emit_health(tmp_path):
    manifest = _make_bundle(tmp_path, include_claim_map=True)
    report = compute_forensic_preflight(str(manifest))

    assert report["status"] == "blocked"
    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["post_emit_health_present"]["status"] == "blocked"


def test_forensic_strict_blocked_when_jsonschema_unavailable(tmp_path, monkeypatch):
    manifest = _make_bundle(tmp_path, include_claim_map=True)
    _write_post_health(manifest)
    monkeypatch.setattr(forensic_preflight_module, "jsonschema", None)

    report = compute_forensic_preflight(str(manifest))

    assert report["status"] == "blocked"
    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["claim_evidence_map_schema_valid"]["status"] == "blocked"


def test_forensic_strict_fail_outranks_blocked(tmp_path):
    manifest = _make_bundle(tmp_path, include_claim_map=True)
    (tmp_path / "demo.claim_evidence_map.json").write_text('{"tampered":true}\n', encoding="utf-8")

    report = compute_forensic_preflight(str(manifest))

    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["claim_evidence_map_hash_ok"]["status"] == "fail"
    assert by_name["claim_evidence_map_schema_valid"]["status"] == "skipped"
    assert by_name["post_emit_health_present"]["status"] == "blocked"
    assert report["status"] == "fail"


def test_forensic_preflight_rejects_stale_post_emit_health(tmp_path):
    bundle_a_dir = tmp_path / "a"
    bundle_a_dir.mkdir()
    manifest_a = _make_bundle(bundle_a_dir, include_claim_map=True)
    post_health_a = _write_post_health(manifest_a)

    bundle_b_dir = tmp_path / "b"
    bundle_b_dir.mkdir()
    manifest_b = _make_bundle(bundle_b_dir, include_claim_map=True)

    report = compute_forensic_preflight(str(manifest_b), post_health_path=str(post_health_a))

    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["post_emit_health_bound_to_manifest"]["status"] == "fail"
    assert by_name["post_emit_health_pass"]["status"] == "blocked"
    assert by_name["range_citation_strict"]["status"] == "blocked"
    assert by_name["no_required_checks_skipped"]["status"] == "blocked"
    assert report["status"] in {"blocked", "fail"}


def test_forensic_preflight_rejects_adjacent_stale_post_emit_health(tmp_path):
    manifest = _make_bundle(tmp_path, include_claim_map=True)
    post_path = _write_post_health(manifest)
    post_doc = json.loads(post_path.read_text(encoding="utf-8"))
    post_doc["bundle_manifest_path"] = str(tmp_path / "other.bundle.manifest.json")
    post_doc["bundle_run_id"] = "other-run"
    post_path.write_text(json.dumps(post_doc, indent=2), encoding="utf-8")

    report = compute_forensic_preflight(str(manifest))

    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["post_emit_health_bound_to_manifest"]["status"] == "fail"
    assert by_name["post_emit_health_pass"]["status"] == "blocked"
    assert report["status"] in {"blocked", "fail"}


def test_forensic_preflight_rejects_invalid_or_wrong_manifest_hash(tmp_path):
    manifest = _make_bundle(tmp_path, include_claim_map=True)
    post_path = _write_post_health(manifest)

    for declared_hash, expected_detail in (
        ("A" * 64, "is invalid"),
        ("0" * 64, "does not match"),
    ):
        post_doc = compute_post_emit_health(str(manifest))
        post_doc["bundle_manifest_sha256"] = declared_hash
        post_path.write_text(json.dumps(post_doc, indent=2), encoding="utf-8")

        report = compute_forensic_preflight(str(manifest))
        binding = {item["name"]: item for item in report["checks"]}[
            "post_emit_health_bound_to_manifest"
        ]
        assert binding["status"] == "fail"
        assert expected_detail in binding["detail"]


def test_forensic_preflight_accepts_byte_identical_immutable_manifest_by_hash(
    tmp_path,
):
    flat = tmp_path / "flat"
    flat.mkdir()
    flat_manifest = _make_bundle(flat, include_claim_map=True)
    flat_post = _write_post_health(flat_manifest)
    post_doc = json.loads(flat_post.read_text(encoding="utf-8"))
    post_doc["bundle_manifest_sha256"] = _sha256(flat_manifest.read_bytes())
    flat_post.write_text(json.dumps(post_doc, indent=2), encoding="utf-8")

    immutable = tmp_path / "immutable"
    shutil.copytree(flat, immutable)
    immutable_manifest = immutable / flat_manifest.name

    report = compute_forensic_preflight(str(immutable_manifest))
    binding = {item["name"]: item for item in report["checks"]}[
        "post_emit_health_bound_to_manifest"
    ]
    assert binding["status"] == "pass"
    assert "hash-bound" in binding["detail"]
    assert report["status"] == "pass"


def test_forensic_strict_preflight_passes_with_all_prerequisites(tmp_path):
    manifest = _make_bundle(tmp_path, include_claim_map=True)
    _write_post_health(manifest)
    report = compute_forensic_preflight(str(manifest))

    assert report["status"] == "pass"
    assert all(item["status"] == "pass" for item in report["checks"] if item["name"] in {
        "canonical_md_hash_ok",
        "chunk_index_hash_ok",
        "citation_map_hash_ok",
        "claim_evidence_map_present",
        "claim_evidence_map_hash_ok",
        "claim_evidence_map_schema_valid",
        "post_emit_health_present",
        "post_emit_health_bound_to_manifest",
        "post_emit_health_pass",
        "range_citation_strict",
        "redaction_policy_explicit",
        "no_required_checks_skipped",
    })


def test_forensic_strict_does_not_emit_truth_verdicts(tmp_path):
    manifest = _make_bundle(tmp_path, include_claim_map=True)
    _write_post_health(manifest)
    report = compute_forensic_preflight(str(manifest))
    dumped = json.dumps(report).lower()

    assert "supported" not in dumped
    assert "proven" not in dumped
    assert "claims_true" in dumped


def test_governance_forensic_preflight_cli_json(tmp_path, capsys):
    manifest = _make_bundle(tmp_path, include_claim_map=True)
    _write_post_health(manifest)

    rc = main(["governance", "forensic-preflight", "--manifest", str(manifest), "--json"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["kind"] == "lenskit.forensic_preflight"
    assert report["status"] == "pass"
