from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_retired_side_products_are_absent_from_active_tree() -> None:
    assert not (REPO_ROOT / "merger" / "omniwandler").exists()
    assert not (REPO_ROOT / "merger" / "repomerger" / "repomerger.py").exists()


def test_product_boundary_decision_is_documented() -> None:
    decision = REPO_ROOT / "docs" / "architecture" / "product-boundaries.md"
    text = decision.read_text(encoding="utf-8")
    assert "Atlas: keep as an optional observation subsystem" in text
    assert "OmniWandler: remove from the active RepoGround repository surface" in text
    assert "Standalone Repomerger: retire rather than inherit destructive behavior" in text
