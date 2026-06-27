import re
from pathlib import Path

from merger.lenskit.core.lenses import LENS_IDS


REPO_ROOT = Path(__file__).resolve().parents[3]
DOC = REPO_ROOT / "docs/architecture/deterministic-lenskit-core.md"


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_deterministic_core_doc_keeps_primary_lens_ids_exact() -> None:
    text = _text()
    section = text.split("## Stable Primary Lens layer", 1)[1].split(
        "## Additive lens layers", 1
    )[0]
    documented = re.findall(r"^- `([a-z_]+)`$", section, flags=re.MULTILINE)

    assert tuple(documented) == tuple(LENS_IDS)


def test_deterministic_core_doc_preserves_authority_and_live_state_boundaries() -> None:
    text = _text()

    assert "`canonical_md` is the sole content authority" in text
    assert "A dump is a snapshot at generation time" in text
    assert "Agent Reading Packs are entry and navigation surfaces, not truth" in text
    assert "Health and surface reports describe performed checks" in text


def test_deterministic_core_doc_names_additive_layers_and_core_exclusions() -> None:
    text = _text()

    for term in ("Facet", "Relation", "State", "Task Context", "Lens Card", "Relation Card"):
        assert f"**{term}:**" in text

    for exclusion in (
        "LLM inference",
        "embeddings",
        "semantic reranking",
        "autonomous review findings",
        "patch generation",
        "automatic commits",
    ):
        assert exclusion in text


def test_deterministic_core_doc_carries_negative_semantics_and_change_gates() -> None:
    text = _text()

    for boundary in (
        "truth",
        "correctness",
        "completeness",
        "runtime_behavior",
        "test_sufficiency",
        "regression_absence",
        "repo_understood",
        "claims_true",
        "forensic_ready",
    ):
        assert f"`{boundary}`" in text

    for gate in (
        "Authority gate",
        "Compatibility gate",
        "Determinism gate",
        "Negative-semantics gate",
        "Measurement gate",
        "Provenance gate",
        "Scope gate",
    ):
        assert gate in text
