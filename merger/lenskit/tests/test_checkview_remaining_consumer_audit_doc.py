from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs/proofs/checkview-remaining-consumer-audit-v1.md"


def test_remaining_consumer_audit_is_registered_and_currently_scoped():
    text = DOC.read_text(encoding="utf-8")

    assert "TASK-CHECKVIEW-REMAINING-CONSUMER-AUDIT-001" in text
    assert "PRs #847, #849, #850, and #852" in text
    assert "after PR #851" in text
    assert "Same field name does not mean same contract" in text


def test_remaining_consumer_audit_lists_migrated_consumers():
    text = DOC.read_text(encoding="utf-8")

    migrated = [
        "merger/lenskit/cli/cmd_bundle_surface.py",
        "merger/lenskit/core/export_safety_report.py",
        "merger/lenskit/core/agent_reading_pack.py",
        "merger/lenskit/core/context_quality.py",
    ]
    for path in migrated:
        assert path in text


def test_remaining_consumer_audit_lists_deferred_runtime_readers():
    text = DOC.read_text(encoding="utf-8")

    remaining = [
        "merger/lenskit/core/post_emit_health.py",
        "merger/lenskit/core/parity_state.py",
        "scripts/rlens-post-merge-surface-smoke.sh",
        "merger/lenskit/core/merge.py",
        "merger/lenskit/core/forensic_preflight.py",
    ]
    for path in remaining:
        assert path in text


def test_remaining_consumer_audit_names_next_slice_and_boundaries():
    text = DOC.read_text(encoding="utf-8")

    assert "post_emit_health" in text
    assert "Do not start with `parity_state`" in text
    assert "Keep `parity_state`, `merge.py`, forensic preflight, and smoke scripts out" in text
    assert "does not prove any future migration correct" in text
