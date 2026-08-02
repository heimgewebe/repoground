import json
from pathlib import Path

import jsonschema
import pytest

from merger.repoground import core as core_api
from merger.repoground.core.scip_adapter import (
    ScipAdapterError,
    benchmark_identity,
    evaluate_scip_adapter,
    normalize_scip_index,
)

INDEX_SHA = "e" * 64
REPOSITORY_COMMIT = "f" * 40
SYMBOL = "scip-go gomod demo 1.0.0 demo/run()."


def _schema(name: str):
    return json.loads(
        (Path(__file__).parent.parent / "contracts" / name).read_text(
            encoding="utf-8"
        )
    )


def _index(*, tool_info=True, metadata_overrides=None, position_encoding=1):
    metadata = {
        "version": 0,
        "projectRoot": "file:///workspace/demo",
        "textDocumentEncoding": "UTF8",
    }
    if tool_info:
        metadata["toolInfo"] = {
            "name": "scip-go",
            "version": "1.0",
            "arguments": [],
        }
    if metadata_overrides:
        metadata.update(metadata_overrides)
    return {
        "metadata": metadata,
        "documents": [
            {
                "relativePath": "main.go",
                "language": "go",
                "positionEncoding": position_encoding,
                "occurrences": [
                    {"range": [0, 0, 3], "symbol": SYMBOL, "symbolRoles": 1}
                ],
                "symbols": [],
            }
        ],
    }


def _artifact(**kwargs):
    return normalize_scip_index(
        _index(**kwargs),
        index_sha256=INDEX_SHA,
        repository_commit=REPOSITORY_COMMIT,
    )


def _goldset(artifact):
    return {"go": [benchmark_identity(artifact["records"][0])]}


def test_public_core_api_exports_the_scip_adapter_without_promotion():
    assert core_api.ScipAdapterError is ScipAdapterError
    assert core_api.normalize_scip_index is normalize_scip_index
    assert core_api.evaluate_scip_adapter is evaluate_scip_adapter
    assert core_api.benchmark_identity is benchmark_identity
    assert {
        "ScipAdapterError",
        "normalize_scip_index",
        "evaluate_scip_adapter",
        "benchmark_identity",
    } <= set(core_api.__all__)


def test_degraded_artifact_cannot_become_review_eligible():
    artifact = _artifact(tool_info=False)

    report = evaluate_scip_adapter(artifact, _goldset(artifact))

    assert artifact["status"] == "degraded"
    assert report["artifact_status"] == "degraded"
    assert report["status"] == "warn"
    assert report["per_language"]["go"]["precision"] == 1.0
    assert report["per_language"]["go"]["recall"] == 1.0
    assert report["eligible_languages"] == []
    assert report["consumer_enablement"] == {
        "eligible_for_review": False,
        "default_promoted": False,
    }
    jsonschema.validate(
        instance=report,
        schema=_schema("scip-adapter-benchmark.v1.schema.json"),
    )


def test_empty_goldset_is_rejected_instead_of_passing_vacuously():
    with pytest.raises(ValueError, match="at least one language"):
        evaluate_scip_adapter(_artifact(), {})


def test_empty_language_goldset_is_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        evaluate_scip_adapter(_artifact(), {"go": []})


def test_casefold_duplicate_goldset_languages_are_rejected():
    artifact = _artifact()
    identity = benchmark_identity(artifact["records"][0])

    with pytest.raises(ValueError, match="unique after case folding"):
        evaluate_scip_adapter(artifact, {"Go": [identity], "go": [identity]})


def test_boolean_position_encoding_is_rejected_not_treated_as_numeric_one():
    artifact = _artifact(position_encoding=True)

    assert artifact["status"] == "degraded"
    assert artifact["records"] == []
    assert any(
        item["code"] == "position_encoding_unsupported"
        and item["document"] == "main.go"
        for item in artifact["degradations"]
    )
    jsonschema.validate(
        instance=artifact,
        schema=_schema("scip-symbol-relations.v1.schema.json"),
    )


def test_non_scalar_metadata_degrades_to_schema_valid_nulls():
    artifact = _artifact(
        metadata_overrides={
            "version": {"unexpected": "object"},
            "textDocumentEncoding": ["UTF8"],
        }
    )

    assert artifact["status"] == "degraded"
    assert artifact["source"]["protocol_version"] is None
    assert artifact["source"]["text_document_encoding"] is None
    assert {item["code"] for item in artifact["degradations"]} >= {
        "protocol_version_invalid",
        "text_document_encoding_invalid",
    }
    jsonschema.validate(
        instance=artifact,
        schema=_schema("scip-symbol-relations.v1.schema.json"),
    )
