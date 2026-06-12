"""Static usage-rule smoke tests for the Agent Reading Pack v1.1 front door."""

import re
from pathlib import Path

from merger.lenskit.core.agent_reading_pack import produce_agent_reading_pack
from merger.lenskit.tests.test_agent_reading_pack import _make_bundle


_TASK_PROFILES = (
    "basic_repo_question",
    "pr_review",
    "roadmap_status_claim",
    "artifact_surface_review",
    "retrieval_quality_review",
)


def _section(body: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing section {heading}"
    return match.group(1)


def _row_for_profile(body: str, profile: str) -> dict[str, str]:
    section = _section(body, "REQUIRED_READING_BY_TASK")
    table_lines = [line for line in section.splitlines() if line.startswith("|")]
    headers = [cell.strip() for cell in table_lines[0].strip("|").split("|")]

    for line in table_lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        row = dict(zip(headers, cells, strict=True))
        if row["task_profile"] == f"`{profile}`":
            return row

    raise AssertionError(f"missing task profile row: {profile}")


def _pack_text(tmp_path: Path) -> str:
    manifest = _make_bundle(tmp_path)
    report = produce_agent_reading_pack(str(manifest))
    assert report["status"] == "ok"
    return Path(report["output_path"]).read_text(encoding="utf-8")


def test_agent_pack_usage_profiles_are_complete(tmp_path):
    body = _pack_text(tmp_path)

    for profile in _TASK_PROFILES:
        row = _row_for_profile(body, profile)
        assert row["required"]
        assert row["recommended"]
        assert row["insufficient"]


def test_agent_pack_usage_profiles_require_expected_sidecars(tmp_path):
    body = _pack_text(tmp_path)

    expected_required = {
        "pr_review": {"citation_map_jsonl"},
        "roadmap_status_claim": {"claim_evidence_map_json"},
        "artifact_surface_review": {"post_emit_health", "bundle_surface_validation"},
        "retrieval_quality_review": {"retrieval_eval_json"},
    }
    for profile, roles in expected_required.items():
        required = _row_for_profile(body, profile)["required"]
        for role in roles:
            assert f"`{role}`" in required


def test_canonical_only_insufficiency_is_explicit_for_heavy_profiles(tmp_path):
    body = _pack_text(tmp_path)
    section = _section(body, "WHEN_CANONICAL_MD_ONLY_IS_INSUFFICIENT")

    assert "`canonical_md` contains the content truth, but some tasks require sidecars" in section
    for task_boundary in (
        "PR review with evidence requirements",
        "Roadmap or status claims",
        "Bundle or surface health assessment",
        "Retrieval quality assessment",
    ):
        assert task_boundary in section

    for profile in _TASK_PROFILES[1:]:
        assert _row_for_profile(body, profile)["insufficient"]


def test_agent_pack_usage_rules_preserve_authority_boundaries(tmp_path):
    body = _pack_text(tmp_path)
    section = _section(body, "SIDECAR_USAGE_RULES")

    assert "Sidecars are navigation, diagnostic signals, indexes or caches" in section
    assert "they are not content truth" in section
    assert "`canonical_md`, the only content truth" in section
    assert "`citation_map_jsonl` maps stable citation IDs to canonical ranges" in section
    assert "`claim_evidence_map_json` is an evidence-navigation index, not truth" in section
    assert "`output_health` is a pre-/emit diagnostic signal" in section
    assert "must not be read as forensic readiness" in section
    assert "`post_emit_health` is post-emit surface diagnosis, not repo understanding" in section
    assert "`bundle_surface_validation` is surface coherence validation, not claim truth" in section


def test_basic_repo_question_stays_lightweight(tmp_path):
    body = _pack_text(tmp_path)
    row = _row_for_profile(body, "basic_repo_question")

    assert "`canonical_md`" in row["required"]
    for heavy_sidecar in (
        "citation_map_jsonl",
        "claim_evidence_map_json",
        "retrieval_eval_json",
    ):
        assert f"`{heavy_sidecar}`" not in row["required"]
