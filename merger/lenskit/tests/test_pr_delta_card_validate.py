import pytest
import json
from pathlib import Path
from merger.lenskit.core.pr_delta_cards import produce_pr_delta_cards
from merger.lenskit.core.pr_delta_card_validate import validate_pr_delta_card

def _valid_source_delta(files=None, repo="heimgewebe/lenskit"):
    if files is None:
        files = [_changed_file("src/main.py")]
    counts = {"added": 0, "changed": 0, "removed": 0}
    for f in files:
        counts[f["status"]] += 1
    return {
        "kind": "repolens.pr_schau.delta",
        "version": 1,
        "repo": repo,
        "generated_at": "2026-06-21T10:00:00Z",
        "summary": counts,
        "files": files
    }

def _changed_file(path, size_bytes=10, sha256="0"*64, sha256_status="ok", **kwargs):
    d = {"path": path, "status": "changed", "size_bytes": size_bytes, "sha256": sha256, "sha256_status": sha256_status}
    d.update(kwargs)
    return d

class TestPRDeltaCardValidate:
    def test_valid_producer_card(self):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "pass"

    def test_invalid_change_status(self):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        card["change_status"] = "unknown"
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "fail"
        assert any(c["validation"]["reason"] == "available" and c["status"] == "fail" for c in val["checks"])

    def test_wrong_repo(self):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        card["delta_context"]["repo"] = "wrong"
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "fail"
        assert any(c["validation"]["reason"] == "producer_coherence_check" for c in val["checks"] if c["status"] == "fail")

    def test_wrong_timestamp(self):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        card["delta_context"]["generated_at"] = "2026-06-21T10:00:01Z"
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "fail"

    def test_wrong_source_kind(self):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        card["delta_context"]["source_kind"] = "wrong"
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "fail"

    def test_wrong_source_version(self):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        card["delta_context"]["source_version"] = 2
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "fail"

    def test_wrong_path(self):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        card["path"] = "other"
        # Since it won't be in the source_delta, coherence check will fail with an exception catch
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "fail"

    def test_wrong_matched_rule(self):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        card["matched_rule"] = "wrong"
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "fail"

    def test_wrong_primary_lens(self):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        card["primary_lens"] = "wrong"
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "fail"

    def test_wrong_facets(self):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        card["facets"] = ["wrong"]
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "fail"

    def test_wrong_navigation_refs(self):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        card["navigation_refs"] = []
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "fail"

    def test_wrong_negativsemantik(self):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        card["does_not_establish"] = []
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "fail"

    def test_missing_source_path(self):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        delta["files"][0]["path"] = "different"
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "fail"
        assert "not found" in str(val["checks"])

    def test_invalid_source_delta(self):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        del delta["repo"]
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "fail"
        assert "SourceValidationError" in str(val["checks"])

    def test_missing_jsonschema(self, monkeypatch):
        import sys
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        monkeypatch.setitem(sys.modules, "jsonschema", None)
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "fail"
        assert any(c["validation"]["reason"] == "dependency_unavailable" for c in val["checks"])

    def test_invalid_card_schema(self, monkeypatch):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        val = validate_pr_delta_card(card, source_delta=delta, schema={"type": "invalid"})
        assert val["status"] == "fail"
        assert any(c["validation"]["reason"] == "schema_invalid" for c in val["checks"])

    def test_controlled_producer_exception(self, monkeypatch):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        import merger.lenskit.core.pr_delta_card_validate as val_mod
        def fake_produce(*args, **kwargs):
            raise RuntimeError("Fake error")
        monkeypatch.setattr(val_mod, "produce_pr_delta_card", fake_produce)
        val = validate_pr_delta_card(card, source_delta=delta)
        assert val["status"] == "fail"
        assert "Fake error" in str(val["checks"])

    def test_deterministic_error_order(self):
        delta = _valid_source_delta()
        card = produce_pr_delta_cards(delta)[0]
        del card["kind"]
        del card["version"]
        val = validate_pr_delta_card(card, source_delta=delta)
        errors = [c.get("errors", []) for c in val["checks"] if c["name"] == "schema_validation" and c["status"] == "fail"][0]
        assert "kind" in str(errors) # Should be sorted first
