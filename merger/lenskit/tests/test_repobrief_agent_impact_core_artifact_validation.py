from __future__ import annotations

import json
from pathlib import Path

import pytest

from merger.lenskit.tests.test_repobrief_agent_impact_adapter import (
    _impact_adapter,
)
from merger.lenskit.tests.test_repobrief_readonly_adapter import (
    _seal_existing_artifact,
)


@pytest.mark.parametrize(
    ("payload", "expected_status", "expected_code"),
    [
        ("{\n", "invalid_json", "invalid_json"),
        (
            json.dumps(
                {
                    "kind": "wrong.graph",
                    "version": "1.0",
                    "nodes": [],
                    "edges": [],
                }
            )
            + "\n",
            "invalid_schema",
            "core_artifact_contract_invalid",
        ),
        (
            json.dumps(
                {
                    "kind": "lenskit.architecture.graph",
                    "version": "1.0",
                    "nodes": {},
                    "edges": [],
                }
            )
            + "\n",
            "invalid_schema",
            "core_artifact_contract_invalid",
        ),
    ],
)
def test_hash_valid_but_unusable_core_json_blocks_projection(
    tmp_path: Path,
    payload: str,
    expected_status: str,
    expected_code: str,
) -> None:
    adapter, bundle, config = _impact_adapter(tmp_path)
    graph_path = bundle["manifest"].parent / "demo.architecture_graph.json"
    graph_path.write_text(payload, encoding="utf-8")
    _seal_existing_artifact(bundle, "architecture_graph_json")
    adapter = type(adapter).from_config(config)

    result = adapter.agent_impact_context(
        "demo",
        target_path="src/demo.py",
        include_query_context=False,
    )

    assert result["status"] == "blocked"
    graph_status = next(
        item
        for item in result["source_statuses"]
        if item["source"] == "architecture_graph_json"
    )
    assert graph_status["status"] == expected_status
    assert graph_status["error_code"] == expected_code
    assert result["relations"] == []
    assert any(
        gap.get("reason") == "required_source_untrusted"
        for gap in result["gaps"]
    )
