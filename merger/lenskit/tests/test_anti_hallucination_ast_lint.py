"""Tests for the C2.7 experimental marker-gated anti-hallucination AST lint and C2.8 adoption pilot.

Covers the three AST/code-path rules (L1 forbidden semantic upgrade, L2 authority
escalation, L4 derived-artifact misuse) with synthetic source fixtures.

C2.7 baseline: produces **zero findings on the un-annotated package tree** (by-construction
guarantee that it cannot mass-false-positive or block CI).

C2.8 adoption pilot: applies markers to 3 real canonical-content sinks; the real tree now
yields 4 intentional L4 findings in merge.py (derived_projection → resolve_canonical_md),
revealing authority-upgrade sites and the need for an authority-upgrade-declaration mechanism.

The lint is marker-gated and opt-in: it fires only on code carrying explicit,
lint-only governance markers. It performs no type inference and is not a runtime
annotation (C4 remains open). Non-blocking; not wired into CI gates.
"""
import json
from pathlib import Path

from merger.lenskit.core.anti_hallucination_ast_lint import (
    RULES_COVERED,
    RULES_OUT_OF_SCOPE,
    AstLintReport,
    lint_default_tree,
    lint_source,
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
    assert d["stage"] == "C2.7"
    assert d["experimental"] is True
    assert d["blocking"] is False
    assert d["authority"] == "diagnostic_signal"
    assert d["risk_class"] == "diagnostic"
    assert d["status"] == "warn"
    assert d["rules_covered"] == list(RULES_COVERED)
    assert set(d["rules_out_of_scope"]) == set(RULES_OUT_OF_SCOPE)
    # C4 (runtime annotation) is explicitly tracked as out of scope / open.
    assert "C4" in d["rules_out_of_scope"]
    assert any("does_not_prove_code_is_authority_safe" in m for m in d["does_not_mean"])


def test_clean_report_status_is_pass():
    assert AstLintReport(files_scanned=5).status == "pass"
    assert AstLintReport(files_scanned=5).to_dict()["status"] == "pass"


# --- Integration against the real package tree ------------------------------


def test_real_tree_c2_8_pilot_findings_match_expected():
    # C2.8 adoption pilot: three canonical sinks annotated in the real tree.
    # - resolve_canonical_md() in merge.py: marked as canonical sink; md_parts
    #   annotated as derived_projection at one call site → 4 expected L4 findings
    #   (file-scoped over-approximation propagates the authority to all resolve_canonical_md(md_parts)
    #   calls in the file).
    # - produce_citation_map() in citation_map.py: marked as canonical sink, no
    #   low-authority variables in scope → 0 findings (clean producer).
    # - produce_agent_reading_pack() in agent_reading_pack.py: marked as canonical
    #   sink; health annotated as diagnostic_signal but flows via PackModel
    #   intermediary → 0 findings (reveals indirect-flow gap in file-scoped engine).
    report = lint_default_tree()
    assert report.files_skipped == 0
    assert report.files_scanned >= 20

    l4_merge = [
        f for f in report.findings
        if f.rule == "L4" and f.file.endswith("merge.py")
    ]
    unexpected = [
        f for f in report.findings
        if not (f.rule == "L4" and f.file.endswith("merge.py"))
    ]
    assert unexpected == [], f"Unexpected findings outside merge.py L4: {[f.to_dict() for f in unexpected]}"
    # All L4 findings are md_parts → resolve_canonical_md (intentional boundary crossing).
    assert len(l4_merge) == 4
    assert all(f.symbol == "md_parts" for f in l4_merge)
    assert all(f.line > _pilot_merge_annotation_line() for f in l4_merge)
    assert all("resolve_canonical_md" in f.message for f in l4_merge)


# --- CLI smoke --------------------------------------------------------------


def test_cli_governance_ast_lint_exits_one_for_c2_8_findings():
    # C2.8 pilot annotations produce findings → exit 1 (warn). The lint is still
    # non-blocking (blocking: false) and not wired into any CI gate.
    from merger.lenskit.cli.main import main

    assert main(["governance", "ast-lint"]) == 1


def test_cli_governance_ast_lint_json_is_valid(capsys):
    from merger.lenskit.cli.main import main

    rc = main(["governance", "ast-lint", "--json"])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "warn"
    assert payload["experimental"] is True
    assert payload["blocking"] is False
    assert payload["authority"] == "diagnostic_signal"
    assert payload["finding_count"] == 4
    assert payload["rules_covered"] == list(RULES_COVERED)


def test_cli_governance_ast_lint_rejects_nonexistent_path(capsys, tmp_path):
    from merger.lenskit.cli.main import main

    missing = tmp_path / "does-not-exist"
    rc = main(["governance", "ast-lint", "--path", str(missing)])
    assert rc == 2
    assert "does not exist" in capsys.readouterr().err
