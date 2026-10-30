"""Regression for canonical and historical repository merge order (#1330)."""

from merger.repoground.core.merge import REPO_ORDER, get_repo_sort_index


def test_commonthing_is_canonical_explicit_merge_order() -> None:
    assert "commonthing" in REPO_ORDER
    assert get_repo_sort_index("commonthing") == REPO_ORDER.index("commonthing")
    assert get_repo_sort_index("commonthing") < get_repo_sort_index("weltgewebe")
    assert get_repo_sort_index("commonthing") < get_repo_sort_index("vault-gewebe")


def test_legacy_weltgewebe_order_and_unknown_fallback_remain() -> None:
    assert "weltgewebe" in REPO_ORDER
    assert get_repo_sort_index("weltgewebe") == REPO_ORDER.index("weltgewebe")
    assert get_repo_sort_index("weltgewebe") < get_repo_sort_index("vault-gewebe")
    assert get_repo_sort_index("some-future-repo") == 999
