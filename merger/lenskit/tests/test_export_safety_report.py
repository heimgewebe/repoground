import json
from pathlib import Path

import pytest
from jsonschema import validate

from merger.lenskit.core.export_safety_report import _DOES_NOT_ESTABLISH, build_export_safety_report


@pytest.fixture(scope="module")
def schema():
    schema_path = Path(__file__).parent.parent / "contracts" / "export-safety-report.v1.schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _validate(report: dict, schema: dict):
    validate(instance=report, schema=schema)


def test_export_safety_report_local_private_pass_without_redaction(schema):
    report = build_export_safety_report(
        profile="local-private",
        output_health={"checks": {"redact_secrets_enabled": False}},
    )
    _validate(report, schema)
    assert report["status"] == "pass"
    assert report["profile_known"] is True
    assert report["agent_facing"] is False
    assert report["public_facing"] is False
    assert report["redaction_required"] is False
    assert report["redaction_observed"] is False
    assert report["redaction_source"] == "output_health"
    assert report["post_emit_health_required"] is False
    assert report["agent_export_gate_required"] is False
    assert set(_DOES_NOT_ESTABLISH).issubset(set(report["does_not_establish"]))


def test_export_safety_report_debug_full_agent_facing_fails(schema):
    report = build_export_safety_report(
        profile="debug-full",
        agent_facing=True,
        output_health={"checks": {"redact_secrets_enabled": False}},
    )
    _validate(report, schema)
    assert report["status"] == "fail"
    assert "debug_full_cannot_be_agent_facing" in report["errors"]
    assert report["agent_facing"] is True
    assert report["public_facing"] is False


def test_export_safety_report_debug_full_public_facing_fails(schema):
    report = build_export_safety_report(
        profile="debug-full",
        public_facing=True,
    )
    _validate(report, schema)
    assert report["status"] == "fail"
    assert "debug_full_cannot_be_public_facing" in report["errors"]


def test_export_safety_report_agent_portable_requires_redaction(schema):
    report = build_export_safety_report(
        profile="agent-portable",
        post_emit_health={
            "status": "pass",
            "redaction_status": {
                "available": True,
                "redact_secrets_enabled": False,
                "enforced": False,
            },
        },
        agent_export_gate={"status": "pass"},
    )
    _validate(report, schema)
    assert report["status"] == "fail"
    assert report["agent_facing"] is True
    assert report["public_facing"] is False
    assert report["redaction_required"] is True
    assert report["redaction_observed"] is False
    assert report["redaction_source"] == "post_emit_health"
    assert "redaction_required_but_not_observed" in report["errors"]


def test_export_safety_report_agent_portable_passes_with_required_signals(schema):
    report = build_export_safety_report(
        profile="agent-portable",
        post_emit_health={
            "status": "pass",
            "redaction_status": {
                "available": True,
                "redact_secrets_enabled": True,
                "enforced": False,
            },
        },
        agent_export_gate={"status": "pass"},
    )
    _validate(report, schema)
    assert report["status"] == "pass"
    assert report["redaction_required"] is True
    assert report["redaction_observed"] is True
    assert report["post_emit_health_required"] is True
    assert report["post_emit_health_status"] == "pass"
    assert report["agent_export_gate_required"] is True
    assert report["agent_export_gate_status"] == "pass"


def test_export_safety_report_public_share_fails_without_redaction(schema):
    report = build_export_safety_report(
        profile="public-share",
        post_emit_health={
            "status": "pass",
            "redaction_status": {
                "available": True,
                "redact_secrets_enabled": False,
                "enforced": False,
            },
        },
        agent_export_gate={"status": "pass"},
    )
    _validate(report, schema)
    assert report["status"] == "fail"
    assert report["public_facing"] is True
    assert report["redaction_required"] is True
    assert "redaction_required_but_not_observed" in report["errors"]
    assert "secret_absence" in report["does_not_establish"]
    assert "pii_absence" in report["does_not_establish"]


def test_export_safety_report_ci_artifact_fails_when_post_emit_missing(schema):
    report = build_export_safety_report(
        profile="ci-artifact",
        output_health={"checks": {"redact_secrets_enabled": True}},
        agent_export_gate={"status": "pass"},
    )
    _validate(report, schema)
    assert report["status"] == "fail"
    assert report["post_emit_health_required"] is True
    assert report["post_emit_health_status"] == "missing"
    assert "post_emit_health_required_but_missing_or_not_pass" in report["errors"]


def test_export_safety_report_output_health_pass_does_not_replace_post_emit_health(schema):
    report = build_export_safety_report(
        profile="agent-portable",
        post_emit_health=None,
        output_health={
            "verdict": "pass",
            "checks": {"redact_secrets_enabled": True},
        },
        agent_export_gate={"status": "pass"},
    )
    _validate(report, schema)
    assert report["status"] == "fail"
    assert report["redaction_observed"] is True
    assert report["redaction_source"] == "output_health"
    assert report["post_emit_health_status"] == "missing"
    assert "post_emit_health_required_but_missing_or_not_pass" in report["errors"]


def test_export_safety_report_agent_portable_fails_without_agent_export_gate(schema):
    report = build_export_safety_report(
        profile="agent-portable",
        post_emit_health={
            "status": "pass",
            "redaction_status": {"redact_secrets_enabled": True},
        },
        agent_export_gate=None,
    )
    _validate(report, schema)
    assert report["status"] == "fail"
    assert report["agent_export_gate_required"] is True
    assert report["agent_export_gate_status"] is None
    assert "agent_export_gate_required_but_missing_or_not_pass" in report["errors"]


def test_export_safety_report_fails_when_agent_export_gate_blocked(schema):
    report = build_export_safety_report(
        profile="agent-portable",
        post_emit_health={
            "status": "pass",
            "redaction_status": {"redact_secrets_enabled": True},
        },
        agent_export_gate={"status": "blocked", "errors": ["blocked_by_policy"]},
    )
    _validate(report, schema)
    assert report["status"] == "fail"
    assert report["agent_export_gate_status"] == "blocked"
    assert "agent_export_gate_required_but_missing_or_not_pass" in report["errors"]


def test_export_safety_report_ignores_malformed_optional_inputs(schema):
    report = build_export_safety_report(
        profile="local-private",
        post_emit_health=True,
        output_health=404,
        agent_export_gate="bad",
    )
    _validate(report, schema)
    assert report["status"] == "pass"
    assert report["redaction_observed"] is None
    assert report["redaction_source"] is None
    assert report["post_emit_health_required"] is False
    assert report["agent_export_gate_required"] is False


def test_export_safety_report_unknown_profile_fails_with_machine_readable_report(schema):
    report = build_export_safety_report(profile="moon-export")
    _validate(report, schema)
    assert report["status"] == "fail"
    assert report["profile"] == "moon-export"
    assert report["profile_known"] is False
    assert "unknown_profile:moon-export" in report["errors"]


def test_export_safety_report_prefers_post_emit_redaction_over_output_health(schema):
    report = build_export_safety_report(
        profile="agent-portable",
        post_emit_health={
            "status": "pass",
            "redaction_status": {"redact_secrets_enabled": False},
        },
        output_health={
            "checks": {"redact_secrets_enabled": True},
        },
        agent_export_gate={"status": "pass"},
    )
    _validate(report, schema)
    assert report["redaction_observed"] is False
    assert report["redaction_source"] == "post_emit_health"
    assert report["status"] == "fail"


def test_export_safety_report_unknown_post_emit_status_stays_schema_valid(schema):
    report = build_export_safety_report(
        profile="agent-portable",
        post_emit_health={
            "status": "skipped",
            "redaction_status": {"redact_secrets_enabled": True},
        },
        agent_export_gate={"status": "pass"},
    )

    _validate(report, schema)
    assert report["status"] == "fail"
    assert report["post_emit_health_status"] == "error"
    assert "post_emit_health_required_but_missing_or_not_pass" in report["errors"]
    assert "post_emit_health_unknown_status:skipped" in report["errors"]


def test_export_safety_report_local_private_unknown_post_emit_status_remains_schema_valid(schema):
    report = build_export_safety_report(
        profile="local-private",
        post_emit_health={"status": "skipped"},
    )

    _validate(report, schema)
    assert report["post_emit_health_status"] == "error"
    assert report["status"] == "pass"


def test_export_safety_report_observes_root_output_health_redaction(schema):
    report = build_export_safety_report(
        profile="agent-portable",
        post_emit_health={"status": "pass"},
        output_health={"redact_secrets_enabled": True},
        agent_export_gate={"status": "pass"},
    )

    _validate(report, schema)
    assert report["redaction_observed"] is True
    assert report["redaction_source"] == "output_health"


def test_export_safety_report_agent_portable_fails_with_empty_agent_export_gate(schema):
    report = build_export_safety_report(
        profile="agent-portable",
        post_emit_health={
            "status": "pass",
            "redaction_status": {"redact_secrets_enabled": True},
        },
        agent_export_gate={},
    )

    _validate(report, schema)
    assert report["status"] == "fail"
    assert report["agent_export_gate_required"] is True
    assert report["agent_export_gate_status"] is None
    assert "agent_export_gate_required_but_missing_or_not_pass" in report["errors"]


def test_export_safety_report_agent_portable_fails_with_warn_agent_export_gate(schema):
    report = build_export_safety_report(
        profile="agent-portable",
        post_emit_health={
            "status": "pass",
            "redaction_status": {"redact_secrets_enabled": True},
        },
        agent_export_gate={"status": "warn"},
    )

    _validate(report, schema)
    assert report["status"] == "fail"
    assert report["agent_export_gate_status"] == "warn"
    assert "agent_export_gate_required_but_missing_or_not_pass" in report["errors"]


def test_export_safety_report_agent_portable_fails_when_post_emit_status_missing(schema):
    report = build_export_safety_report(
        profile="agent-portable",
        post_emit_health={
            "redaction_status": {"redact_secrets_enabled": True},
        },
        agent_export_gate={"status": "pass"},
    )

    _validate(report, schema)
    assert report["status"] == "fail"
    assert report["post_emit_health_status"] == "missing"
    assert "post_emit_health_required_but_missing_or_not_pass" in report["errors"]


def test_export_safety_report_public_share_allows_explicit_agent_facing_when_required_signals_pass(schema):
    report = build_export_safety_report(
        profile="public-share",
        agent_facing=True,
        post_emit_health={
            "status": "pass",
            "redaction_status": {"redact_secrets_enabled": True},
        },
        agent_export_gate={"status": "pass"},
    )

    _validate(report, schema)
    assert report["status"] == "pass"
    assert report["public_facing"] is True
    assert report["agent_facing"] is True


def test_export_safety_report_local_private_public_facing_requires_safety_signals(schema):
    report = build_export_safety_report(
        profile="local-private",
        public_facing=True,
    )

    _validate(report, schema)
    assert report["status"] == "fail"
    assert report["public_facing"] is True
    assert report["redaction_required"] is True
    assert report["post_emit_health_required"] is True
    assert report["agent_export_gate_required"] is True
    assert "redaction_required_but_not_observed" in report["errors"]
    assert "post_emit_health_required_but_missing_or_not_pass" in report["errors"]
    assert "agent_export_gate_required_but_missing_or_not_pass" in report["errors"]


def test_export_safety_report_local_private_agent_facing_requires_safety_signals(schema):
    report = build_export_safety_report(
        profile="local-private",
        agent_facing=True,
    )

    _validate(report, schema)
    assert report["status"] == "fail"
    assert report["agent_facing"] is True
    assert report["redaction_required"] is True
    assert report["post_emit_health_required"] is True
    assert report["agent_export_gate_required"] is True


def test_export_safety_report_local_private_public_facing_passes_with_required_signals(schema):
    report = build_export_safety_report(
        profile="local-private",
        public_facing=True,
        post_emit_health={
            "status": "pass",
            "redaction_status": {"redact_secrets_enabled": True},
        },
        agent_export_gate={"status": "pass"},
    )

    _validate(report, schema)
    assert report["status"] == "pass"
    assert report["public_facing"] is True
    assert report["redaction_required"] is True
    assert report["post_emit_health_status"] == "pass"
    assert report["agent_export_gate_status"] == "pass"


def test_export_safety_report_agent_safe_profile_is_known_and_requires_safety_signals(schema):
    report = build_export_safety_report(
        profile="agent-safe",
        post_emit_health={
            "status": "pass",
            "redaction_status": {"redact_secrets_enabled": True},
        },
        agent_export_gate={"status": "pass"},
    )

    _validate(report, schema)
    assert report["status"] == "pass"
    assert report["profile_known"] is True
    assert report["agent_facing"] is True
    assert report["redaction_required"] is True
    assert report["post_emit_health_required"] is True
    assert report["agent_export_gate_required"] is True


def test_export_safety_report_agent_minimal_profile_is_known_and_requires_safety_signals(schema):
    report = build_export_safety_report(
        profile="agent_minimal",
        post_emit_health={
            "status": "pass",
            "redaction_status": {"redact_secrets_enabled": True},
        },
        agent_export_gate={"status": "pass"},
    )

    _validate(report, schema)
    assert report["status"] == "pass"
    assert report["profile_known"] is True
    assert report["agent_facing"] is True
    assert report["redaction_required"] is True
    assert report["post_emit_health_required"] is True
    assert report["agent_export_gate_required"] is True


def test_export_safety_report_agent_safe_fails_without_required_signals(schema):
    report = build_export_safety_report(profile="agent-safe")

    _validate(report, schema)
    assert report["status"] == "fail"
    assert report["profile_known"] is True
    assert "redaction_required_but_not_observed" in report["errors"]
    assert "post_emit_health_required_but_missing_or_not_pass" in report["errors"]
    assert "agent_export_gate_required_but_missing_or_not_pass" in report["errors"]
