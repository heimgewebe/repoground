import json

from merger.repoground.tests.test_repoground_vs_grep_read_benchmark import (
    _benchmark_module,
    _fixture_index,
)


def test_v3_fixture_payload_measurement_matches_contract_proof():
    # v3 is a frozen historical contract after the v4 comparator change. Keep
    # this fixture independent from the current _grep_read response shape so a
    # later benchmark version cannot silently rewrite the v3 proof measurement.
    result = {
        "query": "widget",
        "k": 1,
        "status": "available",
        "search_engine": "python_utf8_substring",
        "paths": ["src/widget.py"],
        "reads": [
            {
                "path": "src/widget.py",
                "bytes_read": 34,
                "content": "def widget():\n    return 'widget'\n",
            }
        ],
    }
    response_bytes = len(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )

    assert result["reads"][0]["bytes_read"] == 34
    assert response_bytes == 211
    assert (response_bytes + 3) // 4 == 53


def test_readonly_index_uri_handles_uri_delimiters(tmp_path):
    module = _benchmark_module()
    root, index, questions = _fixture_index(tmp_path)
    special_index = index.with_name("fixture?x#y.index.sqlite")
    index.rename(special_index)

    report = module.run(special_index, root, questions, k=1)

    assert report["inputs"]["index_path"] == special_index.name
    assert report["cases"][0]["repoground"]["paths"] == ["src/widget.py"]
