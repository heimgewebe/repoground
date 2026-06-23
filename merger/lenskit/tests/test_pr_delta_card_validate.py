from merger.lenskit.core.pr_delta_cards import produce_pr_delta_card
from merger.lenskit.core.pr_delta_card_validate import validate_pr_delta_card

def _valid_delta_context():
    return {
        "source_kind": "repolens.pr_schau.delta",
        "source_version": 1,
        "repo": "myrepo",
        "generated_at": "2023-01-01T00:00:00Z"
    }

def _valid_file_entry():
    return {"path": "src/main.py", "status": "added"}

def test_validate_pr_delta_card_success():
    ctx = _valid_delta_context()
    entry = _valid_file_entry()
    card = produce_pr_delta_card(ctx, entry)
    result = validate_pr_delta_card(card, delta_context=ctx, file_entry=entry)
    assert result["status"] == "pass"
    assert any(c["name"] == "schema_validation" and c["status"] == "pass" for c in result["checks"])
    assert any(c["name"] == "source_producer_coherence" and c["status"] == "pass" for c in result["checks"])

def test_validate_pr_delta_card_invalid_schema():
    ctx = _valid_delta_context()
    entry = _valid_file_entry()
    card = produce_pr_delta_card(ctx, entry)
    card["extra_field"] = "not_allowed"
    result = validate_pr_delta_card(card, delta_context=ctx, file_entry=entry)
    assert result["status"] == "fail"
    assert any(c["name"] == "schema_validation" and c["status"] == "fail" for c in result["checks"])

def test_validate_pr_delta_card_wrong_status():
    ctx = _valid_delta_context()
    entry = _valid_file_entry()
    card = produce_pr_delta_card(ctx, entry)
    card["change_status"] = "removed"  # Allowed by schema but violates producer source evidence
    result = validate_pr_delta_card(card, delta_context=ctx, file_entry=entry)
    assert result["status"] == "fail"
    assert any(c["name"] == "source_producer_coherence" and c["status"] == "fail" for c in result["checks"])

def test_validate_pr_delta_card_wrong_lens_projection():
    ctx = _valid_delta_context()
    entry = _valid_file_entry()
    card = produce_pr_delta_card(ctx, entry)
    card["primary_lens"] = "invalid_lens" # Violates schema
    result = validate_pr_delta_card(card, delta_context=ctx, file_entry=entry)
    assert result["status"] == "fail"
    assert any(c["name"] == "schema_validation" and c["status"] == "fail" for c in result["checks"])

def test_validate_pr_delta_card_wrong_path_coherence():
    ctx = _valid_delta_context()
    entry = _valid_file_entry()
    card = produce_pr_delta_card(ctx, entry)
    card["path"] = "src/other.py" # Allowed by schema, violates producer
    result = validate_pr_delta_card(card, delta_context=ctx, file_entry=entry)
    assert result["status"] == "fail"
    assert any(c["name"] == "source_producer_coherence" and c["status"] == "fail" for c in result["checks"])

def test_validate_pr_delta_card_missing_negative_semantics():
    ctx = _valid_delta_context()
    entry = _valid_file_entry()
    card = produce_pr_delta_card(ctx, entry)
    card["does_not_establish"].pop()
    result = validate_pr_delta_card(card, delta_context=ctx, file_entry=entry)
    assert result["status"] == "fail"
    assert any(c["name"] == "schema_validation" and c["status"] == "fail" for c in result["checks"])

def test_validate_pr_delta_card_wrong_repo():
    ctx = _valid_delta_context()
    entry = _valid_file_entry()
    card = produce_pr_delta_card(ctx, entry)
    card["delta_context"]["repo"] = "otherrepo"
    result = validate_pr_delta_card(card, delta_context=ctx, file_entry=entry)
    assert result["status"] == "fail"
    assert any(c["name"] == "source_producer_coherence" and c["status"] == "fail" for c in result["checks"])

def test_validate_pr_delta_card_wrong_generated_at():
    ctx = _valid_delta_context()
    entry = _valid_file_entry()
    card = produce_pr_delta_card(ctx, entry)
    card["delta_context"]["generated_at"] = "2023-12-31T23:59:59Z"
    result = validate_pr_delta_card(card, delta_context=ctx, file_entry=entry)
    assert result["status"] == "fail"
    assert any(c["name"] == "source_producer_coherence" and c["status"] == "fail" for c in result["checks"])

def test_validate_pr_delta_card_wrong_source_version():
    ctx = _valid_delta_context()
    entry = _valid_file_entry()
    card = produce_pr_delta_card(ctx, entry)
    card["delta_context"]["source_version"] = 2
    result = validate_pr_delta_card(card, delta_context=ctx, file_entry=entry)
    assert result["status"] == "fail"
    assert any(c["name"] == "schema_validation" and c["status"] == "fail" for c in result["checks"])

def test_validate_pr_delta_card_wrong_source_kind():
    ctx = _valid_delta_context()
    entry = _valid_file_entry()
    card = produce_pr_delta_card(ctx, entry)
    card["delta_context"]["source_kind"] = "wrong"
    result = validate_pr_delta_card(card, delta_context=ctx, file_entry=entry)
    assert result["status"] == "fail"
    assert any(c["name"] == "schema_validation" and c["status"] == "fail" for c in result["checks"])

def test_validate_pr_delta_card_missing_jsonschema(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    ctx = _valid_delta_context()
    entry = _valid_file_entry()
    card = produce_pr_delta_card(ctx, entry)
    result = validate_pr_delta_card(card, delta_context=ctx, file_entry=entry)
    assert result["status"] == "fail"
    assert any(c["name"] == "schema_validation" and c["status"] == "fail" and c["validation"]["reason"] == "dependency_unavailable" for c in result["checks"])
