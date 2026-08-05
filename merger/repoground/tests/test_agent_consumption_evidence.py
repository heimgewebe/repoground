"""Schema, determinism, negative, freshness, replay, mismatch and E2E tests
for agent tool-read receipts and consumption evidence comparison.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional in minimal envs
    jsonschema = None

from merger.repoground.core.agent_consumption_evidence import (
    DOES_NOT_ESTABLISH as EVIDENCE_DNE,
    KIND as EVIDENCE_KIND,
    VERSION as EVIDENCE_VERSION,
    compare_agent_consumption_evidence,
)
from merger.repoground.core.agent_consumption_receipts import (
    DOES_NOT_ESTABLISH as RECEIPT_DNE,
    KIND as RECEIPT_KIND,
    TRUSTED_WRAPPER_ISSUER_ID,
    ToolReadReceiptError,
    TrustedToolReadWrapper,
    canonical_json,
    compute_binding_sha256,
    mint_tool_read_receipt,
    sha256_json,
    validate_tool_read_receipt,
)
from merger.repoground.core.agent_consumption_validate import (
    DOES_NOT_ESTABLISH as TRACE_DNE,
)

_CONTRACTS = Path(__file__).resolve().parent.parent / "contracts"
_RECEIPT_SCHEMA = _CONTRACTS / "agent-tool-read-receipt.v1.schema.json"
_EVIDENCE_SCHEMA = _CONTRACTS / "agent-consumption-evidence.v1.schema.json"

_TASK = "REPOGROUND-AGENT-UTILITY-V1-T005"
_COMMIT = "76ffaaaab3890d85e3db1c46e828809868c4df46"
_AS_OF = "2026-08-05T22:00:00Z"


def _require_jsonschema() -> None:
    if jsonschema is None:
        pytest.skip("jsonschema not installed")


def _load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _answer_compliance(roles: list[str] | None = None) -> dict:
    return {
        "kind": "lenskit.answer_compliance",
        "version": "1.0",
        "task_profile": "pr_review",
        "declared_artifacts": list(roles or ["canonical_md", "agent_reading_pack"]),
        "declared_citations": [],
        "declared_ranges": [],
        "unread_required_artifacts": [],
        "unread_recommended_artifacts": [],
        "epistemic_gaps": [],
        "does_not_establish": list(TRACE_DNE),
    }


def _mint(
    *,
    role: str = "canonical_md",
    path: str = "bundle/canonical.md",
    content: bytes = b"# canonical\n",
    event_id: str = "evt-canonical-001",
    task_id: str = _TASK,
    repo_commit: str = _COMMIT,
    observed_at: str = "2026-08-05T21:59:00Z",
) -> dict:
    wrapper = TrustedToolReadWrapper()
    return wrapper.observe_artifact_access(
        task_id=task_id,
        repo_commit=repo_commit,
        artifact_role=role,
        path=path,
        content=content,
        access_event_id=event_id,
        observed_at=observed_at,
    )


def _states(evidence: dict) -> dict[str, str]:
    return {item["artifact_role"]: item["state"] for item in evidence["comparisons"]}


def _reasons(evidence: dict) -> set[str]:
    return {item["reason"] for item in evidence["rejected_receipts"]}


def _codes(evidence: dict) -> set[str]:
    return {item["code"] for item in evidence["diagnostics"]}


# ── Schema ──────────────────────────────────────────────────────────────────


def test_receipt_schema_accepts_wrapper_mint():
    _require_jsonschema()
    receipt = _mint()
    jsonschema.validate(instance=receipt, schema=_load_schema(_RECEIPT_SCHEMA))


def test_evidence_schema_accepts_declared_and_observed():
    _require_jsonschema()
    receipt = _mint()
    evidence = compare_agent_consumption_evidence(
        _answer_compliance(["canonical_md"]),
        [receipt],
        task_id=_TASK,
        repo_commit=_COMMIT,
    )
    jsonschema.validate(instance=evidence, schema=_load_schema(_EVIDENCE_SCHEMA))
    assert evidence["kind"] == EVIDENCE_KIND
    assert evidence["version"] == EVIDENCE_VERSION
    assert _states(evidence)["canonical_md"] == "declared-and-observed"


def test_receipt_schema_rejects_content_field():
    _require_jsonschema()
    receipt = _mint()
    receipt["content"] = "should never be stored"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=receipt, schema=_load_schema(_RECEIPT_SCHEMA))


def test_receipt_schema_rejects_unknown_issuer_id():
    _require_jsonschema()
    receipt = _mint()
    receipt["issuer"] = {
        "kind": "trusted_wrapper",
        "id": "answer_text.self_declaration",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=receipt, schema=_load_schema(_RECEIPT_SCHEMA))


def test_receipt_schema_rejects_kind_id_mismatch_wrapper_with_gateway_id():
    _require_jsonschema()
    receipt = _mint()
    receipt["issuer"] = {
        "kind": "trusted_wrapper",
        "id": "repoground.agent_consumption.tool_gateway",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=receipt, schema=_load_schema(_RECEIPT_SCHEMA))


def test_receipt_schema_rejects_kind_id_mismatch_gateway_with_wrapper_id():
    _require_jsonschema()
    receipt = _mint()
    receipt["issuer"] = {
        "kind": "tool_gateway",
        "id": "repoground.agent_consumption.tool_read_wrapper",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=receipt, schema=_load_schema(_RECEIPT_SCHEMA))


def test_receipt_schema_accepts_tool_gateway_issuer_pair():
    _require_jsonschema()
    receipt = _mint()
    # Schema-only instance: runtime mint path uses trusted_wrapper by default.
    receipt["issuer"] = {
        "kind": "tool_gateway",
        "id": "repoground.agent_consumption.tool_gateway",
    }
    # Hashes are intentionally stale here; schema does not recompute digests.
    jsonschema.validate(instance=receipt, schema=_load_schema(_RECEIPT_SCHEMA))


# ── Determinism ─────────────────────────────────────────────────────────────


def test_binding_and_receipt_hashes_are_deterministic():
    r1 = _mint(content=b"same-bytes")
    r2 = _mint(content=b"same-bytes")
    assert r1["binding_sha256"] == r2["binding_sha256"]
    assert r1["receipt_sha256"] == r2["receipt_sha256"]
    assert r1["artifact_identity"]["sha256"] == r2["artifact_identity"]["sha256"]
    assert "content" not in r1
    assert "same-bytes" not in canonical_json(r1)
    assert r1["retention"]["content_retained"] is False


def test_binding_sha256_matches_helper():
    receipt = _mint()
    expected = compute_binding_sha256(
        task_id=receipt["task_id"],
        repo_commit=receipt["repo_commit"],
        artifact_role=receipt["artifact_role"],
        artifact_identity=receipt["artifact_identity"],
        access_event_id=receipt["access_event_id"],
        issuer=receipt["issuer"],
    )
    assert receipt["binding_sha256"] == expected
    without = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    assert receipt["receipt_sha256"] == sha256_json(without)


def test_comparison_output_is_deterministic():
    receipt = _mint()
    ac = _answer_compliance(["canonical_md", "agent_reading_pack"])
    a = compare_agent_consumption_evidence(
        ac,
        [receipt],
        task_id=_TASK,
        repo_commit=_COMMIT,
        expected_roles=["post_emit_health"],
    )
    b = compare_agent_consumption_evidence(
        ac,
        [receipt],
        task_id=_TASK,
        repo_commit=_COMMIT,
        expected_roles=["post_emit_health"],
    )
    assert canonical_json(a) == canonical_json(b)


# ── Trust / negative origin ──────────────────────────────────────────────────


def test_self_declaration_cannot_mint_observed_evidence():
    forged = {
        "kind": RECEIPT_KIND,
        "version": "1.0",
        "task_id": _TASK,
        "repo_commit": _COMMIT,
        "artifact_role": "canonical_md",
        "artifact_identity": {
            "path": "bundle/canonical.md",
            "sha256": "a" * 64,
            "bytes": 12,
        },
        "access_event_id": "evt-self-decl-001",
        "observed_at": "2026-08-05T21:59:00Z",
        "issuer": {"kind": "trusted_wrapper", "id": "answer_text.self_declaration"},
        "binding_sha256": "b" * 64,
        "receipt_sha256": "c" * 64,
        "retention": {
            "policy": "ephemeral_comparison_input",
            "content_retained": False,
            "redaction": "metadata_only",
            "deletion": "safe_at_any_time",
        },
        "does_not_establish": list(RECEIPT_DNE),
    }
    evidence = compare_agent_consumption_evidence(
        _answer_compliance(["canonical_md"]),
        [forged],
        task_id=_TASK,
        repo_commit=_COMMIT,
    )
    assert _states(evidence)["canonical_md"] == "declared-only"
    assert "untrusted_issuer" in _reasons(evidence)
    assert evidence["status"] == "fail"
    assert not evidence["accepted_receipt_refs"]


def test_answer_compliance_alone_never_produces_observed_state():
    evidence = compare_agent_consumption_evidence(
        _answer_compliance(["canonical_md"]),
        [],
        task_id=_TASK,
        repo_commit=_COMMIT,
    )
    assert _states(evidence) == {"canonical_md": "declared-only"}
    assert evidence["accepted_receipt_refs"] == []


def test_mint_rejects_content_fields():
    with pytest.raises(ToolReadReceiptError):
        mint_tool_read_receipt(
            task_id=_TASK,
            repo_commit=_COMMIT,
            artifact_role="canonical_md",
            artifact_identity={
                "path": "x.md",
                "sha256": "a" * 64,
                "bytes": 1,
                "content": "nope",
            },
            access_event_id="evt-bad-content-01",
        )


def test_mint_rejects_secret_like_path():
    jwtish = (
        "tokens/"
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    with pytest.raises(ToolReadReceiptError, match="secret-like"):
        mint_tool_read_receipt(
            task_id=_TASK,
            repo_commit=_COMMIT,
            artifact_role="canonical_md",
            artifact_identity={
                "path": jwtish,
                "sha256": "a" * 64,
                "bytes": 1,
            },
            access_event_id="evt-secret-path-01",
        )


def test_validate_rejects_tampered_binding():
    receipt = _mint()
    receipt["binding_sha256"] = "0" * 64
    with pytest.raises(ToolReadReceiptError, match="binding_sha256"):
        validate_tool_read_receipt(receipt)


# ── Comparison states ────────────────────────────────────────────────────────


def test_states_declared_only_observed_only_declared_and_observed_unavailable():
    observed = _mint(
        role="agent_reading_pack",
        path="bundle/pack.md",
        content=b"pack",
        event_id="evt-pack-001",
    )
    both = _mint(
        role="canonical_md",
        path="bundle/canonical.md",
        content=b"canon",
        event_id="evt-canon-001",
    )
    evidence = compare_agent_consumption_evidence(
        _answer_compliance(["canonical_md", "citation_map_jsonl"]),
        [observed, both],
        task_id=_TASK,
        repo_commit=_COMMIT,
        expected_roles=["post_emit_health"],
    )
    states = _states(evidence)
    assert states["canonical_md"] == "declared-and-observed"
    assert states["citation_map_jsonl"] == "declared-only"
    assert states["agent_reading_pack"] == "observed-only"
    assert states["post_emit_health"] == "unavailable"
    assert set(EVIDENCE_DNE) >= set(TRACE_DNE)
    assert "semantic_reading" in evidence["does_not_establish"]
    assert "actual_reading_proven" in evidence["does_not_establish"]


# ── Freshness / replay / mismatch ────────────────────────────────────────────


def test_stale_receipt_never_elevates():
    stale = _mint(observed_at="2026-08-05T12:00:00Z", event_id="evt-stale-001")
    evidence = compare_agent_consumption_evidence(
        _answer_compliance(["canonical_md"]),
        [stale],
        task_id=_TASK,
        repo_commit=_COMMIT,
        as_of=_AS_OF,
        max_age_seconds=60,
    )
    assert _states(evidence)["canonical_md"] == "declared-only"
    assert "stale" in _reasons(evidence)
    assert "stale" in _codes(evidence)
    assert not evidence["accepted_receipt_refs"]


def test_task_mismatch_never_elevates():
    foreign = _mint(task_id="OTHER-TASK-001", event_id="evt-task-mis-001")
    evidence = compare_agent_consumption_evidence(
        _answer_compliance(["canonical_md"]),
        [foreign],
        task_id=_TASK,
        repo_commit=_COMMIT,
    )
    assert _states(evidence)["canonical_md"] == "declared-only"
    assert "task_mismatch" in _reasons(evidence)


def test_commit_mismatch_never_elevates():
    foreign = _mint(repo_commit="a" * 40, event_id="evt-commit-mis-001")
    evidence = compare_agent_consumption_evidence(
        _answer_compliance(["canonical_md"]),
        [foreign],
        task_id=_TASK,
        repo_commit=_COMMIT,
    )
    assert _states(evidence)["canonical_md"] == "declared-only"
    assert "commit_mismatch" in _reasons(evidence)


def test_replay_never_elevates_twice():
    first = _mint(event_id="evt-replay-001", content=b"body-a")
    second = copy.deepcopy(first)
    # Same event id presented again is a replay even if the payload is identical.
    evidence = compare_agent_consumption_evidence(
        _answer_compliance(["canonical_md"]),
        [first, second],
        task_id=_TASK,
        repo_commit=_COMMIT,
    )
    assert "replay" in _reasons(evidence)
    assert len(evidence["accepted_receipt_refs"]) == 1
    assert _states(evidence)["canonical_md"] == "declared-and-observed"


def test_artifact_mismatch_with_declared_identity_never_elevates():
    receipt = _mint(content=b"actual-bytes", event_id="evt-art-mis-001")
    declared_identities = {
        "canonical_md": {
            "path": "bundle/canonical.md",
            "sha256": "f" * 64,
            "bytes": 999,
        }
    }
    evidence = compare_agent_consumption_evidence(
        _answer_compliance(["canonical_md"]),
        [receipt],
        task_id=_TASK,
        repo_commit=_COMMIT,
        declared_identities=declared_identities,
    )
    assert _states(evidence)["canonical_md"] == "declared-only"
    assert "artifact_mismatch" in _reasons(evidence)
    assert not evidence["accepted_receipt_refs"]


def test_conflicting_identities_for_same_role_remove_observation():
    a = _mint(content=b"one", event_id="evt-conflict-a")
    b = _mint(content=b"two", event_id="evt-conflict-b")
    evidence = compare_agent_consumption_evidence(
        _answer_compliance(["canonical_md"]),
        [a, b],
        task_id=_TASK,
        repo_commit=_COMMIT,
    )
    assert "artifact_mismatch" in _reasons(evidence)
    assert _states(evidence)["canonical_md"] == "declared-only"
    assert not evidence["accepted_receipt_refs"]


def test_privacy_violation_receipt_fails_closed():
    receipt = _mint(event_id="evt-privacy-001")
    poisoned = dict(receipt)
    poisoned["content"] = "raw repository text must not elevate evidence"
    evidence = compare_agent_consumption_evidence(
        _answer_compliance(["canonical_md"]),
        [poisoned],
        task_id=_TASK,
        repo_commit=_COMMIT,
    )
    assert "privacy_violation" in _reasons(evidence)
    assert _states(evidence)["canonical_md"] == "declared-only"
    assert evidence["status"] == "fail"


# ── Fail-closed comparison bindings ──────────────────────────────────────────


def _assert_no_trusted_observation(evidence: dict) -> None:
    assert evidence["accepted_receipt_refs"] == []
    assert all(item["observed"] is False for item in evidence["comparisons"])
    assert all(
        item["state"] != "declared-and-observed" for item in evidence["comparisons"]
    )
    assert evidence["status"] == "fail"
    assert "invalid_input_field" in _codes(evidence)
    if jsonschema is not None:
        jsonschema.validate(instance=evidence, schema=_load_schema(_EVIDENCE_SCHEMA))


def test_empty_task_id_never_accepts_receipts_or_observes():
    receipt = _mint(event_id="evt-empty-task-001")
    evidence = compare_agent_consumption_evidence(
        _answer_compliance(["canonical_md"]),
        [receipt],
        task_id="",
        repo_commit=_COMMIT,
    )
    _assert_no_trusted_observation(evidence)
    assert evidence["task_id"] == "unknown"
    assert _states(evidence)["canonical_md"] == "declared-only"


def test_invalid_repo_commit_never_accepts_receipts_or_observes():
    receipt = _mint(event_id="evt-bad-commit-001")
    evidence = compare_agent_consumption_evidence(
        _answer_compliance(["canonical_md"]),
        [receipt],
        task_id=_TASK,
        repo_commit="not-a-commit",
    )
    _assert_no_trusted_observation(evidence)
    # Schema placeholder only — not a trusted observation binding.
    assert evidence["repo_commit"] == "0" * 40
    assert _states(evidence)["canonical_md"] == "declared-only"


def test_invalid_explicit_as_of_never_accepts_receipts_or_observes():
    receipt = _mint(event_id="evt-bad-asof-001")
    evidence = compare_agent_consumption_evidence(
        _answer_compliance(["canonical_md"]),
        [receipt],
        task_id=_TASK,
        repo_commit=_COMMIT,
        as_of="not-a-timestamp",
        max_age_seconds=3600,
    )
    _assert_no_trusted_observation(evidence)
    assert evidence["task_id"] == _TASK
    assert evidence["repo_commit"] == _COMMIT
    assert _states(evidence)["canonical_md"] == "declared-only"


def test_invalid_max_age_seconds_never_accepts_receipts_or_observes():
    receipt = _mint(event_id="evt-bad-max-age-001")
    evidence = compare_agent_consumption_evidence(
        _answer_compliance(["canonical_md"]),
        [receipt],
        task_id=_TASK,
        repo_commit=_COMMIT,
        as_of=_AS_OF,
        max_age_seconds=-1,
    )
    _assert_no_trusted_observation(evidence)
    assert evidence["task_id"] == _TASK
    assert evidence["repo_commit"] == _COMMIT
    assert _states(evidence)["canonical_md"] == "declared-only"


# ── E2E wrapper adoption ─────────────────────────────────────────────────────


def test_e2e_trusted_wrapper_declaration_comparison_without_semantic_overclaim():
    wrapper = TrustedToolReadWrapper()
    assert wrapper.issuer_id == TRUSTED_WRAPPER_ISSUER_ID

    content_a = b"# Agent Reading Pack\nnavigation only\n"
    content_b = b"# Canonical\ntruth source\n"
    receipts = [
        wrapper.observe_artifact_access(
            task_id=_TASK,
            repo_commit=_COMMIT,
            artifact_role="agent_reading_pack",
            path="out/agent_reading_pack.md",
            content=content_a,
            access_event_id="evt-e2e-pack-001",
            observed_at="2026-08-05T21:58:30Z",
        ),
        wrapper.observe_artifact_access(
            task_id=_TASK,
            repo_commit=_COMMIT,
            artifact_role="canonical_md",
            path="out/canonical.md",
            content=content_b,
            access_event_id="evt-e2e-canon-001",
            observed_at="2026-08-05T21:58:45Z",
        ),
    ]
    # Content must not leak into receipts.
    for receipt in receipts:
        encoded = canonical_json(receipt)
        assert "navigation only" not in encoded
        assert "truth source" not in encoded
        validate_tool_read_receipt(receipt)

    ac = _answer_compliance(
        ["canonical_md", "agent_reading_pack", "citation_map_jsonl"]
    )
    evidence = compare_agent_consumption_evidence(
        ac,
        receipts,
        task_id=_TASK,
        repo_commit=_COMMIT,
        as_of=_AS_OF,
        max_age_seconds=3600,
        expected_roles=["post_emit_health"],
        declared_identities={
            "canonical_md": receipts[1]["artifact_identity"],
            "agent_reading_pack": receipts[0]["artifact_identity"],
        },
    )

    states = _states(evidence)
    assert states["canonical_md"] == "declared-and-observed"
    assert states["agent_reading_pack"] == "declared-and-observed"
    assert states["citation_map_jsonl"] == "declared-only"
    assert states["post_emit_health"] == "unavailable"
    assert len(evidence["accepted_receipt_refs"]) == 2
    assert evidence["status"] in {"pass", "warn"}

    # Explicit non-claims: observation is not semantic reading / truth.
    for boundary in (
        "semantic_reading",
        "relevance_to_answer",
        "answer_correct",
        "claims_true",
        "actual_reading_proven",
        "runtime_interception",
        "mandatory_wrapper_adoption",
    ):
        assert boundary in evidence["does_not_establish"]

    if jsonschema is not None:
        jsonschema.validate(instance=evidence, schema=_load_schema(_EVIDENCE_SCHEMA))
        for receipt in receipts:
            jsonschema.validate(instance=receipt, schema=_load_schema(_RECEIPT_SCHEMA))


def test_trace_does_not_establish_boundaries_remain_subset():
    assert set(TRACE_DNE).issubset(set(EVIDENCE_DNE))
    assert list(TRACE_DNE) == [
        "actual_reading_proven",
        "answer_correct",
        "repo_understood",
        "all_relevant_context_used",
        "claims_true",
        "test_sufficiency",
        "regression_absence",
        "runtime_behavior",
        "forensic_ready",
    ]
