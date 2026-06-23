import pytest
from merger.lenskit.core.pr_delta_cards import (
    produce_pr_delta_cards,
    produce_pr_delta_card,
    SourceValidationError,
)

def _valid_source_delta(files=None, repo="heimgewebe/lenskit"):
    if files is None:
        files = [_changed_file("src/main.py")]
    
    counts = {"added": 0, "changed": 0, "removed": 0}
    for f in files:
        if f["status"] in counts:
            counts[f["status"]] += 1
        
    return {
        "kind": "repolens.pr_schau.delta",
        "version": 1,
        "repo": repo,
        "generated_at": "2026-06-21T10:00:00Z",
        "summary": counts,
        "files": files
    }

def _added_file(path, size_bytes=10, sha256="0"*64, sha256_status="ok", **kwargs):
    d = {"path": path, "status": "added", "size_bytes": size_bytes, "sha256": sha256, "sha256_status": sha256_status}
    d.update(kwargs)
    return d

def _changed_file(path, size_bytes=10, sha256="0"*64, sha256_status="ok", **kwargs):
    d = {"path": path, "status": "changed", "size_bytes": size_bytes, "sha256": sha256, "sha256_status": sha256_status}
    d.update(kwargs)
    return d

def _removed_file(path, **kwargs):
    d = {"path": path, "status": "removed", "size_bytes": 0, "sha256": None, "sha256_status": "skipped"}
    d.update(kwargs)
    return d

class TestSourceContractValidation:
    def test_valid_delta(self):
        delta = _valid_source_delta([
            _added_file("a"),
            _changed_file("b"),
            _removed_file("c")
        ])
        cards = produce_pr_delta_cards(delta)
        assert len(cards) == 3
        
    def test_missing_root_field(self):
        delta = _valid_source_delta()
        del delta["repo"]
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_additional_root_field(self):
        delta = _valid_source_delta()
        delta["extra"] = "value"
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_missing_file_field(self):
        f = _changed_file("a")
        del f["size_bytes"]
        delta = _valid_source_delta([f])
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_additional_file_field(self):
        f = _changed_file("a", extra="value")
        delta = _valid_source_delta([f])
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_invalid_status(self):
        f = _changed_file("a")
        f["status"] = "unknown"
        delta = _valid_source_delta([f])
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_negative_size(self):
        delta = _valid_source_delta([_changed_file("a", size_bytes=-1)])
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_invalid_sha(self):
        delta = _valid_source_delta([_changed_file("a", sha256="short")])
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_ok_with_null_sha(self):
        delta = _valid_source_delta([_changed_file("a", sha256=None)])
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_not_ok_with_sha(self):
        delta = _valid_source_delta([_changed_file("a", sha256_status="missing")])
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_removed_not_skipped(self):
        f = _removed_file("a")
        f["sha256_status"] = "ok"
        f["sha256"] = "0"*64
        delta = _valid_source_delta([f])
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_added_skipped(self):
        f = _added_file("a")
        f["sha256_status"] = "skipped"
        f["sha256"] = None
        delta = _valid_source_delta([f])
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_invalid_date(self):
        delta = _valid_source_delta()
        delta["generated_at"] = "invalid"
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_date_without_timezone(self):
        delta = _valid_source_delta()
        delta["generated_at"] = "2026-06-21T10:00:00"
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_boolean_summary(self):
        delta = _valid_source_delta([_added_file("a")])
        delta["summary"]["added"] = True
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_float_summary(self):
        delta = _valid_source_delta([_added_file("a")])
        delta["summary"]["added"] = 1.0
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_negative_summary(self):
        delta = _valid_source_delta()
        delta["summary"]["removed"] = -1
        with pytest.raises(SourceValidationError):
            produce_pr_delta_cards(delta)
            
    def test_missing_jsonschema(self, monkeypatch):
        import sys
        monkeypatch.setitem(sys.modules, "jsonschema", None)
        with pytest.raises(SourceValidationError, match="jsonschema library is required"):
            produce_pr_delta_cards(_valid_source_delta())
            
    def test_deterministic_error_order(self):
        delta = _valid_source_delta()
        del delta["kind"]
        del delta["version"]
        try:
            produce_pr_delta_cards(delta)
        except SourceValidationError as e:
            # kind should be evaluated first since 'k' comes before 'v'
            assert "kind" in str(e)

class TestBatchProduction:
    def test_all_statuses(self):
        cards = produce_pr_delta_cards(_valid_source_delta([
            _added_file("a"), _changed_file("b"), _removed_file("c")
        ]))
        assert len(cards) == 3
        
    def test_empty_delta(self):
        assert produce_pr_delta_cards(_valid_source_delta([])) == []
        
    def test_unsorted_source(self):
        cards = produce_pr_delta_cards(_valid_source_delta([
            _changed_file("z"), _changed_file("a")
        ]))
        assert cards[0]["path"] == "a"
        assert cards[1]["path"] == "z"
        
    def test_summary_mismatch(self):
        delta = _valid_source_delta([_added_file("a")])
        delta["summary"]["added"] = 2
        with pytest.raises(SourceValidationError, match="counts do not match"):
            produce_pr_delta_cards(delta)
            
    def test_duplicate_paths(self):
        delta = _valid_source_delta([_added_file("a"), _changed_file("a")])
        # Summary counts must match to avoid false failures
        delta["summary"] = {"added": 1, "changed": 1, "removed": 0}
        with pytest.raises(SourceValidationError, match="Duplicate path"):
            produce_pr_delta_cards(delta)
            
    def test_input_not_mutated(self):
        delta = _valid_source_delta()
        import copy
        orig = copy.deepcopy(delta)
        produce_pr_delta_cards(delta)
        assert delta == orig
        
    def test_empty_repo(self):
        delta = _valid_source_delta(repo="")
        cards = produce_pr_delta_cards(delta)
        assert cards[0]["delta_context"]["repo"] == ""
        
    def test_no_hash_fields(self):
        cards = produce_pr_delta_cards(_valid_source_delta([_changed_file("a", sha256="1"*64)]))
        assert "sha256" not in cards[0]
        assert "sha256" not in str(cards[0])

class TestSingleProduction:
    def test_existing_path(self):
        delta = _valid_source_delta([_added_file("a"), _changed_file("b")])
        card = produce_pr_delta_card(delta, "a")
        assert card["path"] == "a"
        
    def test_missing_path(self):
        delta = _valid_source_delta([_added_file("a")])
        with pytest.raises(ValueError, match="not found"):
            produce_pr_delta_card(delta, "b")
            
    def test_duplicate_path(self):
        delta = _valid_source_delta([_added_file("a"), _changed_file("a")])
        delta["summary"] = {"added": 1, "changed": 1, "removed": 0}
        # Actually fails during validation first
        with pytest.raises(SourceValidationError, match="Duplicate path"):
            produce_pr_delta_card(delta, "a")
            
    def test_removed_path(self):
        delta = _valid_source_delta([_removed_file("a")])
        card = produce_pr_delta_card(delta, "a")
        assert card["change_status"] == "removed"
        
    def test_facet_free(self):
        delta = _valid_source_delta([_changed_file("src/main.py")])
        card = produce_pr_delta_card(delta, "src/main.py")
        assert "core" in card["primary_lens"]
        
    def test_multi_facet(self):
        delta = _valid_source_delta([_changed_file("merger/lenskit/tests/test_x.py")])
        card = produce_pr_delta_card(delta, "merger/lenskit/tests/test_x.py")
        assert len(card["facets"]) > 0
        
    def test_controlled_lens_card(self, monkeypatch):
        import merger.lenskit.core.pr_delta_cards as core_mod
        called = False
        def fake_produce(*args, **kwargs):
            nonlocal called
            called = True
            from merger.lenskit.core.lens_cards import produce_lens_card
            return produce_lens_card(*args, **kwargs)
        monkeypatch.setattr(core_mod, "produce_lens_card", fake_produce)
        produce_pr_delta_card(_valid_source_delta(), "src/main.py")
        assert called
        
    def test_same_source_same_card(self):
        delta = _valid_source_delta([_added_file("a")])
        c1 = produce_pr_delta_card(delta, "a")
        c2 = produce_pr_delta_card(delta, "a")
        assert c1 == c2


class TestContractParity:
    def test_schema_parity(self):
        import json
        from pathlib import Path
        
        contracts_dir = Path("merger/lenskit/contracts")
        pr_schau = json.loads((contracts_dir / "pr-schau-delta.v1.schema.json").read_text())
        lens_card = json.loads((contracts_dir / "lens-card.v1.schema.json").read_text())
        pr_delta = json.loads((contracts_dir / "pr-delta-card.v1.schema.json").read_text())
        lens_facet = json.loads((contracts_dir / "lens-facet.v1.schema.json").read_text())
        
        # 1. Path pattern parity
        lc_path = lens_card["definitions"]["repo_path"]["pattern"]
        pr_path = pr_delta["definitions"]["repo_path"]["pattern"]
        assert pr_path == lc_path, "Path pattern must be identical"
        
        # 2. Primary Lens enum
        lc_lens = lens_card["properties"]["primary_lens"]["enum"]
        pr_lens = pr_delta["properties"]["primary_lens"]["enum"]
        assert pr_lens == lc_lens, "Primary lens enums must be identical"
        
        lc_facets = lens_card["definitions"]["facet"]["properties"]["facet"]["enum"]
        pr_facets = pr_delta["definitions"]["facet"]["properties"]["facet"]["enum"]
        assert pr_facets == lc_facets, "Facets enums must be identical"
        
        # 4. Navigation Ref shape
        lc_refs = lens_card["definitions"]["navigation_ref"]
        pr_refs = pr_delta["definitions"]["navigation_ref"]
        assert pr_refs == lc_refs, "Navigation refs shape must be identical"
        
        # 5. Change-Status == PR-Schau-Delta-Status
        pr_status = pr_delta["properties"]["change_status"]["enum"]
        schau_status = pr_schau["properties"]["files"]["items"]["properties"]["status"]["enum"]
        assert pr_status == schau_status, "Change status enums must match"
        
        # 6. Context source kind and version
        ctx_kind = pr_delta["properties"]["delta_context"]["properties"]["source_kind"]["const"]
        schau_kind = pr_schau["properties"]["kind"]["const"]
        assert ctx_kind == schau_kind, "Source kind must match"
        
        ctx_version = pr_delta["properties"]["delta_context"]["properties"]["source_version"]["const"]
        schau_version = pr_schau["properties"]["version"]["const"]
        assert ctx_version == schau_version, "Source version must match"
        
        # 7. Facet-/Source-Rule-Bindungen identisch
        assert pr_delta["properties"]["matched_rule"]["type"] == lens_card["properties"]["matched_rule"]["type"]

