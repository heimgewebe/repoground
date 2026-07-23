import json
from pathlib import Path

from scripts.ci.emit_security_alert_summary import main


def _write_sarif(path: Path, results: list[dict]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "python.sarif").write_text(
        json.dumps({"version": "2.1.0", "runs": [{"results": results}]}),
        encoding="utf-8",
    )


def _run(monkeypatch, args, capsys):
    monkeypatch.setattr("sys.argv", ["emit_security_alert_summary.py", *args])
    exit_code = main()
    return exit_code, capsys.readouterr().out


def test_zero_findings_sarif_dir_is_clean_and_exits_zero(tmp_path, monkeypatch, capsys):
    sarif_dir = tmp_path / "codeql-results"
    _write_sarif(sarif_dir, [])

    exit_code, out = _run(monkeypatch, ["--sarif-dir", str(sarif_dir)], capsys)

    assert exit_code == 0
    assert '"state": "clean"' in out


def test_findings_present_in_sarif_dir_exits_nonzero(tmp_path, monkeypatch, capsys):
    sarif_dir = tmp_path / "codeql-results"
    _write_sarif(
        sarif_dir,
        [
            {
                "ruleId": "py/path-injection",
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": "example.py"},
                            "region": {"startLine": 3},
                        }
                    }
                ],
            }
        ],
    )

    exit_code, out = _run(monkeypatch, ["--sarif-dir", str(sarif_dir)], capsys)

    assert exit_code == 1
    assert '"state": "alerts_present"' in out
    assert '"alert_count": 1' in out


def test_missing_sarif_dir_is_unavailable_not_clean_and_exits_nonzero(tmp_path, monkeypatch, capsys):
    missing_dir = tmp_path / "does-not-exist"

    exit_code, out = _run(monkeypatch, ["--sarif-dir", str(missing_dir)], capsys)

    assert exit_code == 1
    assert '"state": "unavailable"' in out
    assert '"state": "clean"' not in out


def test_api_401_response_is_unauthorized_and_exits_nonzero(tmp_path, monkeypatch, capsys):
    api_response = tmp_path / "api-response.json"
    api_response.write_text(json.dumps({"status_code": 401, "open_alert_count": None}), encoding="utf-8")

    exit_code, out = _run(monkeypatch, ["--api-response", str(api_response)], capsys)

    assert exit_code == 1
    assert '"state": "unauthorized"' in out


def test_api_404_response_alone_is_unavailable_not_clean(tmp_path, monkeypatch, capsys):
    api_response = tmp_path / "api-response.json"
    api_response.write_text(json.dumps({"status_code": 404, "open_alert_count": None}), encoding="utf-8")

    exit_code, out = _run(monkeypatch, ["--api-response", str(api_response)], capsys)

    assert exit_code == 1
    assert '"state": "unavailable"' in out
    assert '"state": "clean"' not in out


def test_no_evidence_at_all_fails_closed_to_unknown(monkeypatch, capsys):
    exit_code, out = _run(monkeypatch, [], capsys)

    assert exit_code == 1
    assert '"state": "unknown"' in out


def test_writes_summary_to_output_path(tmp_path, monkeypatch, capsys):
    sarif_dir = tmp_path / "codeql-results"
    _write_sarif(sarif_dir, [])
    output_path = tmp_path / "security-alert-summary.json"

    exit_code, _out = _run(
        monkeypatch,
        ["--sarif-dir", str(sarif_dir), "--output", str(output_path)],
        capsys,
    )

    assert exit_code == 0
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["state"] == "clean"


def test_cli_raw_empty_api_page_without_pagination_proof_fails_closed(tmp_path, monkeypatch, capsys):
    api_response = tmp_path / "raw-alerts.json"
    api_response.write_text(json.dumps([]), encoding="utf-8")

    exit_code, out = _run(monkeypatch, ["--api-response", str(api_response)], capsys)

    assert exit_code == 1
    assert '"state": "unknown"' in out
    assert 'api_zero_count_pagination_unproven' in out


def test_cli_supports_repository_and_commit_sha_arguments(tmp_path, monkeypatch, capsys):
    sarif_dir = tmp_path / "codeql-results"
    _write_sarif(sarif_dir, [])

    exit_code, out = _run(
        monkeypatch,
        [
            "--sarif-dir",
            str(sarif_dir),
            "--repository",
            "heimgewebe/repoground",
            "--commit-sha",
            "1234567890abcdef1234567890abcdef12345678",
        ],
        capsys,
    )

    assert exit_code == 0
    assert '"repository": "heimgewebe/repoground"' in out
    assert '"commit_sha": "1234567890abcdef1234567890abcdef12345678"' in out


def test_cli_returns_exit_code_2_on_classification_error(tmp_path, monkeypatch, capsys):
    api_response = tmp_path / "api-invalid.json"
    api_response.write_text(
        json.dumps({"status_code": 200, "open_alert_count": -5}), encoding="utf-8"
    )

    exit_code, out = _run(monkeypatch, ["--api-response", str(api_response)], capsys)

    assert exit_code == 2
    assert "security-alert readback error:" in out

