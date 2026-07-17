import json
from pathlib import Path

import pytest

from scripts.ci.assert_codeql_sarif_clean import collect_results


def _write_sarif(path: Path, results: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": "2.1.0", "runs": [{"results": results}]}),
        encoding="utf-8",
    )


def test_collect_results_accepts_empty_raw_sarif(tmp_path):
    _write_sarif(tmp_path / "python.sarif", [])

    files, findings = collect_results(tmp_path)

    assert files == [tmp_path / "python.sarif"]
    assert findings == []


def test_collect_results_reports_rule_path_and_line(tmp_path):
    _write_sarif(
        tmp_path / "python.sarif",
        [
            {
                "ruleId": "py/path-injection",
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": "example.py"},
                            "region": {"startLine": 17},
                        }
                    }
                ],
            }
        ],
    )

    _files, findings = collect_results(tmp_path)

    assert findings == ["py/path-injection at example.py:17"]


def test_collect_results_fails_closed_without_sarif(tmp_path):
    with pytest.raises(ValueError, match="No SARIF files found"):
        collect_results(tmp_path)


def test_collect_results_fails_closed_on_invalid_json(tmp_path):
    (tmp_path / "broken.sarif").write_text("not json", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid SARIF file"):
        collect_results(tmp_path)
