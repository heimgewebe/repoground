from merger.repoground.core.scip_adapter import normalize_scip_index

INDEX_SHA = "c" * 64
REPOSITORY_COMMIT = "d" * 40
SYMBOL = "scip-python python demo 1.0.0 demo/run()."
TARGET = "scip-python python demo 1.0.0 demo/Runner#"


def _metadata():
    return {
        "version": 0,
        "toolInfo": {"name": "scip-python", "version": "1.0", "arguments": []},
        "projectRoot": "file:///workspace/demo",
        "textDocumentEncoding": "UTF8",
    }


def _normalize(index):
    return normalize_scip_index(
        index,
        index_sha256=INDEX_SHA,
        repository_commit=REPOSITORY_COMMIT,
    )


def test_unspecified_position_encoding_is_degraded_and_not_projected():
    artifact = _normalize(
        {
            "metadata": _metadata(),
            "documents": [
                {
                    "relativePath": "src/main.py",
                    "language": "python",
                    "positionEncoding": "UnspecifiedPositionEncoding",
                    "occurrences": [
                        {"range": [0, 0, 3], "symbol": SYMBOL, "symbolRoles": 1}
                    ],
                    "symbols": [],
                }
            ],
        }
    )

    assert artifact["status"] == "degraded"
    assert artifact["records"] == []
    assert artifact["languages"] == []
    assert any(
        item["code"] == "position_encoding_unspecified"
        and item["document"] == "src/main.py"
        for item in artifact["degradations"]
    )


def test_numeric_unspecified_position_encoding_is_also_rejected():
    artifact = _normalize(
        {
            "metadata": _metadata(),
            "documents": [
                {
                    "relativePath": "src/main.py",
                    "language": "python",
                    "positionEncoding": 0,
                    "occurrences": [],
                    "symbols": [],
                }
            ],
        }
    )

    assert any(
        item["code"] == "position_encoding_unspecified"
        for item in artifact["degradations"]
    )


def test_relationship_never_borrows_definition_from_another_document():
    artifact = _normalize(
        {
            "metadata": _metadata(),
            "documents": [
                {
                    "relativePath": "src/a.py",
                    "language": "python",
                    "positionEncoding": "UTF32CodeUnitOffsetFromLineStart",
                    "occurrences": [
                        {"range": [0, 0, 3], "symbol": SYMBOL, "symbolRoles": 1}
                    ],
                    "symbols": [],
                },
                {
                    "relativePath": "src/b.py",
                    "language": "python",
                    "positionEncoding": "UTF32CodeUnitOffsetFromLineStart",
                    "occurrences": [],
                    "symbols": [
                        {
                            "symbol": SYMBOL,
                            "relationships": [
                                {"symbol": TARGET, "isImplementation": True}
                            ],
                        }
                    ],
                },
            ],
        }
    )

    assert artifact["status"] == "degraded"
    assert not any(
        record["record_type"] == "relationship" for record in artifact["records"]
    )
    assert any(
        item["code"] == "relationship_source_definition_document_mismatch"
        and item["document"] == "src/b.py"
        and item["symbol"] == SYMBOL
        for item in artifact["degradations"]
    )


def _relationship_only_index(symbol_information):
    return {
        "metadata": _metadata(),
        "documents": [
            {
                "relativePath": "src/main.py",
                "language": "python",
                "positionEncoding": "UTF32CodeUnitOffsetFromLineStart",
                "occurrences": [],
                "symbols": [symbol_information],
            }
        ],
    }


def test_missing_or_empty_relationships_do_not_require_source_definition():
    for symbol_information in (
        {"symbol": SYMBOL},
        {"symbol": SYMBOL, "relationships": []},
    ):
        artifact = _normalize(_relationship_only_index(symbol_information))

        assert artifact["status"] == "available"
        assert artifact["languages"] == ["python"]
        assert artifact["record_count"] == 0
        assert artifact["records"] == []
        assert artifact["degradations"] == []
        assert artifact["consumer_enablement"] == {
            "requires_language_benchmark": True,
            "eligible_for_review": False,
            "default_promoted": False,
        }


def test_malformed_relationships_remain_fail_closed_without_definition_lookup():
    artifact = _normalize(
        _relationship_only_index({"symbol": SYMBOL, "relationships": {}})
    )

    assert artifact["status"] == "degraded"
    assert artifact["record_count"] == 0
    assert [item["code"] for item in artifact["degradations"]] == [
        "relationships_invalid"
    ]


def test_nonempty_relationships_still_require_exact_source_definition():
    artifact = _normalize(
        _relationship_only_index(
            {
                "symbol": SYMBOL,
                "relationships": [
                    {"symbol": TARGET, "isImplementation": True}
                ],
            }
        )
    )

    assert artifact["status"] == "degraded"
    assert artifact["record_count"] == 0
    assert any(
        item["code"] == "relationship_source_definition_missing"
        for item in artifact["degradations"]
    )
