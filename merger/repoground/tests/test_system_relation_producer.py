import json
from pathlib import Path

import pytest

import merger.repoground.core.system_relation_producer as producer
from merger.repoground.core.system_relation_overlay import (
    normalize_system_relation_evidence,
)
from merger.repoground.tests.git_fixture import commit_fixture

REPOSITORY_IDENTITY = "example/repository"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _collect(root: Path, **kwargs):
    commit = commit_fixture(root)
    return producer.collect_system_relation_evidence(
        root,
        repository_identity=REPOSITORY_IDENTITY,
        repository_commit=commit,
        **kwargs,
    )


def test_collects_only_explicit_config_schema_and_local_workflow_relations(tmp_path):
    _write(
        tmp_path / "pyproject.toml",
        "[tool.repoground]\nenabled = true\n\n[tool.ruff]\nline-length = 100\n",
    )
    _write(
        tmp_path / "schemas" / "widget.schema.json",
        json.dumps(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "$id": "https://example.test/schemas/widget.schema.json",
                "type": "object",
            },
            indent=2,
        )
        + "\n",
    )
    _write(
        tmp_path / ".github" / "workflows" / "reuse.yml",
        "name: reuse\non:\n  workflow_call:\njobs: {}\n",
    )
    _write(
        tmp_path / ".github" / "workflows" / "caller.yml",
        "name: caller\njobs:\n  delegated:\n    uses: ./.github/workflows/reuse.yml\n",
    )

    result = _collect(tmp_path)
    evidence = result["evidence"]
    overlay = result["overlay"]

    assert evidence["kind"] == "repoground.system_relation_evidence"
    assert evidence["version"] == "1.0"
    assert evidence["producer"] == {
        "name": "repoground.system_relation_producer",
        "version": "1.0",
    }
    assert {record["relation"] for record in evidence["records"]} == {
        "declares_config",
        "declares_schema",
        "references_workflow",
    }
    assert [
        record["target"]["identity"]
        for record in evidence["records"]
        if record["relation"] == "declares_config"
    ] == ["pyproject.tool.repoground", "pyproject.tool.ruff"]

    schema_record = next(
        record for record in evidence["records"] if record["relation"] == "declares_schema"
    )
    assert schema_record["contract_identity"] == {
        "kind": "schema",
        "id": "https://example.test/schemas/widget.schema.json",
        "version": "unversioned",
    }
    assert schema_record["source"]["kind"] == "schema_file"
    assert schema_record["source"]["range"]["start_line"] == 3

    workflow_record = next(
        record
        for record in evidence["records"]
        if record["relation"] == "references_workflow"
    )
    assert workflow_record["subject"] == {
        "kind": "workflow",
        "identity": ".github/workflows/caller.yml",
    }
    assert workflow_record["target"] == {
        "kind": "workflow",
        "identity": ".github/workflows/reuse.yml",
    }
    assert workflow_record["contract_identity"] is None
    assert workflow_record["source"]["range"]["start_line"] == 4

    assert overlay["source"]["repository_commit"] == result["repository"]["commit"]
    assert result["revision_binding"] == {
        "mode": "git_commit_object",
        "repository_commit": result["repository"]["commit"],
        "verified": True,
    }
    assert overlay["source"]["evidence_sha256"] == result["evidence_sha256"]
    assert overlay["relation_kinds"] == [
        "declares_config",
        "declares_schema",
        "references_workflow",
    ]
    assert all(
        record["relation"] not in {"calls", "constructs"}
        for record in overlay["records"]
    )
    assert result["producer_contract"]["repository_source"] == "git_object_database"
    assert result["producer_contract"]["working_tree_reads"] is False
    assert result["producer_contract"]["network_access"] is False
    assert result["producer_contract"]["secret_file_scanning"] is False


def test_dynamic_ambiguous_and_missing_workflow_targets_are_omitted(tmp_path):
    _write(
        tmp_path / ".github" / "workflows" / "caller.yml",
        "name: caller\njobs:\n  dynamic:\n    uses: ${{ matrix.workflow }}\n  missing:\n    uses: ./.github/workflows/missing.yml\n",
    )

    result = _collect(tmp_path)

    assert result["evidence"]["records"] == []
    reasons = [item["reason"] for item in result["omissions"]]
    assert reasons == [
        "dynamic_workflow_reference",
        "workflow_target_missing",
    ]
    assert result["overlay"]["status"] == "degraded"
    assert result["overlay"]["degradations"][0]["code"] == "records_empty"


def test_true_null_case_does_not_infer_relations_from_unrelated_files(tmp_path):
    _write(tmp_path / "README.md", "# no structural declarations here\n")
    _write(tmp_path / "data.json", '{"name": "ordinary data"}\n')

    result = _collect(tmp_path)

    assert result["scan"]["candidate_count"] == 0
    assert result["scan"]["scanned_file_count"] == 0
    assert result["evidence"]["records"] == []
    assert result["omissions"] == []
    assert "do not establish absence" in result["absence_semantics"]


def test_schema_without_literal_top_level_id_is_reported_not_inferred(tmp_path):
    _write(
        tmp_path / "schemas" / "anonymous.schema.json",
        '{"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"}\n',
    )

    result = _collect(tmp_path)

    assert result["evidence"]["records"] == []
    assert result["omissions"] == [
        {
            "path": "schemas/anonymous.schema.json",
            "reason": "schema_id_missing_or_nonliteral",
        }
    ]



def test_generic_schema_version_field_is_not_promoted_to_contract_identity(tmp_path):
    _write(
        tmp_path / "contracts" / "versioned.schema.json",
        '{"$id":"https://example.test/versioned","version":"999","type":"object"}\n',
    )

    result = _collect(tmp_path)

    assert result["evidence"]["records"][0]["contract_identity"] == {
        "kind": "schema",
        "id": "https://example.test/versioned",
        "version": "unversioned",
    }

def test_nested_schema_id_does_not_masquerade_as_top_level_declaration(tmp_path):
    _write(
        tmp_path / "schemas" / "nested.schema.json",
        "{\n"
        '  "type": "object",\n'
        '  "properties": {\n'
        '    "nested": {"$id": "https://example.test/nested", "type": "string"}\n'
        "  }\n"
        "}\n",
    )

    result = _collect(tmp_path)

    assert result["evidence"]["records"] == []
    assert result["omissions"][0]["reason"] == "schema_id_missing_or_nonliteral"


def test_invalid_or_oversized_candidates_fail_closed(tmp_path):
    _write(tmp_path / "pyproject.toml", "[tool.broken\n")
    _write(
        tmp_path / "schemas" / "huge.schema.json",
        '{"$id":"https://example.test/huge","padding":"' + ("x" * 256) + '"}\n',
    )

    result = _collect(tmp_path, max_file_bytes=128)

    assert result["evidence"]["records"] == []
    assert {item["reason"] for item in result["omissions"]} == {
        "invalid_toml",
        "file_too_large",
    }


def test_file_budget_is_deterministic_and_visible(tmp_path):
    _write(
        tmp_path / "a.schema.json",
        '{"$id":"https://example.test/a","type":"object"}\n',
    )
    _write(
        tmp_path / "b.schema.json",
        '{"$id":"https://example.test/b","type":"object"}\n',
    )

    result = _collect(tmp_path, max_files=1)

    assert len(result["evidence"]["records"]) == 1
    assert result["evidence"]["records"][0]["target"]["identity"] == "https://example.test/a"
    assert result["omissions"] == [
        {"path": "b.schema.json", "reason": "file_budget_exhausted"}
    ]


def test_evidence_and_overlay_are_deterministic(tmp_path):
    _write(tmp_path / "pyproject.toml", "[tool.zeta]\nx = 1\n[tool.alpha]\ny = 2\n")

    first = _collect(tmp_path)
    second = _collect(tmp_path)

    assert first == second
    assert len(first["evidence_sha256"]) == 64
    assert first["overlay"] == normalize_system_relation_evidence(
        first["evidence"],
        evidence_sha256=first["evidence_sha256"],
        repository_commit=first["repository"]["commit"],
    )


def test_requested_commit_is_read_from_git_objects_not_dirty_worktree(tmp_path):
    _write(tmp_path / "pyproject.toml", "[tool.alpha]\nenabled = true\n")
    commit = commit_fixture(tmp_path)
    first = producer.collect_system_relation_evidence(
        tmp_path,
        repository_identity=REPOSITORY_IDENTITY,
        repository_commit=commit,
    )

    _write(tmp_path / "pyproject.toml", "[tool.beta]\nenabled = true\n")
    second = producer.collect_system_relation_evidence(
        tmp_path,
        repository_identity=REPOSITORY_IDENTITY,
        repository_commit=commit,
    )

    assert first == second
    assert [record["target"]["identity"] for record in second["evidence"]["records"]] == [
        "pyproject.tool.alpha"
    ]


def test_well_formed_but_missing_commit_is_rejected(tmp_path):
    _write(tmp_path / "README.md", "fixture\n")
    commit_fixture(tmp_path)

    with pytest.raises(producer.SystemRelationProducerError, match="commit verification failed"):
        producer.collect_system_relation_evidence(
            tmp_path,
            repository_identity=REPOSITORY_IDENTITY,
            repository_commit="b" * 40,
        )


@pytest.mark.parametrize(
    "commit",
    ["", "ABC", "g" * 40, "a" * 39, "a" * 41],
)
def test_repository_commit_must_be_revision_bound(tmp_path, commit):
    with pytest.raises(producer.SystemRelationProducerError, match="repository_commit"):
        producer.collect_system_relation_evidence(
            tmp_path,
            repository_identity=REPOSITORY_IDENTITY,
            repository_commit=commit,
        )

def test_missing_toml_parser_omits_config_instead_of_failing_import(tmp_path, monkeypatch):
    _write(tmp_path / "pyproject.toml", "[tool.alpha]\nenabled = true\n")
    monkeypatch.setattr(producer, "tomllib", None)

    result = _collect(tmp_path)

    assert result["evidence"]["records"] == []
    assert result["omissions"] == [
        {"path": "pyproject.toml", "reason": "toml_parser_unavailable"}
    ]
