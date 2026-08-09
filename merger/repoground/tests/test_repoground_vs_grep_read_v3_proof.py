import json

from merger.repoground.tests.test_repoground_vs_grep_read_benchmark import (
    _benchmark_module,
    _fixture_index,
)


def test_v3_fixture_payload_measurement_matches_contract_proof(monkeypatch, tmp_path):
    module = _benchmark_module()
    root = tmp_path / "repo"
    source = root / "src" / "widget.py"
    source.parent.mkdir(parents=True)
    source.write_text("def widget():\n    return 'widget'\n", encoding="utf-8")
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)

    result, process_calls, read_calls = module._grep_read(root, "widget", 1)
    response_bytes = len(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )

    assert result["reads"][0]["bytes_read"] == 34
    assert response_bytes == 211
    assert (response_bytes + 3) // 4 == 53
    assert process_calls == 0
    assert read_calls == 1


def test_v3_readonly_index_uri_handles_uri_delimiters(tmp_path):
    module = _benchmark_module()
    root, index, questions = _fixture_index(tmp_path)
    special_index = index.with_name("fixture?x#y.index.sqlite")
    index.rename(special_index)

    report = module.run(special_index, root, questions, k=1)

    assert report["inputs"]["index_path"] == special_index.name
    assert report["cases"][0]["repoground"]["paths"] == ["src/widget.py"]
