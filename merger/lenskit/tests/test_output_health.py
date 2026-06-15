"""Tests for merger.lenskit.core.output_health."""

import hashlib
import json
import sqlite3
from pathlib import Path

import jsonschema
import pytest

from merger.lenskit.core.output_health import compute_output_health, write_output_health

_SCHEMA_PATH = (
    Path(__file__).parent.parent / "contracts" / "output-health.v1.schema.json"
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_file(path: Path, data: bytes) -> str:
    path.write_bytes(data)
    return _sha256_bytes(data)


def _make_chunk_jsonl(tmp_path: Path, chunks: list[dict]) -> tuple[Path, str]:
    content = "\n".join(json.dumps(c) for c in chunks) + "\n"
    data = content.encode("utf-8")
    p = tmp_path / "test.chunk_index.jsonl"
    sha = _write_file(p, data)
    return p, sha


def _make_canonical_md(tmp_path: Path) -> tuple[Path, str]:
    data = b"# Test merge\n\nSome content.\n"
    p = tmp_path / "test.md"
    sha = _write_file(p, data)
    return p, sha


def _make_dump_index(tmp_path: Path, canonical_name: str, chunk_name: str) -> Path:
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


def _make_sqlite(
    tmp_path: Path, chunks_rows: list[dict], fts_rows: list[dict] | None = None
) -> Path:
    db_path = tmp_path / "test.index.sqlite"
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute("CREATE TABLE chunks (id TEXT PRIMARY KEY, content TEXT, path TEXT)")
    try:
        c.execute(
            "CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id, content, path_tokens)"
        )
    except sqlite3.OperationalError as e:
        conn.close()
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
    conn.close()
    return db_path


def _build_range_ref_for_canonical(
    canonical_path: Path, start_byte: int, end_byte: int
) -> dict:
    content = canonical_path.read_bytes()[start_byte:end_byte]
    return {
        "artifact_role": "canonical_md",
        "repo_id": "repo-1",
        "file_path": canonical_path.name,
        "start_byte": start_byte,
        "end_byte": end_byte,
        "start_line": 1,
        "end_line": 1,
        "content_sha256": _sha256_bytes(content),
    }


def _base_kwargs(
    *,
    tmp_path: Path,
    chunks: list[dict] | None = None,
    with_sqlite: bool = True,
    with_manifest: bool = True,
) -> dict:
    if chunks is None:
        chunks = [{"id": "c1", "content": "hello world", "path": "test/a.md"}]

    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path, chunk_sha = _make_chunk_jsonl(tmp_path, chunks)
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )
    sqlite_index_path = _make_sqlite(tmp_path, chunks) if with_sqlite else None

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


def test_verdict_pass_when_blocking_checks_pass_and_optional_features_are_skipped(
    tmp_path,
):
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    rr = _build_range_ref_for_canonical(canonical_md_path, 0, 8)
    chunks = [
        {
            "id": "c1",
            "content": "hello world",
            "path": "test/a.md",
            "content_range_ref": rr,
        }
    ]
    chunk_index_path, chunk_sha = _make_chunk_jsonl(tmp_path, chunks)
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )
    sqlite_index_path = _make_sqlite(
        tmp_path, [{"id": "c1", "content": "hello world", "path": "test/a.md"}]
    )

    result = compute_output_health(
        run_id="run-pass",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=sqlite_index_path,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_sha,
    )

    assert result["verdict"] == "pass"
    assert result["warnings"] == []
    assert result["checks"]["manifest_present"] is True
    assert result["checks"]["range_ref_resolution_ok"] is True
    assert result["checks"]["sqlite_row_count_matches_chunk_count"] is True
    assert result["checks"]["sqlite_fts_row_count_matches_chunk_count"] is True
    assert result["checks"]["sample_query_content_hit"]["status"] == "skipped"
    assert result["checks"]["sample_query_content_hit"]["required"] is False
    assert result["checks"]["agent_pack_present"]["status"] == "skipped"
    assert result["checks"]["agent_pack_present"]["required"] is False
    assert result["checks"]["redact_secrets_enabled"] is False
    assert result["checks"]["chunk_invalid_json_line_count"] == 0
    assert result["checks"]["chunk_missing_id_line_count"] == 0


def test_health_not_fail_when_final_bundle_manifest_not_written_yet(tmp_path):
    # Key: primary_manifest_path exists (with_manifest=True), but we don't have
    # the final bundle manifest. Health should still succeed because it checks
    # the primary manifest, not the final bundle manifest.
    kwargs = _base_kwargs(tmp_path=tmp_path, with_manifest=True, with_sqlite=False)
    result = compute_output_health(**kwargs)

    assert result["checks"]["manifest_present"] is True
    assert not any(
        "primary artifact manifest is missing" in e for e in result["errors"]
    )
    assert result["verdict"] != "fail"


def test_output_health_does_not_require_final_bundle_manifest_entry(tmp_path):
    kwargs = _base_kwargs(tmp_path=tmp_path, with_manifest=True, with_sqlite=False)
    # Key: primary_manifest_path exists (with_manifest=True).
    # compute_output_health() has intentionally NO final_bundle_manifest_path parameter.
    # Health is computed from primary artifacts only, avoiding self-referential circularity.
    result = compute_output_health(**kwargs)

    assert result["checks"]["manifest_present"] is True
    assert not any(
        "primary artifact manifest is missing" in e for e in result["errors"]
    )
    assert result["verdict"] != "fail"


def test_verdict_fail_when_expected_canonical_hash_missing(tmp_path):
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    kwargs["expected_canonical_md_sha256"] = None
    result = compute_output_health(**kwargs)

    assert result["verdict"] == "fail"
    assert result["checks"]["canonical_md_hash_ok"] is False
    assert any("expected sha256 missing" in e for e in result["errors"])


def test_verdict_fail_when_expected_chunk_index_hash_missing(tmp_path):
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    kwargs["expected_chunk_index_sha256"] = None
    result = compute_output_health(**kwargs)

    assert result["verdict"] == "fail"
    assert result["checks"]["chunk_index_hash_ok"] is False
    assert any("expected sha256 missing" in e for e in result["errors"])


def test_verdict_fail_canonical_md_missing(tmp_path):
    kwargs = _base_kwargs(tmp_path=tmp_path)
    kwargs["canonical_md_path"] = tmp_path / "nonexistent.md"
    result = compute_output_health(**kwargs)

    assert result["verdict"] == "fail"
    assert result["checks"]["canonical_md_hash_ok"] is False
    assert any("file missing" in e.lower() for e in result["errors"])


def test_archive_mode_can_skip_chunk_index_hash_check(tmp_path):
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    kwargs["chunk_index_required"] = False
    kwargs["chunk_index_path"] = tmp_path / "missing.chunk_index.jsonl"
    kwargs["expected_chunk_index_sha256"] = None

    result = compute_output_health(**kwargs)

    assert result["checks"]["chunk_index_required"] is False
    assert result["checks"]["chunk_index_hash_ok"] is None
    assert not any("chunk_index hash check failed" in e for e in result["errors"])
    assert result["verdict"] != "fail"


def test_retrieval_mode_can_skip_canonical_md_hash_check(tmp_path):
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    kwargs["canonical_md_required"] = False
    kwargs["canonical_md_path"] = tmp_path / "missing.md"
    kwargs["expected_canonical_md_sha256"] = None

    result = compute_output_health(**kwargs)

    assert result["checks"]["canonical_md_required"] is False
    assert result["checks"]["canonical_md_hash_ok"] is None
    assert not any("canonical_md hash check failed" in e for e in result["errors"])
    assert result["verdict"] != "fail"


def test_verdict_fail_chunk_index_missing_file_when_required(tmp_path):
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    kwargs["chunk_index_path"] = tmp_path / "missing.chunk_index.jsonl"

    result = compute_output_health(**kwargs)

    assert result["verdict"] == "fail"
    assert result["checks"]["chunk_index_hash_ok"] is False
    assert any(
        "chunk_index hash check failed: file missing" in e for e in result["errors"]
    )


def test_verdict_fail_empty_chunk_index(tmp_path):
    kwargs = _base_kwargs(tmp_path=tmp_path, chunks=[])
    result = compute_output_health(**kwargs)

    assert result["verdict"] == "fail"
    assert result["checks"]["chunk_count"] == 0


def test_verdict_fail_sqlite_row_count_mismatch(tmp_path):
    chunks_full = [
        {"id": "c1", "content": "aaa", "path": "a.md"},
        {"id": "c2", "content": "bbb", "path": "b.md"},
        {"id": "c3", "content": "ccc", "path": "c.md"},
    ]
    chunks_short = [{"id": "c1", "content": "aaa", "path": "a.md"}]

    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path, chunk_sha = _make_chunk_jsonl(tmp_path, chunks_full)
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )
    sqlite_index_path = _make_sqlite(tmp_path, chunks_short)

    result = compute_output_health(
        run_id="run-test-mismatch",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=sqlite_index_path,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_sha,
    )

    assert result["verdict"] == "fail"
    assert result["checks"]["sqlite_row_count_matches_chunk_count"] is False


def test_verdict_fail_sqlite_expected_but_missing(tmp_path):
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunks = [{"id": "c1", "content": "aaa", "path": "a.md"}]
    chunk_index_path, chunk_sha = _make_chunk_jsonl(tmp_path, chunks)
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )
    sqlite_index_path = tmp_path / "missing.index.sqlite"

    result = compute_output_health(
        run_id="run-missing-sqlite",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=sqlite_index_path,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_sha,
    )

    assert result["checks"]["sqlite_present"] is False
    assert result["checks"]["sqlite_checks_required"] is True
    assert result["verdict"] == "fail"
    assert any(
        "sqlite" in e.lower() and "missing" in e.lower() for e in result["errors"]
    )


def test_sqlite_not_required_and_missing_does_not_warn_or_fail(tmp_path):
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    rr = _build_range_ref_for_canonical(canonical_md_path, 0, 8)
    chunks = [
        {
            "id": "c1",
            "content": "hello world",
            "path": "test/a.md",
            "content_range_ref": rr,
        }
    ]
    chunk_index_path, chunk_sha = _make_chunk_jsonl(tmp_path, chunks)
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-missing-sqlite-not-required",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        sqlite_index_required=False,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_sha,
    )

    assert result["checks"]["sqlite_checks_required"] is False
    assert result["checks"]["sqlite_present"] is False
    assert not any("sqlite" in w.lower() for w in result["warnings"])
    assert result["errors"] == []
    assert result["verdict"] == "pass"


def test_verdict_fail_sqlite_fts_row_count_mismatch(tmp_path):
    chunks = [
        {"id": "c1", "content": "aaa", "path": "a.md"},
        {"id": "c2", "content": "bbb", "path": "b.md"},
    ]
    fts_only_one = [{"id": "c1", "content": "aaa", "path": "a.md"}]

    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path, chunk_sha = _make_chunk_jsonl(tmp_path, chunks)
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )
    sqlite_index_path = _make_sqlite(
        tmp_path, chunks_rows=chunks, fts_rows=fts_only_one
    )

    result = compute_output_health(
        run_id="run-fts-mismatch",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=sqlite_index_path,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_sha,
    )

    assert result["verdict"] == "fail"
    assert result["checks"]["sqlite_fts_row_count"] == 1
    assert result["checks"]["sqlite_fts_row_count_matches_chunk_count"] is False
    assert any(
        "fts row count" in e.lower() and "chunk count" in e.lower()
        for e in result["errors"]
    )


def test_verdict_fail_fts_content_empty(tmp_path):
    chunks = [{"id": "c1", "content": "text", "path": "a.md"}]
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path, chunk_sha = _make_chunk_jsonl(tmp_path, chunks)
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    sqlite_index_path = _make_sqlite(
        tmp_path,
        chunks_rows=[{"id": "c1", "content": "text", "path": "a.md"}],
        fts_rows=[{"id": "c1", "content": "", "path": "a.md"}],
    )

    result = compute_output_health(
        run_id="run-empty-fts",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=sqlite_index_path,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_sha,
    )

    assert result["verdict"] == "fail"
    assert result["checks"]["fts_content_non_empty"] is False


def test_verdict_fail_range_ref_resolution_broken(tmp_path):
    chunks = [
        {
            "id": "c1",
            "content": "",
            "path": "a.md",
            "content_range_ref": {
                "artifact_role": "canonical_md",
                "repo_id": "repo-1",
                "file_path": "missing_artifact.md",
                "start_byte": 0,
                "end_byte": 10,
                "start_line": 1,
                "end_line": 1,
                "content_sha256": "0" * 64,
            },
        }
    ]
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path, chunk_sha = _make_chunk_jsonl(tmp_path, chunks)
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-broken-ref",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_sha,
    )

    assert result["checks"]["range_ref_resolution_ok"] is False
    assert result["verdict"] == "fail"


def test_verdict_fail_invalid_content_range_ref_json_string(tmp_path):
    chunks = [
        {
            "id": "c1",
            "content": "x",
            "path": "a.md",
            "content_range_ref": "{broken-json",
        }
    ]
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path, chunk_sha = _make_chunk_jsonl(tmp_path, chunks)
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-invalid-ref-json",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_sha,
    )

    assert result["verdict"] == "fail"
    assert result["checks"]["range_ref_resolution_ok"] is False
    assert result["checks"]["range_ref_resolution_status"] == "fail"
    assert result["checks"]["range_ref_resolution"]["validation"] == {
        "mode": "structural_precheck",
        "engine": "range_resolver",
        "reason": "malformed_range_ref",
    }
    assert any("invalid range reference json" in e.lower() for e in result["errors"])
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=result, schema=schema)


def test_verdict_fail_content_range_ref_wrong_type(tmp_path):
    chunks = [
        {
            "id": "c1",
            "content": "x",
            "path": "a.md",
            "content_range_ref": ["not", "an", "object"],
        }
    ]
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path, chunk_sha = _make_chunk_jsonl(tmp_path, chunks)
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-wrong-ref-type",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_sha,
    )

    assert result["verdict"] == "fail"
    assert result["checks"]["range_ref_resolution_ok"] is False
    assert result["checks"]["range_ref_resolution_status"] == "fail"
    assert result["checks"]["range_ref_resolution"]["validation"] == {
        "mode": "structural_precheck",
        "engine": "range_resolver",
        "reason": "malformed_range_ref",
    }
    assert any(
        "range reference" in e.lower() and "object" in e for e in result["errors"]
    )
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=result, schema=schema)


def test_range_ref_precheck_prefers_malformed_canonical_range(tmp_path):
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    valid_legacy_ref = _build_range_ref_for_canonical(canonical_md_path, 0, 8)
    chunks = [
        {
            "id": "c1",
            "content": "x",
            "path": "a.md",
            "canonical_range": ["not", "an", "object"],
            "content_range_ref": valid_legacy_ref,
        }
    ]
    chunk_index_path, chunk_sha = _make_chunk_jsonl(tmp_path, chunks)
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-malformed-canonical-range",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        sqlite_index_required=False,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_sha,
    )

    assert result["verdict"] == "fail"
    assert result["checks"]["range_ref_resolution_ok"] is False
    assert result["checks"]["range_ref_resolution_status"] == "fail"
    assert result["checks"]["range_ref_resolution"]["validation"] == {
        "mode": "structural_precheck",
        "engine": "range_resolver",
        "reason": "malformed_range_ref",
    }
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=result, schema=schema)


def test_no_range_reference_is_warn_not_pass(tmp_path):
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    result = compute_output_health(**kwargs)

    assert result["checks"]["range_ref_resolution_ok"] is None
    assert result["verdict"] == "warn"
    assert any(
        "range_ref" in w.lower() and "skipped" in w.lower() for w in result["warnings"]
    )


def test_schema_conformance(tmp_path):
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    result = compute_output_health(**kwargs)
    jsonschema.validate(instance=result, schema=schema)


def test_agent_pack_present_skipped_when_path_not_provided(tmp_path):
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    result = compute_output_health(**kwargs)
    check = result["checks"]["agent_pack_present"]
    assert check["status"] == "skipped"
    assert check["required"] is False


def test_agent_pack_present_pass_when_file_exists(tmp_path):
    pack = tmp_path / "test.agent_reading_pack.md"
    pack.write_text("# pack\n", encoding="utf-8")
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    result = compute_output_health(
        **kwargs, agent_reading_pack_path=pack, agent_reading_pack_expected=True
    )
    check = result["checks"]["agent_pack_present"]
    assert check["status"] == "pass"
    assert check["required"] is True


def test_agent_pack_expected_but_missing_is_warning_not_fail(tmp_path):
    pack = tmp_path / "absent.agent_reading_pack.md"
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    result = compute_output_health(
        **kwargs, agent_reading_pack_path=pack, agent_reading_pack_expected=True
    )
    check = result["checks"]["agent_pack_present"]
    assert check["status"] == "warning"
    # Non-blocking in v1: a missing-but-expected pack must not fail the verdict.
    assert result["verdict"] != "fail"
    assert any(
        "agent_reading_pack expected but file is missing" in w
        for w in result["warnings"]
    )


def test_agent_pack_missing_and_not_expected_is_skipped(tmp_path):
    pack = tmp_path / "absent.agent_reading_pack.md"
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    result = compute_output_health(
        **kwargs, agent_reading_pack_path=pack, agent_reading_pack_expected=False
    )
    check = result["checks"]["agent_pack_present"]
    assert check["status"] == "skipped"
    assert check["required"] is False


def test_agent_pack_directory_at_path_fails_when_expected(tmp_path):
    """A directory at the pack path must not count as present; expected → fail."""
    pack_dir = tmp_path / "test.agent_reading_pack.md"
    pack_dir.mkdir()
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    result = compute_output_health(
        **kwargs, agent_reading_pack_path=pack_dir, agent_reading_pack_expected=True
    )
    check = result["checks"]["agent_pack_present"]
    assert check["status"] == "fail"
    assert check["required"] is True


def test_agent_pack_directory_at_path_warns_when_not_expected(tmp_path):
    """A directory at the pack path must not pass; not expected → warning."""
    pack_dir = tmp_path / "test.agent_reading_pack.md"
    pack_dir.mkdir()
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    result = compute_output_health(
        **kwargs, agent_reading_pack_path=pack_dir, agent_reading_pack_expected=False
    )
    check = result["checks"]["agent_pack_present"]
    assert check["status"] == "warning"
    assert check["required"] is False


def test_agent_pack_check_schema_conformance(tmp_path):
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    pack = tmp_path / "test.agent_reading_pack.md"
    pack.write_text("# pack\n", encoding="utf-8")
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    result = compute_output_health(
        **kwargs, agent_reading_pack_path=pack, agent_reading_pack_expected=True
    )
    jsonschema.validate(instance=result, schema=schema)


def test_write_output_health_writes_file(tmp_path):
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    rr = _build_range_ref_for_canonical(canonical_md_path, 0, 8)
    chunks = [
        {
            "id": "c1",
            "content": "hello world",
            "path": "test/a.md",
            "content_range_ref": rr,
        }
    ]
    kwargs = _base_kwargs(tmp_path=tmp_path, chunks=chunks, with_sqlite=False)
    out_path = tmp_path / "test.output_health.json"
    returned = write_output_health(out_path, **kwargs)

    assert returned == out_path
    assert out_path.exists()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["kind"] == "lenskit.output_health"
    assert data["verdict"] in {"pass", "warn", "fail"}

    # Assert validation is emitted in the real written sidecar
    output_checks = data["checks"]
    assert "range_ref_resolution_ok" in output_checks
    assert "range_ref_resolution_status" in output_checks
    validation = output_checks["range_ref_resolution"]["validation"]
    assert validation == {
        "mode": "jsonschema",
        "engine": "range_resolver",
        "reason": "available",
    }


def test_redact_secrets_flag_visible_in_checks(tmp_path):
    # Test with redact_secrets=True
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    kwargs["redact_secrets"] = True
    result = compute_output_health(**kwargs)
    assert result["checks"]["redact_secrets_enabled"] is True

    # Test with redact_secrets=False
    kwargs["redact_secrets"] = False
    result = compute_output_health(**kwargs)
    assert result["checks"]["redact_secrets_enabled"] is False


def test_chunk_index_invalid_json_line_is_error(tmp_path):
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunks = [{"id": "c1", "content": "hello"}]
    chunk_index_path = tmp_path / "test.chunk_index.jsonl"
    # Write valid line + invalid line
    chunk_index_path.write_text(
        json.dumps(chunks[0]) + "\n" + "this is not json\n", encoding="utf-8"
    )
    chunk_index_sha = _sha256_bytes(chunk_index_path.read_bytes())
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-invalid-json",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_index_sha,
    )

    assert result["verdict"] == "fail"
    assert result["checks"]["chunk_invalid_json_line_count"] == 1
    assert any("invalid or non-object" in e for e in result["errors"])


def test_chunk_index_non_object_json_line_is_error(tmp_path):
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path = tmp_path / "test.chunk_index.jsonl"
    # One valid object line and one valid non-object JSON line
    chunk_index_path.write_text(
        json.dumps({"id": "c1", "content": "hello", "path": "a.md"}) + "\n" + "[]\n",
        encoding="utf-8",
    )
    chunk_index_sha = _sha256_bytes(chunk_index_path.read_bytes())
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-non-object-json",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_index_sha,
    )

    assert result["verdict"] == "fail"
    assert result["checks"]["chunk_invalid_json_line_count"] == 1
    assert any("non-object" in e for e in result["errors"])


def test_chunk_index_missing_id_is_error(tmp_path):
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path = tmp_path / "test.chunk_index.jsonl"
    # JSON object without id or chunk_id
    chunk_index_path.write_text(
        json.dumps({"content": "hello", "path": "test/a.md"}) + "\n", encoding="utf-8"
    )
    chunk_index_sha = _sha256_bytes(chunk_index_path.read_bytes())
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-missing-id",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_index_sha,
    )

    assert result["verdict"] == "fail"
    assert result["checks"]["chunk_missing_id_line_count"] == 1
    assert any("missing valid id" in e for e in result["errors"])


def test_chunk_index_empty_chunk_id_is_error(tmp_path):
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path = tmp_path / "test.chunk_index.jsonl"
    chunk_index_path.write_text(
        json.dumps({"chunk_id": "", "content": "hello", "path": "test/a.md"}) + "\n",
        encoding="utf-8",
    )
    chunk_index_sha = _sha256_bytes(chunk_index_path.read_bytes())
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-empty-chunk-id",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_index_sha,
    )

    assert result["verdict"] == "fail"
    assert result["checks"]["chunk_missing_id_line_count"] == 1


def test_chunk_index_whitespace_chunk_id_is_error(tmp_path):
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path = tmp_path / "test.chunk_index.jsonl"
    chunk_index_path.write_text(
        json.dumps({"chunk_id": "   ", "content": "hello", "path": "test/a.md"}) + "\n",
        encoding="utf-8",
    )
    chunk_index_sha = _sha256_bytes(chunk_index_path.read_bytes())
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-whitespace-chunk-id",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_index_sha,
    )

    assert result["verdict"] == "fail"
    assert result["checks"]["chunk_missing_id_line_count"] == 1


def test_chunk_index_none_id_is_error(tmp_path):
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path = tmp_path / "test.chunk_index.jsonl"
    chunk_index_path.write_text(
        json.dumps({"id": None, "content": "hello", "path": "test/a.md"}) + "\n",
        encoding="utf-8",
    )
    chunk_index_sha = _sha256_bytes(chunk_index_path.read_bytes())
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-none-id",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_index_sha,
    )

    assert result["verdict"] == "fail"
    assert result["checks"]["chunk_missing_id_line_count"] == 1


def test_chunk_index_false_chunk_id_is_error(tmp_path):
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path = tmp_path / "test.chunk_index.jsonl"
    chunk_index_path.write_text(
        json.dumps({"chunk_id": False, "content": "hello", "path": "test/a.md"}) + "\n",
        encoding="utf-8",
    )
    chunk_index_sha = _sha256_bytes(chunk_index_path.read_bytes())
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-false-chunk-id",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_index_sha,
    )

    assert result["verdict"] == "fail"
    assert result["checks"]["chunk_missing_id_line_count"] == 1


def test_chunk_index_list_chunk_id_is_error(tmp_path):
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path = tmp_path / "test.chunk_index.jsonl"
    chunk_index_path.write_text(
        json.dumps({"chunk_id": [], "content": "hello", "path": "test/a.md"}) + "\n",
        encoding="utf-8",
    )
    chunk_index_sha = _sha256_bytes(chunk_index_path.read_bytes())
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-list-chunk-id",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_index_sha,
    )

    assert result["verdict"] == "fail"
    assert result["checks"]["chunk_missing_id_line_count"] == 1


def test_chunk_index_invalid_utf8_is_structured_fail_not_crash(tmp_path):
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path = tmp_path / "test.chunk_index.jsonl"
    chunk_index_path.write_bytes(b"\xff\xfe\xfd\n")
    chunk_index_sha = _sha256_bytes(chunk_index_path.read_bytes())
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-invalid-utf8",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_index_sha,
    )

    assert result["verdict"] == "fail"
    assert result["checks"]["chunk_invalid_json_line_count"] >= 1
    assert any("invalid or non-object" in e for e in result["errors"])


# ── range_ref_resolution_status tests ────────────────────────────────────────


def _raise_jsonschema_unavailable(*args, **kwargs):
    """Simulate a missing jsonschema installation from within resolve_range_ref."""
    raise RuntimeError(
        "Schema validation requested but jsonschema is unavailable in this environment."
    )


def _make_range_ref_chunks(tmp_path):
    """Return (canonical_md_path, canonical_md_sha, chunk_index_path, chunk_sha, dump_index_path)
    for a single chunk with a valid content_range_ref."""
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    rr = _build_range_ref_for_canonical(canonical_md_path, 0, 8)
    chunks = [{"id": "c1", "content": "hello", "path": "a.md", "content_range_ref": rr}]
    chunk_index_path, chunk_sha = _make_chunk_jsonl(tmp_path, chunks)
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )
    return (
        canonical_md_path,
        canonical_md_sha,
        chunk_index_path,
        chunk_sha,
        dump_index_path,
    )


def test_range_ref_jsonschema_unavailable_is_warn_not_fail(tmp_path):
    """jsonschema missing → environment_error, verdict warn, not fail."""
    from unittest.mock import patch

    (
        canonical_md_path,
        canonical_md_sha,
        chunk_index_path,
        chunk_sha,
        dump_index_path,
    ) = _make_range_ref_chunks(tmp_path)

    with (
        patch(
            "merger.lenskit.core.range_resolver.resolve_range_ref",
            side_effect=_raise_jsonschema_unavailable,
        ),
        patch("merger.lenskit.core.range_resolver.jsonschema", None),
    ):
        result = compute_output_health(
            run_id="run-jsonschema-missing",
            stem="test",
            primary_manifest_path=dump_index_path,
            canonical_md_path=canonical_md_path,
            chunk_index_path=chunk_index_path,
            dump_index_path=dump_index_path,
            sqlite_index_path=None,
            sqlite_index_required=False,
            redact_secrets=False,
            expected_canonical_md_sha256=canonical_md_sha,
            expected_chunk_index_sha256=chunk_sha,
        )

    assert result["verdict"] != "fail", (
        "verdict must not be 'fail' when jsonschema is merely unavailable"
    )
    assert result["checks"]["range_ref_resolution_ok"] is None
    assert result["checks"]["range_ref_resolution_status"] == "environment_error"
    assert result["checks"]["range_ref_resolution"]["status"] == "environment_error"
    assert result["checks"]["range_ref_resolution"]["validation"] == {
        "mode": "skipped_unavailable",
        "engine": "range_resolver",
        "reason": "dependency_unavailable",
    }
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=result, schema=schema)
    assert any("jsonschema" in w.lower() for w in result["warnings"])
    assert not any("jsonschema" in e.lower() for e in result["errors"])


def test_range_ref_jsonschema_unavailable_verdict_is_warn_not_pass(tmp_path):
    """When jsonschema is unavailable, verdict is 'warn' (not 'pass'), diagnostic is visible."""
    from unittest.mock import patch

    (
        canonical_md_path,
        canonical_md_sha,
        chunk_index_path,
        chunk_sha,
        dump_index_path,
    ) = _make_range_ref_chunks(tmp_path)

    with (
        patch(
            "merger.lenskit.core.range_resolver.resolve_range_ref",
            side_effect=_raise_jsonschema_unavailable,
        ),
        patch("merger.lenskit.core.range_resolver.jsonschema", None),
        patch("merger.lenskit.core.output_health._JSONSCHEMA_AVAILABLE", False),
    ):
        result = compute_output_health(
            run_id="run-jsonschema-warn",
            stem="test",
            primary_manifest_path=dump_index_path,
            canonical_md_path=canonical_md_path,
            chunk_index_path=chunk_index_path,
            dump_index_path=dump_index_path,
            sqlite_index_path=None,
            sqlite_index_required=False,
            redact_secrets=False,
            expected_canonical_md_sha256=canonical_md_sha,
            expected_chunk_index_sha256=chunk_sha,
        )

    deps = result["dependencies"]["jsonschema"]
    assert deps == {
        "available": False,
        "required_for": ["range_ref_schema"],
        "effect": "validation_degraded",
    }
    assert (
        result["checks"]["range_ref_resolution"]["validation"]["mode"]
        == "skipped_unavailable"
    )
    assert (
        result["checks"]["range_ref_resolution"]["validation"]["reason"]
        == "dependency_unavailable"
    )
    assert result["verdict"] == "warn"
    assert result["errors"] == []
    assert any(
        "skipped" in w.lower() and "jsonschema" in w.lower() for w in result["warnings"]
    )


def test_range_ref_status_ok_on_intact_path(tmp_path):
    """Intact range-ref path reports status=ok."""
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    rr = _build_range_ref_for_canonical(canonical_md_path, 0, 8)
    chunks = [
        {
            "id": "c1",
            "content": "hello world",
            "path": "test/a.md",
            "content_range_ref": rr,
        }
    ]
    chunk_index_path, chunk_sha = _make_chunk_jsonl(tmp_path, chunks)
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-range-ok",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        sqlite_index_required=False,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_sha,
    )

    assert result["checks"]["range_ref_resolution_ok"] is True
    assert result["checks"]["range_ref_resolution_status"] == "ok"
    assert result["checks"]["range_ref_resolution"]["validation"] == {
        "mode": "jsonschema",
        "engine": "range_resolver",
        "reason": "available",
    }
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=result, schema=schema)
    assert result["verdict"] == "pass"


def test_range_ref_status_ok_on_canonical_range_without_legacy_ref(tmp_path):
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    rr = _build_range_ref_for_canonical(canonical_md_path, 0, 8)
    chunks = [
        {
            "id": "c1",
            "content": "hello world",
            "path": "test/a.md",
            "canonical_range": rr,
        }
    ]
    chunk_index_path, chunk_sha = _make_chunk_jsonl(tmp_path, chunks)
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-canonical-range-only",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        sqlite_index_required=False,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_sha,
    )

    assert result["checks"]["range_ref_resolution_ok"] is True
    assert result["checks"]["range_ref_resolution_status"] == "ok"
    assert result["checks"]["range_ref_resolution"]["validation"] == {
        "mode": "jsonschema",
        "engine": "range_resolver",
        "reason": "available",
    }
    assert result["verdict"] == "pass"
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=result, schema=schema)


def test_range_ref_status_fail_on_real_semantic_error(tmp_path):
    """A genuine broken range-ref reports status=fail and verdict=fail."""
    chunks = [
        {
            "id": "c1",
            "content": "",
            "path": "a.md",
            "content_range_ref": {
                "artifact_role": "canonical_md",
                "repo_id": "repo-1",
                "file_path": "totally_missing_artifact.md",
                "start_byte": 0,
                "end_byte": 10,
                "start_line": 1,
                "end_line": 1,
                "content_sha256": "0" * 64,
            },
        }
    ]
    canonical_md_path, canonical_md_sha = _make_canonical_md(tmp_path)
    chunk_index_path, chunk_sha = _make_chunk_jsonl(tmp_path, chunks)
    dump_index_path = _make_dump_index(
        tmp_path, canonical_md_path.name, chunk_index_path.name
    )

    result = compute_output_health(
        run_id="run-range-fail",
        stem="test",
        primary_manifest_path=dump_index_path,
        canonical_md_path=canonical_md_path,
        chunk_index_path=chunk_index_path,
        dump_index_path=dump_index_path,
        sqlite_index_path=None,
        sqlite_index_required=False,
        redact_secrets=False,
        expected_canonical_md_sha256=canonical_md_sha,
        expected_chunk_index_sha256=chunk_sha,
    )

    assert result["checks"]["range_ref_resolution_ok"] is False
    assert result["checks"]["range_ref_resolution_status"] == "fail"
    assert result["verdict"] == "fail"
    assert any("range_ref" in e.lower() for e in result["errors"])


def test_regression_manifest_hash_checks_remain_hard_fail(tmp_path):
    """Hash check failures are unaffected by the range_ref status changes."""
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    kwargs["expected_canonical_md_sha256"] = "0" * 64  # wrong hash

    result = compute_output_health(**kwargs)

    assert result["verdict"] == "fail"
    assert result["checks"]["canonical_md_hash_ok"] is False
    assert any("hash mismatch" in e for e in result["errors"])


def test_regression_chunk_index_hash_check_remains_hard_fail(tmp_path):
    """Chunk-index hash check failures are unaffected by the range_ref status changes."""
    kwargs = _base_kwargs(tmp_path=tmp_path, with_sqlite=False)
    kwargs["expected_chunk_index_sha256"] = "0" * 64  # wrong hash

    result = compute_output_health(**kwargs)

    assert result["verdict"] == "fail"
    assert result["checks"]["chunk_index_hash_ok"] is False
    assert any("hash mismatch" in e for e in result["errors"])


def test_range_ref_jsonschema_importerror_is_warn_not_fail(tmp_path):
    """ModuleNotFoundError for jsonschema must also produce warn, not fail."""
    from unittest.mock import patch

    (
        canonical_md_path,
        canonical_md_sha,
        chunk_index_path,
        chunk_sha,
        dump_index_path,
    ) = _make_range_ref_chunks(tmp_path)

    with patch(
        "merger.lenskit.core.range_resolver.resolve_range_ref",
        side_effect=ModuleNotFoundError("No module named 'jsonschema'"),
    ):
        result = compute_output_health(
            run_id="run-jsonschema-importerror",
            stem="test",
            primary_manifest_path=dump_index_path,
            canonical_md_path=canonical_md_path,
            chunk_index_path=chunk_index_path,
            dump_index_path=dump_index_path,
            sqlite_index_path=None,
            sqlite_index_required=False,
            redact_secrets=False,
            expected_canonical_md_sha256=canonical_md_sha,
            expected_chunk_index_sha256=chunk_sha,
        )

    assert result["verdict"] == "warn"
    assert result["checks"]["range_ref_resolution_ok"] is None
    assert result["checks"]["range_ref_resolution_status"] == "environment_error"
    assert any("jsonschema" in w.lower() for w in result["warnings"])
    assert result["errors"] == []


def test_output_health_noise_hygiene_unavailable_without_scan_diagnostic(tmp_path):
    kwargs = _base_kwargs(tmp_path=tmp_path)
    result = compute_output_health(**kwargs)

    assert result["checks"]["noise_hygiene"]["available"] is False
    assert result["checks"]["excluded_noise"]["count"] == 0


def test_output_health_noise_hygiene_available_with_scan_diagnostic(tmp_path):
    kwargs = _base_kwargs(tmp_path=tmp_path)
    kwargs["excluded_noise"] = {
        "count": 1,
        "samples": [
            ".tmp/forensic-preflight-ci-canary/artifacts/forensic-preflight-canary.json"
        ],
        "patterns": [".tmp/"],
    }
    result = compute_output_health(**kwargs)

    assert result["checks"]["noise_hygiene"]["available"] is True
    assert result["checks"]["noise_hygiene"]["excluded_noise_count"] == 1
    assert result["checks"]["excluded_noise"]["samples"] == [
        ".tmp/forensic-preflight-ci-canary/artifacts/forensic-preflight-canary.json"
    ]


def test_output_health_schema_rejects_bad_validation_mode(tmp_path):
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    report = compute_output_health(**_base_kwargs(tmp_path=tmp_path, with_sqlite=False))
    report["checks"]["range_ref_resolution"]["validation"]["mode"] = "banana_mode"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_output_health_schema_rejects_bad_validation_reason(tmp_path):
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    report = compute_output_health(**_base_kwargs(tmp_path=tmp_path, with_sqlite=False))
    report["checks"]["range_ref_resolution"]["validation"]["reason"] = "banana_reason"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_output_health_schema_rejects_bad_validation_engine(tmp_path):
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    report = compute_output_health(**_base_kwargs(tmp_path=tmp_path, with_sqlite=False))
    report["checks"]["range_ref_resolution"]["validation"]["engine"] = "banana_engine"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_output_health_schema_rejects_incomplete_validation(tmp_path):
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    report = compute_output_health(**_base_kwargs(tmp_path=tmp_path, with_sqlite=False))
    report["checks"]["range_ref_resolution"]["validation"] = {
        "mode": "jsonschema",
        "engine": "range_resolver",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_output_health_schema_accepts_legacy_checks_without_range_ref_resolution_block(
    tmp_path,
):
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    report = compute_output_health(**_base_kwargs(tmp_path=tmp_path, with_sqlite=False))

    # Legacy reports carried range_ref_resolution_ok/status before the nested
    # range_ref_resolution diagnostic block was added.
    assert "range_ref_resolution_ok" in report["checks"]
    assert "range_ref_resolution_status" in report["checks"]

    report["checks"].pop("range_ref_resolution", None)
    jsonschema.validate(instance=report, schema=schema)


def _get_base_oh_report():
    from merger.lenskit.core.output_health import compute_output_health

    return compute_output_health(
        run_id="test-run",
        stem="test",
        primary_manifest_path=None,
        canonical_md_path=None,
        chunk_index_path=None,
        dump_index_path=None,
        sqlite_index_path=None,
        redact_secrets=False,
        canonical_md_required=False,
        chunk_index_required=False,
    )


def test_output_health_schema_accepts_dependencies():
    report = _get_base_oh_report()
    report["dependencies"] = {
        "jsonschema": {
            "available": True,
            "required_for": ["range_ref_schema"],
            "effect": "full_validation_available",
        }
    }
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_output_health_schema_accepts_legacy_report_without_dependencies():
    report = _get_base_oh_report()
    if "dependencies" in report:
        del report["dependencies"]
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_output_health_schema_rejects_invalid_dependency_effect():
    report = _get_base_oh_report()
    report["dependencies"] = {
        "jsonschema": {
            "available": True,
            "required_for": ["range_ref_schema"],
            "effect": "invalid_effect",
        }
    }
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_output_health_schema_rejects_invalid_required_for():
    report = _get_base_oh_report()
    report["dependencies"] = {
        "jsonschema": {
            "available": True,
            "required_for": ["manifest_schema"],
            "effect": "full_validation_available",
        }
    }
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_output_health_schema_rejects_non_boolean_dependency_available():
    report = _get_base_oh_report()
    report["dependencies"] = {
        "jsonschema": {
            "available": "true",
            "required_for": ["range_ref_schema"],
            "effect": "full_validation_available",
        }
    }
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_output_health_schema_rejects_extra_dependency_name():
    report = _get_base_oh_report()
    report["dependencies"] = {
        "jsonschema": {
            "available": True,
            "required_for": ["range_ref_schema"],
            "effect": "full_validation_available",
        },
        "yaml": {
            "available": True,
            "required_for": [],
            "effect": "full_validation_available",
        },
    }
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_output_health_schema_rejects_empty_dependencies_object():
    report = _get_base_oh_report()
    report["dependencies"] = {}
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_output_health_schema_rejects_dependency_available_effect_mismatch():
    report = _get_base_oh_report()
    report["dependencies"] = {
        "jsonschema": {
            "available": False,
            "required_for": ["range_ref_schema"],
            "effect": "full_validation_available",
        }
    }
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_output_health_dependencies_reports_jsonschema_available(monkeypatch):
    monkeypatch.setattr("merger.lenskit.core.output_health._JSONSCHEMA_AVAILABLE", True)

    report = compute_output_health(
        run_id="test-run",
        stem="test",
        primary_manifest_path=None,
        canonical_md_path=None,
        chunk_index_path=None,
        dump_index_path=None,
        sqlite_index_path=None,
        redact_secrets=False,
        canonical_md_required=False,
        chunk_index_required=False,
    )

    assert report["dependencies"]["jsonschema"] == {
        "available": True,
        "required_for": ["range_ref_schema"],
        "effect": "full_validation_available",
    }


def test_output_health_dependencies_reports_jsonschema_unavailable(monkeypatch):
    monkeypatch.setattr("merger.lenskit.core.output_health._JSONSCHEMA_AVAILABLE", False)

    report = compute_output_health(
        run_id="test-run",
        stem="test",
        primary_manifest_path=None,
        canonical_md_path=None,
        chunk_index_path=None,
        dump_index_path=None,
        sqlite_index_path=None,
        redact_secrets=False,
        canonical_md_required=False,
        chunk_index_required=False,
    )

    assert report["dependencies"]["jsonschema"] == {
        "available": False,
        "required_for": ["range_ref_schema"],
        "effect": "validation_degraded",
    }
