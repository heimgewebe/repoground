import copy
import json
from pathlib import Path

import jsonschema

from merger.repoground.core.agent_impact_context import build_agent_impact_context
from merger.repoground.core.system_relation_producer import (
    collect_system_relation_evidence,
)
from merger.repoground.tests.git_fixture import commit_fixture

OTHER_COMMIT = "0" * 40
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "contracts" / "agent-impact-context.v1.schema.json"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _producer_result(root: Path) -> dict:
    _write(root / "pyproject.toml", "[tool.repoground]\nenabled = true\n")
    commit = commit_fixture(root)
    return collect_system_relation_evidence(
        root,
        repository_identity="example/repository",
        repository_commit=commit,
    )


def test_impact_context_uses_coherent_structural_evidence_without_call_graph_mixing(tmp_path):
    producer_result = _producer_result(tmp_path)

    context = build_agent_impact_context(
        target_path="pyproject.toml",
        repository_commit=producer_result["repository"]["commit"],
        system_relation_result=producer_result,
    )
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(context, schema)

    assert context["status"] == "partial"
    assert context["target"]["paths"] == ["pyproject.toml"]
    assert context["relations"] == []
    assert context["structural_relations"]["status"] == "available"
    assert context["structural_relations"]["relevant_record_count"] == 1
    relation = context["structural_relations"]["records"][0]
    assert relation["relation"] == "declares_config"
    assert relation["relation"] not in {"calls", "constructs"}
    assert context["composition"]["system_relation_evidence_used"] is True


def test_impact_context_blocks_commit_mismatch_without_false_target_activation(tmp_path):
    producer_result = _producer_result(tmp_path)

    context = build_agent_impact_context(
        target_path="pyproject.toml",
        repository_commit=OTHER_COMMIT,
        system_relation_result=producer_result,
    )

    assert context["status"] == "missing_target"
    assert context["structural_relations"]["status"] == "blocked"
    assert context["structural_relations"]["reason"] == "repository_commit_mismatch"
    assert context["structural_relations"]["records"] == []
    assert context["composition"]["system_relation_evidence_used"] is False
    assert any(
        gap.get("source") == "system_relation_evidence"
        and gap.get("reason") == "repository_commit_mismatch"
        for gap in context["gaps"]
    )


def test_impact_context_blocks_digest_mismatch_without_false_target_activation(tmp_path):
    producer_result = _producer_result(tmp_path)
    tampered = copy.deepcopy(producer_result)
    tampered["evidence"]["producer"]["version"] = "tampered"

    context = build_agent_impact_context(
        target_path="pyproject.toml",
        repository_commit=producer_result["repository"]["commit"],
        system_relation_result=tampered,
    )

    assert context["status"] == "missing_target"
    assert context["structural_relations"]["status"] == "blocked"
    assert context["structural_relations"]["reason"] == "evidence_digest_mismatch"
    assert context["structural_relations"]["records"] == []
    assert context["composition"]["system_relation_evidence_used"] is False


def test_impact_context_makes_missing_structural_evidence_visible_when_requested():
    context = build_agent_impact_context(
        target_path="pyproject.toml",
        repository_commit="f" * 40,
        system_relation_result=None,
    )

    assert context["structural_relations"]["status"] == "missing"
    assert context["structural_relations"]["reason"] == "system_relation_evidence_missing"
    assert context["composition"]["system_relation_evidence_used"] is False
    assert any(
        gap.get("source") == "system_relation_evidence"
        and gap.get("status") == "missing"
        for gap in context["gaps"]
    )
