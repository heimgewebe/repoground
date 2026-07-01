import json

from merger.lenskit.cli.main import main
from merger.lenskit.core.token_budget_report import build_token_budget_report


def _manifest():
    return {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "artifacts": [
            {"role": "canonical_md", "path": "bundle.md", "bytes": 400, "sha256": "a" * 64, "content_type": "text/markdown"},
            {"role": "agent_reading_pack", "path": "bundle.agent.md", "bytes": 40, "sha256": "b" * 64, "content_type": "text/markdown"},
            {"role": "chunk_index_jsonl", "path": "bundle.chunk.jsonl", "bytes": 160, "sha256": "c" * 64, "content_type": "application/jsonl"},
        ],
    }


def test_token_budget_report_estimates_from_manifest_bytes():
    report = build_token_budget_report(_manifest(), context_budget_tokens=200, bytes_per_token=4.0)

    assert report["kind"] == "lenskit.token_budget_report"
    assert report["status"] == "pass"
    assert report["totals"]["bytes"] == 600
    assert report["totals"]["estimated_tokens"] == 150
    assert report["totals"]["budget_remaining_tokens"] == 50
    assert report["largest_artifacts"][0]["role"] == "canonical_md"
    assert "exact_token_count" in report["does_not_establish"]


def test_token_budget_report_warns_when_estimate_exceeds_context_budget():
    report = build_token_budget_report(_manifest(), context_budget_tokens=100, bytes_per_token=4.0)

    assert report["status"] == "warn"
    assert report["totals"]["budget_overflow_tokens"] == 50
    assert "estimated_tokens_exceed_context_budget" in report["warnings"]


def test_token_budget_report_fails_invalid_artifact_bytes():
    manifest = _manifest()
    manifest["artifacts"].append({"role": "output_health", "path": "bad.json", "bytes": -1})

    report = build_token_budget_report(manifest, context_budget_tokens=200, bytes_per_token=4.0)

    assert report["status"] == "fail"
    assert "artifact_3_invalid_bytes" in report["errors"]


def test_token_budget_cli_report_outputs_json(tmp_path, capsys):
    manifest = tmp_path / "bundle.manifest.json"
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")

    rc = main([
        "token-budget",
        "report",
        "--bundle-manifest",
        str(manifest),
        "--context-budget",
        "200",
    ])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "pass"
    assert data["source_manifest"] == str(manifest)


def test_token_budget_cli_strict_warn_returns_one(tmp_path, capsys):
    manifest = tmp_path / "bundle.manifest.json"
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")

    rc = main([
        "token-budget",
        "report",
        "--bundle-manifest",
        str(manifest),
        "--context-budget",
        "100",
        "--strict",
    ])

    assert rc == 1
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "warn"
