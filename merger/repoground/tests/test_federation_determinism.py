import json
import hashlib
from pathlib import Path
from merger.repoground.core.federation import init_federation, add_bundle

def test_federation_index_builds_deterministically(tmp_path: Path, monkeypatch):
    """
    Stellt sicher, dass identische logische Inhalte unabhängig von der
    Add-Reihenfolge zur gleichen kanonischen Ausgabe im Index führen.
    """
    from datetime import datetime, timezone
    fixed_now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    class MockDatetime:
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    import merger.repoground.core.federation as fed_module
    monkeypatch.setattr(fed_module.datetime, "datetime", MockDatetime)

    index_1_path = tmp_path / "fed1.json"
    init_federation("test-det-fed", index_1_path)

    index_2_path = tmp_path / "fed2.json"
    init_federation("test-det-fed", index_2_path)

    # Add bundles in order A, B, C to fed1
    add_bundle(index_1_path, "repo-a", "/bundles/repo-a")
    add_bundle(index_1_path, "repo-b", "/bundles/repo-b")
    add_bundle(index_1_path, "repo-c", "/bundles/repo-c")

    # Add bundles in order C, A, B to fed2
    add_bundle(index_2_path, "repo-c", "/bundles/repo-c")
    add_bundle(index_2_path, "repo-a", "/bundles/repo-a")
    add_bundle(index_2_path, "repo-b", "/bundles/repo-b")

    with index_1_path.open("r", encoding="utf-8") as f:
        data_1 = json.load(f)

    with index_2_path.open("r", encoding="utf-8") as f:
        data_2 = json.load(f)

    # First, verify sorting works properly
    assert [b["repo_id"] for b in data_1["bundles"]] == ["repo-a", "repo-b", "repo-c"]
    assert [b["repo_id"] for b in data_2["bundles"]] == ["repo-a", "repo-b", "repo-c"]

    # Verify identical canonical json dump
    json_1_str = json.dumps(data_1, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    json_2_str = json.dumps(data_2, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    hash_1 = hashlib.sha256(json_1_str.encode("utf-8")).hexdigest()
    hash_2 = hashlib.sha256(json_2_str.encode("utf-8")).hexdigest()

    assert hash_1 == hash_2
    assert data_1 == data_2
