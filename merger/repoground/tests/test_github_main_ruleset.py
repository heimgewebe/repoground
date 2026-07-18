import copy
import json
from pathlib import Path

import pytest

from scripts.ci.check_github_main_ruleset import (
    RulesetValidationError,
    api_payload,
    load_policy,
    validate_ruleset,
)

ROOT = Path(__file__).resolve().parents[3]


def _observed():
    policy = load_policy()
    observed = api_payload(policy)
    observed["id"] = 1234
    observed["source"] = policy["repository"]
    observed["source_type"] = policy["source_type"]
    return policy, observed


def test_required_checks_policy_matches_observed_ruleset():
    policy, observed = _observed()

    report = validate_ruleset(policy, observed)

    assert report["status"] == "pass"
    assert report["ruleset_id"] == 1234
    assert report["observed_source"] == "heimgewebe/repoground"
    assert report["observed_source_type"] == "Repository"
    assert report["findings"] == []
    assert {item["context"] for item in report["required_checks"]} == {
        "Lenskit CodeQL policy (python)",
        "CodeQL",
        "pytest-full",
        "release-candidate",
        "ruff",
        "webui-js-tests",
        "ai-context-guard",
        "browser-tests",
    }
    assert "github_runtime_enforcement" in report["does_not_establish"]


def test_required_checks_policy_detects_wrong_repository_source():
    policy, observed = _observed()
    observed["source"] = "other-owner/lenskit-fork"

    report = validate_ruleset(policy, observed)

    assert report["status"] == "fail"
    assert any("source mismatch" in finding for finding in report["findings"])


def test_required_checks_policy_detects_missing_or_wrong_source_type():
    policy, observed = _observed()
    observed["source_type"] = "Organization"

    report = validate_ruleset(policy, observed)

    assert report["status"] == "fail"
    assert any("source_type mismatch" in finding for finding in report["findings"])


def test_required_checks_policy_detects_missing_check():
    policy, observed = _observed()
    observed["rules"][0]["parameters"]["required_status_checks"].pop()

    report = validate_ruleset(policy, observed)

    assert report["status"] == "fail"
    assert any("missing required checks" in finding for finding in report["findings"])


def test_required_checks_policy_detects_wrong_integration():
    policy, observed = _observed()
    observed["rules"][0]["parameters"]["required_status_checks"][0][
        "integration_id"
    ] = 999

    report = validate_ruleset(policy, observed)

    assert report["status"] == "fail"
    assert any("missing required checks" in finding for finding in report["findings"])
    assert any(
        "unexpected required checks" in finding for finding in report["findings"]
    )


def test_required_checks_policy_detects_inactive_or_wrong_scope():
    policy, observed = _observed()
    observed["enforcement"] = "disabled"
    observed["conditions"]["ref_name"]["include"] = ["refs/heads/release"]

    report = validate_ruleset(policy, observed)

    assert report["status"] == "fail"
    assert any("enforcement mismatch" in finding for finding in report["findings"])
    assert any("conditions mismatch" in finding for finding in report["findings"])


def test_required_checks_policy_rejects_ambiguous_extra_rule():
    policy, observed = _observed()
    observed["rules"].append(copy.deepcopy(observed["rules"][0]))

    report = validate_ruleset(policy, observed)

    assert report["status"] == "fail"
    assert any("exactly one rule" in finding for finding in report["findings"])


def test_required_checks_policy_detects_bypass_actor():
    policy, observed = _observed()
    observed["bypass_actors"] = [
        {"actor_id": 1, "actor_type": "RepositoryRole", "bypass_mode": "always"}
    ]

    report = validate_ruleset(policy, observed)

    assert report["status"] == "fail"
    assert any("bypass_actors mismatch" in finding for finding in report["findings"])


def test_codeql_transition_context_is_bound_to_canonical_policy():
    workflow = (ROOT / ".github" / "workflows" / "codeql.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count("name: RepoGround CodeQL policy (python)") == 1
    assert workflow.count("name: Lenskit CodeQL policy (python)") == 1
    assert "name: Validate CodeQL suppression inventory" in workflow
    assert "name: Require clean raw CodeQL SARIF" in workflow
    assert "legacy-context:" in workflow
    assert "needs: analyze" in workflow
    assert "CANONICAL_RESULT: ${{ needs.analyze.result }}" in workflow
    assert 'run: test "$CANONICAL_RESULT" = success' in workflow


def test_required_checks_policy_rejects_invalid_policy_rule_shape():
    policy, observed = _observed()
    policy["ruleset"]["rules"] = []

    with pytest.raises(RulesetValidationError, match="exactly one"):
        validate_ruleset(policy, observed)


def test_grabowski_required_check_catalog_matches_ruleset_policy():
    policy = load_policy()
    expected = [
        item["context"]
        for item in policy["ruleset"]["rules"][0]["parameters"][
            "required_status_checks"
        ]
    ]
    catalog = json.loads(
        (ROOT / ".github" / "grabowski-required-checks.json").read_text(
            encoding="utf-8"
        )
    )

    assert catalog == {"schema_version": 1, "required_checks": expected}


def test_release_candidate_required_context_runs_for_every_main_pr():
    workflow = (ROOT / ".github" / "workflows" / "test-suite.yml").read_text(
        encoding="utf-8"
    )
    trigger_header, jobs = workflow.split("\njobs:", 1)

    assert "pull_request:" in trigger_header
    assert "branches: [main]" in trigger_header
    assert "paths:" not in trigger_header
    assert "\n  release-candidate:" in "\njobs:" + jobs
    assert "name: release-candidate" in jobs
