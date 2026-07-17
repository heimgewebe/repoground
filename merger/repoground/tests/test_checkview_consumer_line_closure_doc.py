from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs/proofs/checkview-consumer-line-closure-proof.md"


def test_checkview_consumer_line_closure_is_registered_and_decisive():
    text = DOC.read_text(encoding="utf-8")

    assert "TASK-CHECKVIEW-CONSUMER-LINE-CLOSURE-001" in text
    assert "Close the CheckView consumer migration line after PR #854" in text
    assert "No further automatic CheckView migration" in text


def test_checkview_consumer_line_closure_lists_migrated_paths():
    text = DOC.read_text(encoding="utf-8")

    migrated = [
        "merger/lenskit/cli/cmd_bundle_surface.py",
        "merger/lenskit/core/export_safety_report.py",
        "merger/lenskit/core/agent_reading_pack.py",
        "merger/lenskit/core/context_quality.py",
        "merger/lenskit/core/post_emit_health.py",
    ]
    for path in migrated:
        assert path in text


def test_checkview_consumer_line_closure_lists_raw_boundaries():
    text = DOC.read_text(encoding="utf-8")

    boundaries = [
        "merger/lenskit/core/parity_state.py",
        "merger/lenskit/core/merge.py",
        "merger/lenskit/core/forensic_preflight.py",
        "scripts/rlens-post-merge-surface-smoke.sh",
        "merger/lenskit/adapters/diagnostics.py",
        "merger/lenskit/cli/cmd_governance.py",
    ]
    for path in boundaries:
        assert path in text


def test_checkview_consumer_line_closure_requires_new_proof_for_future_migration():
    text = DOC.read_text(encoding="utf-8")

    assert "must open a new task/proof" in text
    assert "parity_state" in text and "exact boolean-comparison parity tests" in text
    assert "merge.py" in text and "invariant fail-filter parity tests" in text
    assert "forensic_preflight" in text and "forensic-surface adapter decision" in text
    assert "rlens-post-merge-surface-smoke.sh" in text and "script-level operational parity tests" in text
