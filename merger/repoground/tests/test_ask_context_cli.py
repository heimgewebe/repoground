import hashlib
import json
from pathlib import Path

import jsonschema

from merger.repoground.cli.main import main
from merger.repoground.core.ask_context import build_ask_context_pack
from merger.repoground.tests.test_resolved_evidence_query import _build_resolved_bundle

CONTEXT_SCHEMA = Path(__file__).parent.parent / "contracts" / "repobrief-ask-context-pack.v1.schema.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _add_artifact(bundle: dict, role: str, filename: str, content: str = "ok\n") -> None:
    manifest = bundle["manifest"]
    artifact_path = manifest.parent / filename
    artifact_path.write_text(content, encoding="utf-8")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    artifacts = data.setdefault("artifacts", [])
    artifacts.append({
        "role": role,
        "path": filename,
        "content_type": "application/json" if filename.endswith(".json") else "text/markdown",
        "bytes": artifact_path.stat().st_size,
        "sha256": _sha256(artifact_path),
    })
    manifest.write_text(json.dumps(data), encoding="utf-8")


def _complete_basic_bundle(tmp_path: Path) -> dict:
    bundle = _build_resolved_bundle(tmp_path)
    _add_artifact(bundle, "agent_reading_pack", "demo.agent_reading_pack.md", "# Agent pack\n")
    _add_artifact(bundle, "snapshot_plan_json", "demo.snapshot_plan.json", "{}\n")
    return bundle


def _complete_pr_review_bundle(tmp_path: Path) -> dict:
    bundle = _complete_basic_bundle(tmp_path)
    _add_artifact(bundle, "post_emit_health", "demo.bundle_health.post.json", "{}\n")
    _add_artifact(bundle, "bundle_surface_validation", "demo.bundle_surface_validation.json", "{}\n")
    _add_artifact(bundle, "claim_evidence_map_json", "demo.claim_evidence_map.json", "{}\n")
    return bundle


def _validate_context_pack(pack: dict) -> None:
    schema = json.loads(CONTEXT_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(instance=pack, schema=schema)


def test_build_ask_context_pack_json_for_basic_profile(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)

    pack = build_ask_context_pack(
        bundle["manifest"],
        query="hello",
        task_profile="basic_repo_question",
        max_context_tokens=8000,
        max_answer_tokens=1200,
        k=5,
    )

    _validate_context_pack(pack)
    assert pack["kind"] == "repobrief.ask_context_pack"
    assert pack["required_reading"]["status"] == "pass"
    assert pack["retrieval_hits"]
    assert pack["resolved_ranges"][0]["status"] == "resolved"
    assert "hello resolved world" in pack["resolved_ranges"][0]["text_excerpt"]
    assert pack["budget"]["max_context_tokens"] == 8000
    assert pack["budget"]["does_not_establish_quality"] is True
    assert pack["forbidden_operations"] == [
        "implicit_refresh",
        "git_mutation",
        "snapshot_creation_on_read",
        "patch_application",
        "pull_request_mutation",
        "shell_execution",
        "merge_authorization",
    ]


def test_ask_context_cli_emits_json_context_pack(tmp_path, capsys):
    bundle = _complete_basic_bundle(tmp_path)

    rc = main([
        "repobrief",
        "ask",
        "--bundle-manifest",
        str(bundle["manifest"]),
        "--q",
        "hello",
        "--task-profile",
        "basic_repo_question",
        "--context-budget",
        "8000",
        "--answer-budget",
        "1200",
        "--emit",
        "json",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    pack = json.loads(captured.out)
    _validate_context_pack(pack)
    assert pack["required_reading"]["status"] == "pass"
    assert pack["retrieval_hits"]
    assert pack["does_not_establish"]


def test_ask_context_cli_emits_human_context_pack(tmp_path, capsys):
    bundle = _complete_basic_bundle(tmp_path)

    rc = main([
        "repobrief",
        "ask",
        "--bundle-manifest",
        str(bundle["manifest"]),
        "--q",
        "hello",
        "--emit",
        "text",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    assert "RepoGround Ask Context Pack" in captured.out
    assert "Citation obligations" in captured.out
    assert "Non-claims" in captured.out


def test_ask_context_cli_stricter_profile_smoke(tmp_path, capsys):
    bundle = _complete_pr_review_bundle(tmp_path)

    rc = main([
        "repobrief",
        "ask",
        "--bundle-manifest",
        str(bundle["manifest"]),
        "--q",
        "hello",
        "--task-profile",
        "pr_review",
        "--emit",
        "json",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    pack = json.loads(captured.out)
    _validate_context_pack(pack)
    assert pack["required_reading"]["task_profile"] == "pr_review"
    assert pack["required_reading"]["status"] == "pass"


def test_ask_context_budget_truncates_without_quality_claim(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)

    pack = build_ask_context_pack(
        bundle["manifest"],
        query="hello",
        task_profile="basic_repo_question",
        max_context_tokens=1,
        max_answer_tokens=1200,
        k=5,
    )

    _validate_context_pack(pack)
    assert pack["budget"]["truncated"] is True
    assert pack["budget"]["does_not_establish_quality"] is True
    assert any("truncated" in caveat["detail"] for caveat in pack["answer_scaffold"]["caveats_to_surface"])


def test_ask_context_missing_required_profile_returns_failure(tmp_path, capsys):
    bundle = _build_resolved_bundle(tmp_path)

    rc = main([
        "repobrief",
        "ask",
        "--bundle-manifest",
        str(bundle["manifest"]),
        "--q",
        "hello",
        "--task-profile",
        "pr_review",
        "--emit",
        "json",
    ])

    captured = capsys.readouterr()
    assert rc == 1
    pack = json.loads(captured.out)
    assert pack["required_reading"]["status"] == "fail"
    assert "post_emit_health" in pack["required_reading"]["missing_required"]
