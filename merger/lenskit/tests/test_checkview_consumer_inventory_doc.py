from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs/proofs/checkview-consumer-inventory-v1.md"


def test_checkview_consumer_inventory_doc_is_registered_and_scoped():
    text = DOC.read_text(encoding="utf-8")

    assert "TASK-CHECKVIEW-CONSUMER-INVENTORY-001" in text
    assert "output_health" in text
    assert "post_emit_health" in text
    assert "bundle_surface_validation" in text
    assert "compact_check_projection(report)" in text


def test_checkview_consumer_inventory_lists_runtime_consumers():
    text = DOC.read_text(encoding="utf-8")

    required_paths = [
        "merger/lenskit/cli/cmd_bundle_surface.py",
        "merger/lenskit/core/merge.py",
        "merger/lenskit/core/post_emit_health.py",
        "merger/lenskit/core/agent_reading_pack.py",
        "merger/lenskit/core/context_quality.py",
        "merger/lenskit/core/export_safety_report.py",
        "merger/lenskit/core/parity_state.py",
        "scripts/rlens-post-merge-surface-smoke.sh",
    ]
    for path in required_paths:
        assert path in text


def test_checkview_consumer_inventory_keeps_adjacent_namespaces_out_of_scope():
    text = DOC.read_text(encoding="utf-8")

    assert "forensic_preflight" in text
    assert "lens_card_validate.py" in text
    assert "pr_delta_card_validate.py" in text
    assert "relation_card_validate.py" in text
    assert "Governance command formats a different report family" in text


def test_checkview_consumer_inventory_names_next_slice_and_non_goals():
    text = DOC.read_text(encoding="utf-8")

    assert "export_safety_report" in text
    assert "No broad adapter sweep" in text
    assert "does not prove that any migration is correct" in text
    assert "Do not start with `merge.py`, `parity_state.py`, or `rlens-post-merge-surface-smoke.sh`" in text
