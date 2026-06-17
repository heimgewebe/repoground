"""Shared test fixtures for bundle and health validations.

This module provides deterministic, reusable fixture builders for output health,
post-emit health, and bundle surface validation tests. It replaces private cross-imports
between test modules while preserving exactly their established semantics.
"""

import contextlib
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from merger.lenskit.core.post_emit_health import derive_post_health_path


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_file(path: Path, data: bytes) -> str:
    path.write_bytes(data)
    return _sha256_bytes(data)


def make_chunk_jsonl(tmp_path: Path, chunks: list[dict]) -> tuple[Path, str]:
    content = "\n".join(json.dumps(c) for c in chunks) + "\n"
    data = content.encode("utf-8")
    p = tmp_path / "test.chunk_index.jsonl"
    sha = _write_file(p, data)
    return p, sha


def make_canonical_md(tmp_path: Path) -> tuple[Path, str]:
    data = b"# Test merge\n\nSome content.\n"
    p = tmp_path / "test.md"
    sha = _write_file(p, data)
    return p, sha


def make_dump_index(tmp_path: Path, canonical_name: str, chunk_name: str) -> Path:
    p = tmp_path / "test.dump_index.json"
    dump = {
        "contract": "dump-index",
        "artifacts": {
            "canonical_md": {
                "role": "canonical_md",
                "path": canonical_name,
            },
            "chunk_index_jsonl": {
                "role": "chunk_index_jsonl",
                "path": chunk_name,
            },
        },
    }
    p.write_text(json.dumps(dump), encoding="utf-8")
    return p


def make_sqlite(
    tmp_path: Path, chunks_rows: list[dict], fts_rows: list[dict] | None = None
) -> Path:
    db_path = tmp_path / "test.index.sqlite"
    with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
        c = conn.cursor()
        c.execute("CREATE TABLE chunks (id TEXT PRIMARY KEY, content TEXT, path TEXT)")
        try:
            c.execute(
                "CREATE VIRTUAL TABLE chunks_fts USING fts5("
                "chunk_id, content, path_tokens)"
            )
        except sqlite3.OperationalError as e:
            if "no such module: fts5" in str(e).lower():
                pytest.skip("SQLite FTS5 not available")
            raise

        for row in chunks_rows:
            c.execute(
                "INSERT INTO chunks VALUES (?, ?, ?)",
                (row["id"], row["content"], row["path"]),
            )

        if fts_rows is None:
            fts_rows = chunks_rows
        for row in fts_rows:
            c.execute(
                "INSERT INTO chunks_fts VALUES (?, ?, ?)",
                (row["id"], row["content"], row["path"]),
            )

        conn.commit()
    return db_path


def make_output_health_kwargs(
    *,
    tmp_path: Path,
    chunks: list[dict] | None = None,
    with_sqlite: bool = True,
    with_manifest: bool = True,
) -> dict:
    if chunks is None:
        chunks = [{"id": "c1", "content": "hello world", "path": "test/a.md"}]

    canonical_md_path, canonical_md_sha = make_canonical_md(tmp_path)
    chunk_index_path, chunk_sha = make_chunk_jsonl(tmp_path, chunks)
    dump_index_path = make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )
    sqlite_index_path = make_sqlite(tmp_path, chunks) if with_sqlite else None

    return dict(
        run_id="run-test-1",
        stem="test",
        primary_manifest_path=dump_index_path if with_manifest else None,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=sqlite_index_path,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_sha,
    )


# --- Post-Emit Health Fixtures ---

_CANONICAL = b"# repo: demo\n\n## file: a.py\nx = 1\n"


def make_post_emit_bundle(
    tmp_path: Path,
    *,
    include_pack: bool = True,
    include_health: bool = True,
    include_citation: bool = False,
    health_verdict: str = "pass",
    health_checks: dict | None = None,
    health_top_level: dict | None = None,
    redaction: bool = False,
    pack_authority: str = "navigation_index",
    pack_canonicality: str = "derived",
    range_key: str = "canonical_range",
    include_claim_map: bool = False,
    claim_absence_reason: str | None = None,
) -> Path:
    """Build a synthetic bundle on disk and return the manifest path.

    This exact semantics originated from test_post_emit_health.py's _make_bundle.
    """
    artifacts = []

    (tmp_path / "demo.md").write_bytes(_CANONICAL)
    artifacts.append(
        {
            "role": "canonical_md",
            "path": "demo.md",
            "content_type": "text/markdown",
            "bytes": len(_CANONICAL),
            "sha256": _sha256_bytes(_CANONICAL),
            "authority": "canonical_content",
            "canonicality": "content_source",
        }
    )

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
            "content_sha256": _sha256_bytes(_CANONICAL[_start:]),
        },
    }
    chunk_bytes = (json.dumps(chunk) + "\n").encode("utf-8")
    (tmp_path / "demo.chunk_index.jsonl").write_bytes(chunk_bytes)
    artifacts.append(
        {
            "role": "chunk_index_jsonl",
            "path": "demo.chunk_index.jsonl",
            "content_type": "application/x-ndjson",
            "bytes": len(chunk_bytes),
            "sha256": _sha256_bytes(chunk_bytes),
            "authority": "retrieval_index",
            "canonicality": "derived",
        }
    )

    if include_health:
        checks = {"chunk_count": 1}
        if health_checks:
            checks.update(health_checks)
        health_doc = {
            "kind": "lenskit.output_health",
            "version": "1.0",
            "run_id": "demo-run",
            "created_at": "2026-05-20T00:00:00Z",
            "stem": "demo",
            "checks": checks,
            "diagnostic_artifacts": {},
            "warnings": [],
            "errors": [],
            "verdict": health_verdict,
        }
        if health_top_level:
            health_doc.update(health_top_level)
        health_bytes = json.dumps(health_doc, indent=2).encode("utf-8")
        (tmp_path / "demo.output_health.json").write_bytes(health_bytes)
        artifacts.append(
            {
                "role": "output_health",
                "path": "demo.output_health.json",
                "content_type": "application/json",
                "bytes": len(health_bytes),
                "sha256": _sha256_bytes(health_bytes),
                "authority": "diagnostic_signal",
                "canonicality": "diagnostic",
            }
        )

    if include_pack:
        pack_bytes = (
            b"<!-- ARTIFACT:agent_reading_pack VERSION:v1 -->\n"
            b"# Pack\n"
            b"NAVIGATION, NOT TRUTH\n"
        )
        (tmp_path / "demo.agent_reading_pack.md").write_bytes(pack_bytes)
        artifacts.append(
            {
                "role": "agent_reading_pack",
                "path": "demo.agent_reading_pack.md",
                "content_type": "text/markdown",
                "bytes": len(pack_bytes),
                "sha256": _sha256_bytes(pack_bytes),
                "authority": pack_authority,
                "canonicality": pack_canonicality,
            }
        )

    if include_citation:
        cit_bytes = b'{"citation_id":"cit_0000000000000000"}\n'
        (tmp_path / "demo.citation_map.jsonl").write_bytes(cit_bytes)
        artifacts.append(
            {
                "role": "citation_map_jsonl",
                "path": "demo.citation_map.jsonl",
                "content_type": "application/x-ndjson",
                "bytes": len(cit_bytes),
                "sha256": _sha256_bytes(cit_bytes),
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
                    "id": "x",
                    "claim": "Demo claim",
                    "doc": "docs/proof.md",
                    "locator": "L1",
                    "status": "done",
                    "normative": False,
                    "owner": "lenskit",
                    "last_verified": "2026-05-20",
                    "requires_live_check": True,
                    "evidence_refs": [
                        {"kind": "symbol", "target": "docs/proof.md::L1"}
                    ],
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
                "sha256": _sha256_bytes(claim_bytes),
                "authority": "navigation_index",
                "canonicality": "derived",
                "regenerable": True,
                "staleness_sensitive": True,
                "contract": {"id": "claim-evidence-map", "version": "v1"},
                "interpretation": {"mode": "contract"},
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
    manifest_path = tmp_path / "demo.bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


# --- Bundle Surface Fixtures ---

_PACK_V1_1_FRONT_DOOR = (
    "<!-- ARTIFACT:agent_reading_pack VERSION:v1.1 "
    "AUTHORITY:navigation_index CANONICALITY:derived -->\n"
    "## REQUIRED_READING_BY_TASK\n"
    "## WHEN_CANONICAL_MD_ONLY_IS_INSUFFICIENT\n"
    "## SIDECAR_USAGE_RULES\n"
    "## ANSWER_COMPLIANCE_CHECKLIST\n"
    "## DO_NOT_CLAIM\n"
    "- `change_impact` — relation or path proximity alone does not "
    "prove change impact.\n"
)
_PACK_SUMMARY_PRESENT = _PACK_V1_1_FRONT_DOOR + (
    "## CLAIM_EVIDENCE_MAP_SUMMARY\n"
    "- artifact: `x.claim_evidence_map.json`\n"
    "- claims: 3\n"
)


def make_surface_manifest(
    tmp_path: Path,
    *,
    claim_present: bool,
    absence_reason: str | None = None,
    pack_text: str = _PACK_SUMMARY_PRESENT,
    include_pack: bool = True,
    include_runtime: bool = True,
    include_post_health: bool = True,
    post_health_status: str = "pass",
    include_output_health: bool = True,
) -> Path:
    """Write a synthetic but structurally valid bundle manifest + referenced files.

    This exact semantics originated from test_bundle_surface_validate.py's _make_manifest.
    """
    manifest_path = tmp_path / "x.bundle.manifest.json"
    artifacts = []
    _DUMMY_SHA = "0" * 64

    (tmp_path / "x.md").write_text("# canonical\n", encoding="utf-8")
    artifacts.append(
        {"role": "canonical_md", "path": "x.md", "sha256": _DUMMY_SHA, "bytes": 12}
    )

    if include_pack:
        (tmp_path / "x.pack.md").write_text(pack_text, encoding="utf-8")
        artifacts.append(
            {
                "role": "agent_reading_pack",
                "path": "x.pack.md",
                "sha256": _DUMMY_SHA,
                "bytes": 1,
            }
        )
    if include_output_health:
        (tmp_path / "x.oh.json").write_text('{"verdict": "pass"}', encoding="utf-8")
        artifacts.append(
            {
                "role": "output_health",
                "path": "x.oh.json",
                "sha256": _DUMMY_SHA,
                "bytes": 1,
            }
        )
    if claim_present:
        (tmp_path / "x.cem.json").write_text("{}", encoding="utf-8")
        artifacts.append(
            {
                "role": "claim_evidence_map_json",
                "path": "x.cem.json",
                "sha256": _DUMMY_SHA,
                "bytes": 2,
            }
        )

    links = {}
    if absence_reason is not None:
        links["claim_evidence_map_absence_reason"] = absence_reason

    generator = {"name": "rlens", "version": "dev", "config_sha256": "a" * 64}
    if include_runtime:
        generator["runtime"] = {
            "module": "merger.lenskit.core.merge",
            "python_version": "3.11.0",
        }

    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-xyz",
        "created_at": "2026-06-02T00:00:00Z",
        "generator": generator,
        "artifacts": artifacts,
        "links": links,
        "capabilities": {"redaction": False},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if include_post_health:
        # A persisted (unregistered) post_emit_health sidecar with a known status.
        derive_post_health_path(manifest_path).write_text(
            json.dumps(
                {
                    "kind": "lenskit.post_emit_health",
                    "version": "1.0",
                    "status": post_health_status,
                }
            ),
            encoding="utf-8",
        )
    return manifest_path
