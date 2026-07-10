import json
from pathlib import Path

import pytest

from scripts.ci.check_codeql_suppressions import (
    _assert_tracked_python_coverage,
    _scan,
    validate,
)


def _marker() -> str:
    # Keep the suppression token out of this repository test source itself; the
    # scanner must observe only the temporary fixture written by each test.
    return "lgtm" + "[py/path-injection]"


def _write_inventory(
    root: Path,
    *,
    boundary: str = "fixture-boundary",
    expected_occurrences: int = 1,
    files: list[str] | None = None,
    tests: list[str] | None = None,
    scope: str = "<module>",
) -> Path:
    files = files or ["merger/example.py"]
    tests = tests or ["tests/test_example.py::test_fixture"]
    inventory = {
        "schema_version": 1,
        "rule": "py/path-injection",
        "marker": _marker(),
        "boundaries": {
            boundary: {
                "expected_occurrences": expected_occurrences,
                "files": files,
                "sites": [
                    {
                        "path": "merger/example.py",
                        "scope": scope,
                        "statement": 'open("fixture")',
                    }
                ],
                "authority": "Explicit fixture authority.",
                "validation": ["Fixture validation is bounded."],
                "tests": tests,
            }
        },
    }
    path = root / "config" / "codeql-path-suppressions.v1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inventory), encoding="utf-8")
    return path


def _write_source(
    root: Path,
    marker_suffix: str,
    *,
    statement: str = 'open("fixture")',
    copies: int = 1,
    scope: str | None = None,
) -> None:
    path = root / "merger" / "example.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    statements = "".join(
        f"{statement}  # {_marker()} {marker_suffix}\n"
        for _ in range(copies)
    )
    if scope is not None:
        statements = f"def {scope}():\n" + "".join(
            f"    {line}\n" for line in statements.splitlines()
        )
    path.write_text(statements, encoding="utf-8")
    test_path = root / "tests" / "test_example.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text("def test_fixture():\n    assert True\n", encoding="utf-8")


def test_repository_codeql_suppressions_match_inventory():
    root = Path(__file__).resolve().parents[3]
    inventory = root / "config" / "codeql-path-suppressions.v1.json"

    assert validate(root, inventory) == []


def test_ratchet_rejects_unregistered_suppression(tmp_path):
    inventory = _write_inventory(tmp_path)
    _write_source(tmp_path, "")

    findings = validate(tmp_path, inventory)

    assert any("unregistered suppression" in finding for finding in findings)
    assert any("expected 1 occurrence(s), found 0" in finding for finding in findings)


def test_ratchet_rejects_unknown_boundary(tmp_path):
    inventory = _write_inventory(tmp_path)
    _write_source(tmp_path, "codeql-boundary:unknown-boundary")

    findings = validate(tmp_path, inventory)

    assert any("unknown boundary unknown-boundary" in finding for finding in findings)
    assert any("expected 1 occurrence(s), found 0" in finding for finding in findings)


def test_ratchet_rejects_occurrence_drift(tmp_path):
    inventory = _write_inventory(tmp_path)
    _write_source(
        tmp_path,
        "codeql-boundary:fixture-boundary",
        copies=2,
    )

    findings = validate(tmp_path, inventory)

    assert any(
        "boundary fixture-boundary expected 1 occurrence(s), found 2" in finding
        for finding in findings
    )


def test_ratchet_rejects_site_drift_with_unchanged_count(tmp_path):
    inventory = _write_inventory(tmp_path)
    _write_source(
        tmp_path,
        "codeql-boundary:fixture-boundary",
        statement='open("different")',
    )

    findings = validate(tmp_path, inventory)

    assert len(findings) == 1
    assert "boundary fixture-boundary sites mismatch" in findings[0]
    assert 'open("fixture")' in findings[0]
    assert 'open("different")' in findings[0]


def test_ratchet_rejects_missing_regression_test(tmp_path):
    inventory = _write_inventory(tmp_path, tests=["tests/test_missing.py::test_missing"])
    _write_source(tmp_path, "codeql-boundary:fixture-boundary")

    findings = validate(tmp_path, inventory)

    assert findings == [
        "boundary fixture-boundary references missing test: "
        "tests/test_missing.py::test_missing"
    ]


def test_ratchet_rejects_missing_regression_test_node(tmp_path):
    inventory = _write_inventory(
        tmp_path,
        tests=["tests/test_example.py::test_missing"],
    )
    _write_source(tmp_path, "codeql-boundary:fixture-boundary")

    findings = validate(tmp_path, inventory)

    assert findings == [
        "boundary fixture-boundary references missing test: "
        "tests/test_example.py::test_missing"
    ]


def test_scanner_ignores_marker_inside_python_string(tmp_path):
    path = tmp_path / "merger" / "example.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        f'marker = "{_marker()} codeql-boundary:not-a-comment"\n',
        encoding="utf-8",
    )

    assert _scan(tmp_path) == []


def test_scanner_covers_top_level_python_files(tmp_path):
    path = tmp_path / "top_level.py"
    path.write_text(
        f'open("fixture")  # {_marker()} codeql-boundary:fixture-boundary\n',
        encoding="utf-8",
    )

    assert _scan(tmp_path) == [
        (
            "top_level.py",
            1,
            _marker(),
            "fixture-boundary",
            "<module>",
            'open("fixture")',
        )
    ]


def test_ratchet_rejects_test_reference_outside_repository(tmp_path):
    inventory = _write_inventory(
        tmp_path,
        tests=["../test_outside.py::test_outside"],
    )
    _write_source(tmp_path, "codeql-boundary:fixture-boundary")

    findings = validate(tmp_path, inventory)

    assert findings == [
        "boundary fixture-boundary references missing test: "
        "../test_outside.py::test_outside"
    ]


def test_ratchet_rejects_scope_drift_with_unchanged_statement(tmp_path):
    inventory = _write_inventory(tmp_path, scope="expected_scope")
    _write_source(
        tmp_path,
        "codeql-boundary:fixture-boundary",
        scope="different_scope",
    )

    findings = validate(tmp_path, inventory)

    assert len(findings) == 1
    assert "boundary fixture-boundary sites mismatch" in findings[0]
    assert "expected_scope" in findings[0]
    assert "different_scope" in findings[0]


@pytest.mark.parametrize(
    "marker",
    [
        "codeql[py/path-injection]",
        "lgtm [py/path-injection]",
        "LGTM[PY/PATH-INJECTION]",
        "lgtm[py/other, py/path-injection]",
    ],
)
def test_ratchet_rejects_alternative_codeql_marker(tmp_path, marker):
    inventory = _write_inventory(tmp_path)
    path = tmp_path / "merger" / "example.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'open("fixture")  # {marker} codeql-boundary:fixture-boundary\n',
        encoding="utf-8",
    )
    test_path = tmp_path / "tests" / "test_example.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text("def test_fixture():\n    assert True\n", encoding="utf-8")

    findings = validate(tmp_path, inventory)

    assert any(
        f"unsupported suppression marker {marker}" in finding
        for finding in findings
    )
    assert any("expected 1 occurrence(s), found 0" in finding for finding in findings)


def test_tracked_python_coverage_rejects_excluded_file(tmp_path, monkeypatch):
    scanned = tmp_path / "main.py"
    scanned.write_text("pass\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()

    class Result:
        stdout = b"main.py\0.venv/hidden.py\0"

    monkeypatch.setattr(
        "scripts.ci.check_codeql_suppressions.subprocess.run",
        lambda *args, **kwargs: Result(),
    )

    try:
        _assert_tracked_python_coverage(tmp_path, [scanned])
    except ValueError as exc:
        assert str(exc) == (
            "Tracked Python files are excluded from suppression scanning: "
            ".venv/hidden.py"
        )
    else:
        raise AssertionError("expected tracked Python coverage failure")


def test_scanner_records_nested_class_method_scope(tmp_path):
    path = tmp_path / "nested.py"
    path.write_text(
        "class Example:\n"
        "    def run(self):\n"
        f'        open("fixture")  # {_marker()} '
        "codeql-boundary:fixture-boundary\n",
        encoding="utf-8",
    )

    assert _scan(tmp_path) == [
        (
            "nested.py",
            3,
            _marker(),
            "fixture-boundary",
            "Example.run",
            'open("fixture")',
        )
    ]


def test_scanner_covers_pyi_pyw_and_python_shebang(tmp_path):
    pyi = tmp_path / "types.pyi"
    pyi.write_text(
        f'open("pyi")  # {_marker()} codeql-boundary:fixture-boundary\n',
        encoding="utf-8",
    )
    pyw = tmp_path / "window.pyw"
    pyw.write_text(
        f'open("pyw")  # {_marker()} codeql-boundary:fixture-boundary\n',
        encoding="utf-8",
    )
    script = tmp_path / "tool"
    script.write_text(
        "#!/usr/bin/env python3\n"
        f'open("script")  # {_marker()} codeql-boundary:fixture-boundary\n',
        encoding="utf-8",
    )

    assert _scan(tmp_path) == [
        (
            "tool",
            2,
            _marker(),
            "fixture-boundary",
            "<module>",
            'open("script")',
        ),
        (
            "types.pyi",
            1,
            _marker(),
            "fixture-boundary",
            "<module>",
            'open("pyi")',
        ),
        (
            "window.pyw",
            1,
            _marker(),
            "fixture-boundary",
            "<module>",
            'open("pyw")',
        ),
    ]


def test_scanner_ignores_non_target_suppression_comment(tmp_path):
    path = tmp_path / "example.py"
    path.write_text(
        'open("fixture")  # lgtm[py/other-rule]\n',
        encoding="utf-8",
    )

    assert _scan(tmp_path) == []


def test_scanner_does_not_follow_extensionless_symlink_for_shebang(tmp_path):
    outside = tmp_path / "outside.py-source"
    outside.write_text(
        "#!/usr/bin/env python3\n"
        f'open("outside")  # {_marker()} codeql-boundary:fixture-boundary\n',
        encoding="utf-8",
    )
    link = tmp_path / "tool"
    link.symlink_to(outside)

    assert _scan(tmp_path) == []
