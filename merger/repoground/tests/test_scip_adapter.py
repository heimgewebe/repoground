import copy
import json
from pathlib import Path

import jsonschema
import pytest

from merger.repoground.core.scip_adapter import (
    ScipAdapterError,
    benchmark_identity,
    evaluate_scip_adapter,
    normalize_scip_index,
)

INDEX_SHA = "a" * 64
REPOSITORY_COMMIT = "b" * 40
TS_SYMBOL = "scip-typescript npm demo 1.0.0 demo/main()."
TS_TARGET = "scip-typescript npm demo 1.0.0 demo/Runner#"
RUST_SYMBOL = "rust cargo demo 1.0.0 demo/run()."


def _contracts_dir() -> Path:
    return Path(__file__).parent.parent / "contracts"


def _schema(name: str):
    return json.loads((_contracts_dir() / name).read_text(encoding="utf-8"))


def _index():
    return {
        "metadata": {
            "version": 0,
            "toolInfo": {
                "name": "scip-test-indexer",
                "version": "1.2.3",
                "arguments": ["index", "--project=demo"],
            },
            "projectRoot": "file:///workspace/demo",
            "textDocumentEncoding": "UTF8",
        },
        "documents": [
            {
                "relativePath": "src/main.ts",
                "language": "TypeScript",
                "positionEncoding": "UTF16CodeUnitOffsetFromLineStart",
                "occurrences": [
                    {"range": [0, 0, 4], "symbol": TS_SYMBOL, "symbolRoles": 1},
                    {"range": [1, 7, 11], "symbol": TS_SYMBOL, "symbolRoles": 8},
                ],
                "symbols": [
                    {
                        "symbol": TS_SYMBOL,
                        "relationships": [
                            {
                                "symbol": TS_TARGET,
                                "isReference": True,
                                "isImplementation": True,
                            }
                        ],
                    }
                ],
            },
            {
                "relativePath": "src/lib.rs",
                "language": "Rust",
                "positionEncoding": "UTF8CodeUnitOffsetFromLineStart",
                "occurrences": [
                    {
                        "range": [0, 3, 6],
                        "symbol": RUST_SYMBOL,
                        "symbolRoles": 1 | 32,
                    },
                    {"range": [1, 0, 3], "symbol": RUST_SYMBOL, "symbolRoles": 8},
                ],
                "symbols": [],
            },
        ],
    }


def _artifact(index=None):
    return normalize_scip_index(
        _index() if index is None else index,
        index_sha256=INDEX_SHA,
        repository_commit=REPOSITORY_COMMIT,
    )


def _goldset():
    return {
        "typescript": [
            {
                "record_type": "occurrence",
                "relation": "definition",
                "symbol": TS_SYMBOL,
                "target_symbol": None,
                "path": "src/main.ts",
                "start_line": 1,
            },
            {
                "record_type": "occurrence",
                "relation": "reference",
                "symbol": TS_SYMBOL,
                "target_symbol": None,
                "path": "src/main.ts",
                "start_line": 2,
            },
            {
                "record_type": "relationship",
                "relation": "implements_symbol",
                "symbol": TS_SYMBOL,
                "target_symbol": TS_TARGET,
                "path": "src/main.ts",
                "start_line": 1,
            },
            {
                "record_type": "relationship",
                "relation": "references_symbol",
                "symbol": TS_SYMBOL,
                "target_symbol": TS_TARGET,
                "path": "src/main.ts",
                "start_line": 1,
            },
        ],
        "rust": [
            {
                "record_type": "occurrence",
                "relation": "definition",
                "symbol": RUST_SYMBOL,
                "target_symbol": None,
                "path": "src/lib.rs",
                "start_line": 1,
            },
            {
                "record_type": "occurrence",
                "relation": "reference",
                "symbol": RUST_SYMBOL,
                "target_symbol": None,
                "path": "src/lib.rs",
                "start_line": 2,
            },
        ],
    }


def test_normalizes_multilingual_occurrences_and_relationships():
    artifact = _artifact()

    assert artifact["status"] == "available"
    assert artifact["languages"] == ["rust", "typescript"]
    assert artifact["record_count"] == 6
    assert len(artifact["records"]) == 6
    assert {record["relation"] for record in artifact["records"]} == {
        "definition",
        "reference",
        "implements_symbol",
        "references_symbol",
    }
    ts_definition = next(
        record
        for record in artifact["records"]
        if record["language"] == "typescript" and record["relation"] == "definition"
    )
    assert ts_definition["source"]["range"] == {
        "start_line": 1,
        "start_character": 0,
        "end_line": 1,
        "end_character": 4,
        "position_encoding": "UTF16CodeUnitOffsetFromLineStart",
    }
    rust_definition = next(
        record
        for record in artifact["records"]
        if record["language"] == "rust" and record["relation"] == "definition"
    )
    assert rust_definition["roles"] == ["definition", "test"]
    assert artifact["consumer_enablement"] == {
        "requires_language_benchmark": True,
        "eligible_for_review": False,
        "default_promoted": False,
    }


def test_output_is_deterministic_under_input_reordering():
    first = _index()
    second = copy.deepcopy(first)
    second["documents"].reverse()
    for document in second["documents"]:
        document["occurrences"].reverse()
        document["symbols"].reverse()
        for symbol in document["symbols"]:
            symbol["relationships"].reverse()

    assert _artifact(first) == _artifact(second)


def test_source_provenance_is_digest_bound_without_leaking_project_root():
    artifact = _artifact()

    assert artifact["source"]["index_sha256"] == INDEX_SHA
    assert artifact["source"]["repository_commit"] == REPOSITORY_COMMIT
    assert artifact["source"]["indexer"]["name"] == "scip-test-indexer"
    assert len(artifact["source"]["indexer"]["arguments_sha256"]) == 64
    assert len(artifact["source"]["project_root_sha256"]) == 64
    assert "file:///workspace/demo" not in json.dumps(artifact)


def test_missing_indexer_is_explicit_degradation_not_silent_success():
    index = _index()
    index["metadata"].pop("toolInfo")

    artifact = _artifact(index)

    assert artifact["status"] == "degraded"
    assert {item["code"] for item in artifact["degradations"]} >= {
        "indexer_missing",
        "indexer_name_missing",
        "indexer_version_missing",
    }
    assert artifact["record_count"] == 6


def test_partial_document_without_language_is_skipped_with_degradation():
    index = _index()
    index["documents"].append(
        {
            "relativePath": "src/partial.go",
            "positionEncoding": "UTF8CodeUnitOffsetFromLineStart",
            "occurrences": [
                {"range": [0, 0, 1], "symbol": "scip-go gomod demo 1 x.", "symbolRoles": 1}
            ],
        }
    )

    artifact = _artifact(index)

    assert artifact["status"] == "degraded"
    assert any(
        item["code"] == "document_language_missing"
        and item["document"] == "src/partial.go"
        for item in artifact["degradations"]
    )
    assert artifact["record_count"] == 6


def test_unsafe_document_path_fails_closed():
    index = _index()
    index["documents"][0]["relativePath"] = "../escape.ts"

    with pytest.raises(ScipAdapterError, match="unsafe SCIP document path"):
        _artifact(index)


def test_unknown_role_bits_are_visible_and_known_roles_survive():
    index = _index()
    index["documents"][0]["occurrences"][0]["symbolRoles"] = 1 | 128

    artifact = _artifact(index)

    assert artifact["status"] == "degraded"
    assert any(
        item["code"] == "occurrence_roles_unknown_bits"
        and item["symbol"] == TS_SYMBOL
        for item in artifact["degradations"]
    )
    definition = next(
        record
        for record in artifact["records"]
        if record["symbol"] == TS_SYMBOL and record["relation"] == "definition"
    )
    assert definition["roles"] == ["definition"]


def test_unsupported_relationship_is_visible_and_not_projected():
    index = _index()
    index["documents"][0]["symbols"][0]["relationships"] = [
        {"symbol": TS_TARGET}
    ]

    artifact = _artifact(index)

    assert artifact["status"] == "degraded"
    assert any(item["code"] == "relationship_unsupported" for item in artifact["degradations"])
    assert not any(record["record_type"] == "relationship" for record in artifact["records"])


def test_relationship_without_unique_definition_is_not_guessed():
    index = _index()
    index["documents"][0]["occurrences"] = [
        occurrence
        for occurrence in index["documents"][0]["occurrences"]
        if occurrence["symbolRoles"] != 1
    ]

    artifact = _artifact(index)

    assert artifact["status"] == "degraded"
    assert any(
        item["code"] == "relationship_source_definition_missing"
        for item in artifact["degradations"]
    )
    assert not any(record["record_type"] == "relationship" for record in artifact["records"])


def test_local_symbol_definitions_are_scoped_to_their_document():
    local_symbol = "local 1"
    index = _index()
    index["documents"] = [
        {
            "relativePath": "src/a.py",
            "language": "python",
            "positionEncoding": "UTF32CodeUnitOffsetFromLineStart",
            "occurrences": [
                {"range": [0, 0, 1], "symbol": local_symbol, "symbolRoles": 1}
            ],
            "symbols": [
                {
                    "symbol": local_symbol,
                    "relationships": [{"symbol": "local 2", "isReference": True}],
                }
            ],
        },
        {
            "relativePath": "src/b.py",
            "language": "python",
            "positionEncoding": "UTF32CodeUnitOffsetFromLineStart",
            "occurrences": [
                {"range": [4, 0, 1], "symbol": local_symbol, "symbolRoles": 1}
            ],
            "symbols": [],
        },
    ]

    artifact = _artifact(index)

    relationship = next(
        record for record in artifact["records"] if record["record_type"] == "relationship"
    )
    assert relationship["source"]["path"] == "src/a.py"
    assert relationship["source"]["range"]["start_line"] == 1


def test_external_symbols_are_not_projected_without_repository_range():
    index = _index()
    index["externalSymbols"] = [{"symbol": "scip-java maven ext 1 External#"}]

    artifact = _artifact(index)

    assert artifact["status"] == "degraded"
    assert any(
        item["code"] == "external_symbols_not_projected" and item["count"] == 1
        for item in artifact["degradations"]
    )
    assert all("External#" not in record["symbol"] for record in artifact["records"])


def test_accepts_snake_case_binding_field_names():
    index = _index()
    metadata = index["metadata"]
    metadata["tool_info"] = metadata.pop("toolInfo")
    metadata["project_root"] = metadata.pop("projectRoot")
    metadata["text_document_encoding"] = metadata.pop("textDocumentEncoding")
    for document in index["documents"]:
        document["relative_path"] = document.pop("relativePath")
        document["position_encoding"] = document.pop("positionEncoding")
        for occurrence in document["occurrences"]:
            occurrence["symbol_roles"] = occurrence.pop("symbolRoles")
        for symbol in document["symbols"]:
            for relationship in symbol["relationships"]:
                relationship["is_reference"] = relationship.pop("isReference")
                relationship["is_implementation"] = relationship.pop("isImplementation")

    assert _artifact(index)["record_count"] == 6


def test_adapter_artifact_matches_json_schema():
    artifact = _artifact()
    schema = _schema("scip-symbol-relations.v1.schema.json")

    jsonschema.Draft7Validator.check_schema(schema)
    jsonschema.validate(instance=artifact, schema=schema)


def test_fixed_multilingual_benchmark_passes_without_default_promotion():
    artifact = _artifact()

    report = evaluate_scip_adapter(artifact, _goldset())

    assert report["status"] == "pass"
    assert report["eligible_languages"] == ["rust", "typescript"]
    assert report["unbenchmarked_languages"] == []
    assert report["failed_languages"] == []
    assert all(result["precision"] == 1.0 for result in report["per_language"].values())
    assert all(result["recall"] == 1.0 for result in report["per_language"].values())
    assert report["consumer_enablement"] == {
        "eligible_for_review": True,
        "default_promoted": False,
    }
    schema = _schema("scip-adapter-benchmark.v1.schema.json")
    jsonschema.Draft7Validator.check_schema(schema)
    jsonschema.validate(instance=report, schema=schema)


def test_missing_language_goldset_warns_and_blocks_review_eligibility():
    report = evaluate_scip_adapter(_artifact(), {"typescript": _goldset()["typescript"]})

    assert report["status"] == "warn"
    assert report["eligible_languages"] == ["typescript"]
    assert report["unbenchmarked_languages"] == ["rust"]
    assert report["consumer_enablement"]["eligible_for_review"] is False
    assert report["consumer_enablement"]["default_promoted"] is False


def test_false_positive_fails_language_gate():
    goldset = _goldset()
    goldset["typescript"] = goldset["typescript"][:-1]

    report = evaluate_scip_adapter(_artifact(), goldset)

    assert report["status"] == "fail"
    assert report["failed_languages"] == ["typescript"]
    assert report["per_language"]["typescript"]["false_positive"] == 1
    assert report["consumer_enablement"]["eligible_for_review"] is False


def test_benchmark_identity_is_stable_and_minimal():
    record = _artifact()["records"][0]

    assert benchmark_identity(record) == {
        "record_type": record["record_type"],
        "relation": record["relation"],
        "symbol": record["symbol"],
        "target_symbol": record["target_symbol"],
        "path": record["source"]["path"],
        "start_line": record["source"]["range"]["start_line"],
    }


def test_invalid_digests_and_thresholds_fail_closed():
    with pytest.raises(ScipAdapterError, match="index_sha256"):
        normalize_scip_index(_index(), index_sha256="bad", repository_commit=REPOSITORY_COMMIT)
    with pytest.raises(ScipAdapterError, match="repository_commit"):
        normalize_scip_index(_index(), index_sha256=INDEX_SHA, repository_commit="bad")
    with pytest.raises(ValueError, match="minimum_precision"):
        evaluate_scip_adapter(_artifact(), _goldset(), minimum_precision=1.1)
