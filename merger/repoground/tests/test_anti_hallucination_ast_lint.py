"""Tests for the C2.7 marker-gated AST lint, C2.8 adoption pilot, and C2.9 registry.

Covers the three AST/code-path rules (L1 forbidden semantic upgrade, L2 authority
escalation, L4 derived-artifact misuse) with synthetic source fixtures.

C2.7 baseline: produces **zero findings on the un-annotated package tree** (by-construction
guarantee that it cannot mass-false-positive or block CI).

C2.8 adoption pilot: applies markers to 3 real canonical-content sinks; the real tree
revealed 4 intentional L4 detections in merge.py (derived_projection → resolve_canonical_md),
exposing authority-upgrade sites and the need for an authority-upgrade-declaration mechanism.

C2.9 authority-upgrade registry: declares those intentional upgrades machine-readably.
Detection is unchanged (registry-blind) — the lint still fires — but a detection matching
a declared, validated upgrade is reclassified as a ``declared_upgrade`` (surfaced in the
report, NOT suppressed) and does not count as a warning. Un-declared flows still warn; a
malformed registry entry is rejected, not silently accepted.

The lint is marker-gated and opt-in: it fires only on code carrying explicit,
lint-only governance markers. It performs no type inference and is not a runtime
annotation (C4 remains open). Non-blocking; not wired into CI gates.
"""
import json
from pathlib import Path

import pytest

from merger.repoground.core.anti_hallucination_ast_lint import (
    RULES_COVERED,
    RULES_OUT_OF_SCOPE,
    AstLintReport,
    lint_default_tree,
    lint_source,
)
from merger.repoground.core.authority_upgrade_registry import (
    AUTHORITY_UPGRADE_REGISTRY,
    AuthorityUpgrade,
    classify_findings,
    match_upgrade,
    validate_registry,
)


def _rules(findings):
    return [f.rule for f in findings]


def _pilot_merge_annotation_line() -> int:
    merge_py = Path(__file__).resolve().parents[1] / "core" / "merge.py"
    for line_no, line in enumerate(merge_py.read_text().splitlines(), start=1):
        if "md_parts =" in line and "lenskit:authority=derived_projection" in line:
            return line_no
    raise AssertionError("expected md_parts pilot authority marker in core/merge.py")


# --- L1: forbidden semantic upgrade (diagnostic gate -> canonical sink) -----


def test_l1_flags_diagnostic_gate_invoking_canonical_sink():
    src = (
        "cq = compute_quality()  # lenskit:authority=diagnostic_signal\n"
        'if cq.projection_status == "complete":\n'
        "    trust_content()  # lenskit:requires-authority=canonical_content\n"
    )
    findings = lint_source(src, filename="t.py")
    l1 = [f for f in findings if f.rule == "L1"]
    assert len(l1) == 1
    assert l1[0].symbol == "cq"
    assert l1[0].severity == "warning"


def test_l1_does_not_fire_without_sink_in_body():
    src = (
        "cq = compute_quality()  # lenskit:authority=diagnostic_signal\n"
        'if cq.projection_status == "complete":\n'
        "    log(cq)\n"
    )
    assert [f for f in lint_source(src, filename="t.py") if f.rule == "L1"] == []


def test_l1_does_not_fire_when_gate_value_is_unmarked():
    src = (
        "cq = compute_quality()\n"
        'if cq.projection_status == "complete":\n'
        "    trust_content()  # lenskit:requires-authority=canonical_content\n"
    )
    assert lint_source(src, filename="t.py") == []


def test_l1_emits_one_finding_per_if_even_with_multiple_sink_calls():
    src = (
        "cq = q()  # lenskit:authority=diagnostic_signal\n"
        "if cq.ok:\n"
        "    a()  # lenskit:requires-authority=canonical_content\n"
        "    b()  # lenskit:requires-authority=canonical_content\n"
    )
    assert _rules(lint_source(src, filename="t.py")).count("L1") == 1


# --- L2: authority escalation (runtime/agent/diagnostic value -> sink) ------


def test_l2_flags_runtime_observation_passed_to_decorated_sink():
    src = (
        "@lenskit_requires_canonical\n"
        "def generate_canonical_report(x):\n"
        "    return x\n"
        "\n"
        "agent_input = load_session()  # lenskit:authority=runtime_observation\n"
        "generate_canonical_report(agent_input)\n"
    )
    findings = lint_source(src, filename="t.py")
    l2 = [f for f in findings if f.rule == "L2"]
    assert len(l2) == 1
    assert l2[0].symbol == "agent_input"


def test_l2_flags_via_call_site_requires_marker():
    src = (
        "obs = observe()  # lenskit:authority=runtime_observation\n"
        "make_report(obs)  # lenskit:requires-authority=canonical_content\n"
    )
    assert _rules(lint_source(src, filename="t.py")) == ["L2"]


def test_l2_flags_via_def_line_requires_marker():
    src = (
        "def make_report(x):  # lenskit:requires-authority=canonical_content\n"
        "    return x\n"
        "\n"
        "v = obs()  # lenskit:authority=diagnostic_signal\n"
        "make_report(v)\n"
    )
    assert _rules(lint_source(src, filename="t.py")) == ["L2"]


def test_l2_flags_keyword_argument_flow():
    src = (
        "obs = observe()  # lenskit:authority=agent_generated\n"
        "make_report(payload=obs)  # lenskit:requires-authority=canonical_content\n"
    )
    assert _rules(lint_source(src, filename="t.py")) == ["L2"]


# --- L4: derived-artifact misuse (navigation/derived value -> sink) ---------


def test_l4_flags_navigation_index_passed_to_canonical_sink():
    src = (
        "content = reading_pack_top_chunks()  # lenskit:authority=navigation_index\n"
        "verify_as_canonical(content)  # lenskit:requires-authority=canonical_content\n"
    )
    findings = lint_source(src, filename="t.py")
    l4 = [f for f in findings if f.rule == "L4"]
    assert len(l4) == 1
    assert l4[0].symbol == "content"


def test_l4_flags_derived_projection_value():
    src = (
        "proj = project()  # lenskit:authority=derived_projection\n"
        "verify_as_canonical(proj)  # lenskit:requires-authority=canonical_content\n"
    )
    assert _rules(lint_source(src, filename="t.py")) == ["L4"]


def test_l4_flags_value_from_tuple_target():
    src = (
        "a, b = produce_pair()  # lenskit:authority=navigation_index\n"
        "verify_as_canonical(b)  # lenskit:requires-authority=canonical_content\n"
    )
    findings = lint_source(src, filename="t.py")
    assert _rules(findings) == ["L4"]
    assert findings[0].symbol == "b"


# --- Class distinction & negative cases -------------------------------------


def test_diagnostic_signal_argument_is_l2_not_l4():
    # diagnostic_signal is escalation-like, not navigation-like, when used as an arg.
    src = (
        "d = diag()  # lenskit:authority=diagnostic_signal\n"
        "verify_as_canonical(d)  # lenskit:requires-authority=canonical_content\n"
    )
    assert _rules(lint_source(src, filename="t.py")) == ["L2"]


def test_canonical_source_into_canonical_sink_is_not_flagged():
    src = (
        "content = read_canonical()  # lenskit:authority=canonical_content\n"
        "verify_as_canonical(content)  # lenskit:requires-authority=canonical_content\n"
    )
    assert lint_source(src, filename="t.py") == []


def test_unmarked_identical_shape_is_not_flagged():
    src = (
        "content = reading_pack_top_chunks()\n"
        "verify_as_canonical(content)\n"
    )
    assert lint_source(src, filename="t.py") == []


def test_low_authority_value_into_undeclared_sink_is_not_flagged():
    src = (
        "content = nav()  # lenskit:authority=navigation_index\n"
        "some_plain_helper(content)\n"
    )
    assert lint_source(src, filename="t.py") == []


def test_marker_text_inside_string_literal_is_not_matched():
    # tokenize-based extraction must ignore marker text inside string literals.
    src = (
        'note = "see # lenskit:authority=navigation_index for details"\n'
        "verify_as_canonical(note)  # lenskit:requires-authority=canonical_content\n"
    )
    assert lint_source(src, filename="t.py") == []


def test_multiline_assignment_marker_binds_authority():
    src = (
        "content = (\n"
        "    reading_pack_top_chunks()\n"
        ")  # lenskit:authority=navigation_index\n"
        "verify_as_canonical(content)  # lenskit:requires-authority=canonical_content\n"
    )
    assert _rules(lint_source(src, filename="t.py")) == ["L4"]


def test_syntax_error_source_is_skipped_not_failed():
    src = "def broken(:\n  pass  # lenskit:authority=navigation_index\n"
    assert lint_source(src, filename="t.py") == []


def test_no_marker_source_returns_empty_fast_path():
    src = "def f(x):\n    return x + 1\n"
    assert lint_source(src, filename="t.py") == []


# --- Report shape -----------------------------------------------------------


def test_report_self_declares_diagnostic_authority_and_disclaimers():
    report = AstLintReport(files_scanned=3)
    report.findings.extend(
        lint_source(
            "x = obs()  # lenskit:authority=runtime_observation\n"
            "sink(x)  # lenskit:requires-authority=canonical_content\n",
            filename="t.py",
        )
    )
    d = report.to_dict()
    assert d["kind"] == "lenskit.anti_hallucination_ast_lint"
    assert d["stage"] == "C2.9"
    assert d["experimental"] is True
    assert d["blocking"] is False
    assert d["authority"] == "diagnostic_signal"
    assert d["risk_class"] == "diagnostic"
    # runtime_observation -> sink is an L2 escalation, not in the registry: stays a warning.
    assert d["status"] == "warn"
    assert d["finding_count"] == 1
    assert d["declared_upgrade_count"] == 0
    assert d["rules_covered"] == list(RULES_COVERED)
    assert set(d["rules_out_of_scope"]) == set(RULES_OUT_OF_SCOPE)
    # C4 (runtime annotation) is explicitly tracked as out of scope / open.
    assert "C4" in d["rules_out_of_scope"]
    assert any("does_not_prove_code_is_authority_safe" in m for m in d["does_not_mean"])
    # C2.9: a declared upgrade is reviewed intent, not a runtime-safety proof.
    assert any("declared_authority_upgrade_is_reviewed_intent" in m for m in d["does_not_mean"])
    # The full declared policy is always surfaced (machine-readable, not suppressed).
    assert isinstance(d["declared_upgrades"], list)
    assert isinstance(d["authority_upgrade_registry"], list)


def test_clean_report_status_is_pass():
    assert AstLintReport(files_scanned=5).status == "pass"
    assert AstLintReport(files_scanned=5).to_dict()["status"] == "pass"


# --- Integration against the real package tree ------------------------------


def test_real_tree_merge_l4_are_declared_upgrades_not_warnings():
    # C2.8 pilot revealed 4 intentional L4 detections in merge.py
    # (md_parts derived_projection → resolve_canonical_md). C2.9 declares them in
    # the authority-upgrade registry, so they are reclassified as declared upgrades:
    # they no longer count as warnings, but remain visible (not suppressed).
    #   - produce_citation_map() (citation_map.py): clean producer → 0 detections.
    #   - produce_agent_reading_pack() (agent_reading_pack.py): indirect
    #     health→PackModel flow undetected → 0 detections.
    report = lint_default_tree()
    assert report.files_skipped == 0
    assert report.files_scanned >= 20

    # Stop-criterion: the known merge.py L4 cases are no longer warn-findings.
    assert report.findings == [], (
        f"Expected zero real warnings, got: {[f.to_dict() for f in report.findings]}"
    )
    assert report.status == "pass"

    # ...but they are surfaced, machine-readable, as declared authority upgrades.
    assert report.declared_upgrade_count == 4
    annotation_line = _pilot_merge_annotation_line()
    for d in report.declared_upgrades:
        f = d.finding
        assert f.rule == "L4"
        assert f.file.endswith("merge.py")
        assert f.symbol == "md_parts"
        assert f.sink == "resolve_canonical_md"
        assert f.line > annotation_line
        assert d.declaration.source_authority == "derived_projection"
        assert d.declaration.target_authority == "canonical_content"
        assert d.declaration.reason  # auditable rationale present

    # The four declared upgrades are exactly the known call sites and remain
    # after the pilot marker annotation.
    lines = sorted(d.finding.line for d in report.declared_upgrades)
    assert len(lines) == 4
    assert all(line > annotation_line for line in lines)


# --- CLI smoke --------------------------------------------------------------


def test_cli_governance_ast_lint_exits_zero_when_only_declared_upgrades():
    # C2.9: the 4 merge.py L4 detections are declared upgrades, not warnings →
    # status pass → exit 0. The lint is non-blocking and not wired into any CI gate.
    from merger.repoground.cli.main import main

    assert main(["governance", "ast-lint"]) == 0


def test_cli_governance_ast_lint_json_contains_declared_upgrades(capsys):
    from merger.repoground.cli.main import main

    rc = main(["governance", "ast-lint", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"
    assert payload["stage"] == "C2.9"
    assert payload["experimental"] is True
    assert payload["blocking"] is False
    assert payload["authority"] == "diagnostic_signal"
    # The known merge.py L4 cases no longer count as warn-findings...
    assert payload["finding_count"] == 0
    # ...but appear, machine-readable, as declared authority upgrades.
    assert payload["declared_upgrade_count"] == 4
    assert len(payload["declared_upgrades"]) == 4
    upgrade = payload["declared_upgrades"][0]
    assert upgrade["status"] == "declared_upgrade"
    assert upgrade["sink"] == "resolve_canonical_md"
    assert upgrade["source_authority"] == "derived_projection"
    assert upgrade["target_authority"] == "canonical_content"
    assert upgrade["reason"]
    # The full declared policy is always emitted (transparent, not suppressed).
    assert any(
        e["sink"] == "resolve_canonical_md"
        for e in payload["authority_upgrade_registry"]
    )
    assert payload["rules_covered"] == list(RULES_COVERED)


def test_cli_governance_ast_lint_rejects_nonexistent_path(capsys, tmp_path):
    from merger.repoground.cli.main import main

    missing = tmp_path / "does-not-exist"
    rc = main(["governance", "ast-lint", "--path", str(missing)])
    assert rc == 2
    assert "does not exist" in capsys.readouterr().err


# --- C2.9: authority-upgrade registry ---------------------------------------


def _valid_upgrade(**overrides) -> AuthorityUpgrade:
    base = dict(
        rule="L4",
        source_authority="derived_projection",
        target_authority="canonical_content",
        sink="resolve_canonical_md",
        file_suffix="t.py",
        reason="declared canonical-selection upgrade for the registry tests",
    )
    base.update(overrides)
    return AuthorityUpgrade(**base)


def test_declared_upgrade_is_detected_then_allowed_not_suppressed():
    # Mirrors the real merge.py pattern. The detector must STILL fire (registry is
    # not a way to switch the smoke detector off): a raw L4 finding is produced...
    src = (
        "md_parts = collect()  # lenskit:authority=derived_projection\n"
        "resolve_canonical_md(md_parts)  # lenskit:requires-authority=canonical_content\n"
    )
    findings = lint_source(src, filename="merger/repoground/core/merge.py")
    assert _rules(findings) == ["L4"]
    assert findings[0].sink == "resolve_canonical_md"
    assert findings[0].authority == "derived_projection"

    # ...but through a report the declared upgrade is partitioned out of warnings
    # and surfaced as a declared_upgrade (visible, not silently swallowed).
    report = AstLintReport(files_scanned=1)
    report.add_findings(findings)
    assert report.findings == []
    assert report.status == "pass"
    assert report.declared_upgrade_count == 1
    d = report.declared_upgrades[0].to_dict()
    assert d["status"] == "declared_upgrade"
    assert d["rule"] == "L4"
    assert d["sink"] == "resolve_canonical_md"
    assert d["source_authority"] == "derived_projection"
    assert d["target_authority"] == "canonical_content"
    assert d["reason"]


def test_unregistered_derived_projection_into_canonical_sink_stays_l4():
    # Same authority class, DIFFERENT sink (not declared) → still a real warning.
    src = (
        "proj = project()  # lenskit:authority=derived_projection\n"
        "verify_as_canonical(proj)  # lenskit:requires-authority=canonical_content\n"
    )
    report = AstLintReport(files_scanned=1)
    report.add_findings(lint_source(src, filename="t.py"))
    assert _rules(report.findings) == ["L4"]
    assert report.declared_upgrades == []
    assert report.status == "warn"


def test_l2_escalation_into_same_sink_is_not_matched_by_l4_declaration():
    # The declaration is (rule=L4, source=derived_projection). An L2 escalation
    # (runtime_observation) into the SAME sink name must not be reclassified.
    src = (
        "obs = observe()  # lenskit:authority=runtime_observation\n"
        "resolve_canonical_md(obs)  # lenskit:requires-authority=canonical_content\n"
    )
    report = AstLintReport(files_scanned=1)
    report.add_findings(lint_source(src, filename="t.py"))
    assert _rules(report.findings) == ["L2"]
    assert report.declared_upgrades == []
    assert report.status == "warn"


def test_shipped_registry_is_valid_and_declares_the_merge_upgrade():
    assert validate_registry(AUTHORITY_UPGRADE_REGISTRY) == []
    assert any(
        e.rule == "L4"
        and e.source_authority == "derived_projection"
        and e.target_authority == "canonical_content"
        and e.sink == "resolve_canonical_md"
        and e.file_suffix == "merger/repoground/core/merge.py"
        for e in AUTHORITY_UPGRADE_REGISTRY
    )


def test_symbol_narrowing_scopes_a_declaration():
    src = (
        "md_parts = collect()  # lenskit:authority=derived_projection\n"
        "resolve_canonical_md(md_parts)  # lenskit:requires-authority=canonical_content\n"
    )
    findings = lint_source(src, filename="t.py")

    # Pinned to a different symbol → no match → stays a warning.
    pinned_other = (_valid_upgrade(symbol="other_var"),)
    real, declared = classify_findings(findings, registry=pinned_other)
    assert _rules(real) == ["L4"]
    assert declared == []

    # Pinned to the matching symbol → declared upgrade.
    pinned_match = (_valid_upgrade(symbol="md_parts"),)
    real2, declared2 = classify_findings(findings, registry=pinned_match)
    assert real2 == []
    assert len(declared2) == 1
    assert declared2[0].declaration.symbol == "md_parts"


def test_match_upgrade_returns_none_for_unrelated_finding():
    src = (
        "content = nav()  # lenskit:authority=navigation_index\n"
        "verify_as_canonical(content)  # lenskit:requires-authority=canonical_content\n"
    )
    (finding,) = lint_source(src, filename="t.py")
    # navigation_index → verify_as_canonical is a real L4, not the declared upgrade.
    assert match_upgrade(finding) is None


def test_same_sink_outside_merge_file_is_not_declared_upgrade():
    src = (
        "md_parts = collect()  # lenskit:authority=derived_projection\n"
        "resolve_canonical_md(md_parts)  # lenskit:requires-authority=canonical_content\n"
    )
    report = AstLintReport(files_scanned=1)
    report.add_findings(lint_source(src, filename="some/other.py"))
    assert _rules(report.findings) == ["L4"]
    assert report.declared_upgrades == []
    assert report.status == "warn"


@pytest.mark.parametrize(
    "overrides, expect_problem",
    [
        ({"reason": ""}, "reason"),
        ({"reason": "ok"}, "reason"),
        ({"rule": "L9"}, "rule"),
        ({"source_authority": "diagnostic_signal"}, "L4"),  # cannot produce L4
        ({"target_authority": "navigation_index"}, "target_authority"),
        ({"sink": "   "}, "sink"),
        ({"file_suffix": "   "}, "file_suffix"),
        ({"symbol": "  "}, "symbol"),
    ],
)
def test_invalid_registry_entry_is_rejected_not_silently_accepted(overrides, expect_problem):
    bad = _valid_upgrade(**overrides)
    problems = bad.validation_errors()
    assert problems, f"expected {overrides} to be rejected"
    assert any(expect_problem in p for p in problems)

    # And the malformed entry must surface loudly, not be quietly ignored.
    errors = validate_registry([bad])
    assert errors
    with pytest.raises(ValueError):
        classify_findings([], registry=[bad])
    with pytest.raises(ValueError):
        match_upgrade(
            lint_source(
                "md_parts = c()  # lenskit:authority=derived_projection\n"
                "resolve_canonical_md(md_parts)  # lenskit:requires-authority=canonical_content\n",
                filename="t.py",
            )[0],
            registry=[bad],
        )


def test_valid_custom_registry_entry_passes_validation():
    assert _valid_upgrade().validation_errors() == []
    assert validate_registry([_valid_upgrade()]) == []


def test_validate_registry_rejects_non_authority_upgrade_entry_type():
    errors = validate_registry([{}])  # type: ignore[list-item]
    assert errors
    assert any("entry must be an AuthorityUpgrade" in e for e in errors)

    with pytest.raises(ValueError):
        classify_findings([], registry=[{}])  # type: ignore[list-item]
