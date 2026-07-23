"""Guard against retired product names re-entering active retrieval docs.

``docs/retrieval/`` is not a historical-evidence path under
``docs/contracts/repoground-naming-hard-cut.v1.json``
(``historical_evidence.allowed_path_prefixes``), so prose describing the
retrieval CLI/system here must track the current RepoGround surface.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RETIRED_PRODUCT_TERMS = ("lenskit", "repobrief", "repolens", "rlens")
ACTIVE_RETRIEVAL_DOCS = (
    "docs/retrieval/queries.md",
    "docs/retrieval/semantic-reranking.md",
)


def test_active_retrieval_docs_do_not_describe_retired_products_as_current() -> None:
    offenders: list[str] = []
    for relative_path in ACTIVE_RETRIEVAL_DOCS:
        path = ROOT / relative_path
        assert path.is_file(), f"{relative_path} is missing"
        lowered = path.read_text(encoding="utf-8").casefold()
        for term in RETIRED_PRODUCT_TERMS:
            if term in lowered:
                offenders.append(f"{relative_path} contains {term!r}")

    assert offenders == [], "retired product name found in active retrieval docs: " + "; ".join(
        offenders
    )
