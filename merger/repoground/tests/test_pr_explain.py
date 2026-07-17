import json
from merger.repoground.cli.main import main

def test_pr_explain_missing_delta(capsys, tmp_path):
    delta_path = tmp_path / "nonexistent.json"
    assert not delta_path.exists()

    ret = main(["pr-explain", "--delta", str(delta_path)])
    assert ret == 1
    captured = capsys.readouterr()
    assert "Error: PR delta file not found:" in captured.err

def test_pr_explain_valid_delta(capsys, tmp_path):
    delta_data = {
        "repo": "test-repo",
        "summary": {"added": 1, "changed": 2, "removed": 0},
        "files": [
            {"path": "added.py", "status": "added", "suspicious_patterns": ["secret"]},
            {"path": "changed1.py", "status": "changed", "affected_chunk_ids": ["c1", "c2"]},
            {"path": "changed2.py", "status": "changed"}
        ]
    }

    delta_path = tmp_path / "delta.json"
    with open(delta_path, "w", encoding="utf-8") as f:
        json.dump(delta_data, f)

    ret = main(["pr-explain", "--delta", str(delta_path)])
    assert ret == 0
    captured = capsys.readouterr()

    assert "PR Explain:" in captured.out
    assert "Repository: test-repo" in captured.out
    assert "Summary: +1 ~2 -0" in captured.out
    assert "added    added.py" in captured.out
    assert "[!] Suspicious patterns: secret" in captured.out
    assert "changed  changed1.py" in captured.out
    assert "Affected chunks: c1, c2" in captured.out
    assert "changed  changed2.py" in captured.out
