import pytest
from merger.lenskit.core.pr_delta_cards import produce_pr_delta_card, produce_pr_delta_cards, DOES_NOT_ESTABLISH

def _valid_delta_context():
    return {
        "source_kind": "repolens.pr_schau.delta",
        "source_version": 1,
        "repo": "myrepo",
        "generated_at": "2023-01-01T00:00:00Z"
    }

def test_produce_pr_delta_card_added():
    file_entry = {"path": "src/main.py", "status": "added"}
    card = produce_pr_delta_card(_valid_delta_context(), file_entry)
    assert card["kind"] == "lenskit.pr_delta_card"
    assert card["version"] == "1.0"
    assert card["authority"] == "diagnostic_signal"
    assert card["canonicality"] == "diagnostic"
    assert card["delta_context"]["repo"] == "myrepo"
    assert card["delta_context"]["source_kind"] == "repolens.pr_schau.delta"
    assert card["delta_context"]["source_version"] == 1
    assert card["path"] == "src/main.py"
    assert card["change_status"] == "added"
    assert list(card["does_not_establish"]) == list(DOES_NOT_ESTABLISH)
    assert "source_provenance" not in card

def test_produce_pr_delta_card_changed():
    file_entry = {"path": "src/main.py", "status": "changed"}
    card = produce_pr_delta_card(_valid_delta_context(), file_entry)
    assert card["change_status"] == "changed"

def test_produce_pr_delta_card_removed():
    file_entry = {"path": "src/main.py", "status": "removed"}
    card = produce_pr_delta_card(_valid_delta_context(), file_entry)
    assert card["change_status"] == "removed"

def test_produce_pr_delta_card_invalid_status():
    file_entry = {"path": "src/main.py", "status": "modified"}
    with pytest.raises(ValueError, match="Invalid change_status: modified"):
        produce_pr_delta_card(_valid_delta_context(), file_entry)

def test_produce_pr_delta_card_invalid_source_kind():
    ctx = _valid_delta_context()
    ctx["source_kind"] = "wrong"
    with pytest.raises(ValueError, match="Invalid source_kind"):
        produce_pr_delta_card(ctx, {"path": "src/main.py", "status": "added"})

def test_produce_pr_delta_card_invalid_source_version():
    ctx = _valid_delta_context()
    ctx["source_version"] = 2
    with pytest.raises(ValueError, match="Invalid source_version"):
        produce_pr_delta_card(ctx, {"path": "src/main.py", "status": "added"})

def test_produce_pr_delta_card_missing_repo():
    ctx = _valid_delta_context()
    ctx["repo"] = ""
    with pytest.raises(ValueError, match="repo must be a non-empty string"):
        produce_pr_delta_card(ctx, {"path": "src/main.py", "status": "added"})

def test_produce_pr_delta_card_invalid_generated_at():
    ctx = _valid_delta_context()
    ctx["generated_at"] = ""
    with pytest.raises(ValueError, match="generated_at must be a valid string"):
        produce_pr_delta_card(ctx, {"path": "src/main.py", "status": "added"})

def test_produce_pr_delta_card_invalid_path():
    with pytest.raises(ValueError, match="path must be a non-empty string"):
        produce_pr_delta_card(_valid_delta_context(), {"path": "", "status": "added"})

def test_produce_pr_delta_cards_batch_success():
    delta = {
        "kind": "repolens.pr_schau.delta",
        "version": 1,
        "repo": "myrepo",
        "generated_at": "2023-01-01T00:00:00Z",
        "summary": {"added": 1, "changed": 1, "removed": 1},
        "files": [
            {"path": "src/removed.py", "status": "removed"},
            {"path": "src/added.py", "status": "added"},
            {"path": "src/changed.py", "status": "changed"},
        ]
    }
    cards = produce_pr_delta_cards(delta)
    
    assert len(cards) == 3
    # Sorted deterministically by canonical path
    assert cards[0]["path"] == "src/added.py"
    assert cards[1]["path"] == "src/changed.py"
    assert cards[2]["path"] == "src/removed.py"

def test_produce_pr_delta_cards_empty():
    delta = {
        "kind": "repolens.pr_schau.delta",
        "version": 1,
        "repo": "myrepo",
        "generated_at": "2023-01-01T00:00:00Z",
        "summary": {"added": 0, "changed": 0, "removed": 0},
        "files": []
    }
    cards = produce_pr_delta_cards(delta)
    assert cards == []

def test_produce_pr_delta_cards_summary_mismatch():
    delta = {
        "kind": "repolens.pr_schau.delta",
        "version": 1,
        "repo": "myrepo",
        "generated_at": "2023-01-01T00:00:00Z",
        "summary": {"added": 0, "changed": 0, "removed": 0},
        "files": [{"path": "src/added.py", "status": "added"}]
    }
    with pytest.raises(ValueError, match="Source summary counts do not match"):
        produce_pr_delta_cards(delta)

def test_produce_pr_delta_cards_duplicate_paths():
    delta = {
        "kind": "repolens.pr_schau.delta",
        "version": 1,
        "repo": "myrepo",
        "generated_at": "2023-01-01T00:00:00Z",
        "summary": {"added": 2, "changed": 0, "removed": 0},
        "files": [
            {"path": "src/added.py", "status": "added"},
            {"path": "src/added.py", "status": "added"}
        ]
    }
    with pytest.raises(ValueError, match="Duplicate path in delta"):
        produce_pr_delta_cards(delta)

def test_produce_pr_delta_cards_deterministic():
    delta = {
        "kind": "repolens.pr_schau.delta",
        "version": 1,
        "repo": "myrepo",
        "generated_at": "2023-01-01T00:00:00Z",
        "summary": {"added": 1, "changed": 1, "removed": 0},
        "files": [
            {"path": "src/b.py", "status": "added"},
            {"path": "src/a.py", "status": "changed"},
        ]
    }
    cards = produce_pr_delta_cards(delta)
    assert cards[0]["path"] == "src/a.py"
    assert cards[1]["path"] == "src/b.py"

def test_produce_pr_delta_cards_invalid_kind():
    delta = {
        "kind": "wrong",
        "version": 1,
        "repo": "myrepo",
        "generated_at": "2023-01-01T00:00:00Z",
        "summary": {"added": 0, "changed": 0, "removed": 0},
        "files": []
    }
    with pytest.raises(ValueError, match="Delta kind must be repolens.pr_schau.delta"):
        produce_pr_delta_cards(delta)
