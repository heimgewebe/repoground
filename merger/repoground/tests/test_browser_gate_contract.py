import ast
import re
import sys
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call

import yaml

from scripts.ci import check_browser_gate_environment as browser_gate
from scripts.ci.check_browser_gate_environment import EXPECTED_VERSIONS

ROOT = Path(__file__).resolve().parents[3]
IMAGE = (
    "mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:"
    "aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d"
)
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
BROWSER_EXECUTABLE = "/ms-playwright/chromium-123/chrome-linux/chrome"


def _requirements() -> dict[str, str]:
    observed: dict[str, str] = {}
    for raw in (ROOT / "requirements-browser.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        assert "==" in line, f"browser requirement is not exactly pinned: {line}"
        name, version = line.split("==", 1)
        observed[name] = version
    return observed


def _assert_sha_pinned_action(raw_use: str, expected_action: str) -> None:
    action, separator, ref = raw_use.rpartition("@")
    assert separator == "@"
    assert action == expected_action
    assert SHA40_RE.fullmatch(ref) is not None


def test_browser_requirements_are_minimal_and_compatible() -> None:
    assert _requirements() == EXPECTED_VERSIONS


def test_browser_job_uses_digest_pinned_matching_playwright_image() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/test-suite.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["browser-tests"]
    assert job["container"] == {"image": IMAGE, "options": "--ipc=host"}
    assert job["env"] == {"PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright"}

    steps = job["steps"]
    _assert_sha_pinned_action(steps[0]["uses"], "actions/checkout")
    commands = "\n".join(str(step.get("run", "")) for step in steps)
    assert "--require-hashes -r requirements/repoground-browser.lock.txt" in commands
    assert "scripts/ci/check_browser_gate_environment.py" in commands
    assert "-m browser merger/repoground/tests/test_webui_payload.py" in commands
    assert "--browser chromium" in commands
    assert "--tracing retain-on-failure" in commands

    upload = next(
        step
        for step in steps
        if step.get("name") == "Upload browser diagnostics after failure"
    )
    assert upload["if"] == "failure()"
    _assert_sha_pinned_action(upload["uses"], "actions/upload-artifact")


def test_browser_suite_contains_all_current_browser_flows() -> None:
    path = ROOT / "merger/repoground/tests/test_webui_payload.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    tests = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    assert len(tests) >= 10


def test_browser_environment_reports_package_and_root_drift_without_smoke(
    monkeypatch,
) -> None:
    lookup_order: list[str] = []

    def fake_version(package: str) -> str:
        lookup_order.append(package)
        if package == "playwright":
            raise browser_gate.importlib.metadata.PackageNotFoundError(package)
        if package == "pytest":
            return "0.0"
        return EXPECTED_VERSIONS[package]

    monkeypatch.setattr(browser_gate.importlib.metadata, "version", fake_version)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/wrong-root")

    report = browser_gate.inspect_environment()

    assert lookup_order == sorted(EXPECTED_VERSIONS)
    assert report == {
        "kind": "lenskit.browser_gate_environment_check",
        "version": "v1",
        "status": "fail",
        "expected_browser_root": "/ms-playwright",
        "observed_browser_root": "/wrong-root",
        "expected_versions": EXPECTED_VERSIONS,
        "observed_versions": {
            "playwright": None,
            "pytest": "0.0",
            "pytest-asyncio": "1.4.0",
            "pytest-base-url": "2.1.0",
            "pytest-playwright": "0.8.0",
        },
        "chromium_executable": None,
        "chromium_version": None,
        "smoke_page_title": None,
        "findings": [
            "package version mismatch for playwright: expected 1.62.0, found None",
            "package version mismatch for pytest: expected 9.1.1, found 0.0",
            "PLAYWRIGHT_BROWSERS_PATH mismatch: expected /ms-playwright, found /wrong-root",
        ],
        "does_not_establish": [
            "coverage of every browser interaction",
            "cross-browser compatibility",
            "absence of rendering regressions",
            "dependency safety",
            "test completeness",
        ],
    }


def test_browser_environment_success_preserves_smoke_calls(monkeypatch) -> None:
    page = SimpleNamespace(
        set_content=Mock(),
        title=Mock(return_value="lenskit-browser-gate-smoke"),
    )
    browser = SimpleNamespace(
        version="123.0",
        new_page=Mock(return_value=page),
        close=Mock(),
    )
    chromium = SimpleNamespace(
        executable_path=BROWSER_EXECUTABLE,
        launch=Mock(return_value=browser),
    )
    playwright = SimpleNamespace(chromium=chromium)
    sync_api = ModuleType("playwright.sync_api")
    sync_api.sync_playwright = Mock(return_value=nullcontext(playwright))
    package = ModuleType("playwright")
    package.sync_api = sync_api

    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    monkeypatch.setattr(
        browser_gate.importlib.metadata,
        "version",
        lambda package_name: EXPECTED_VERSIONS[package_name],
    )
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")

    report = browser_gate.inspect_environment()

    assert sync_api.sync_playwright.call_count == 1
    assert chromium.launch.call_args == call(headless=True)
    assert browser.new_page.call_count == 1
    assert page.set_content.call_args == call("<title>lenskit-browser-gate-smoke</title>")
    assert page.title.call_count == 1
    assert browser.close.call_count == 1
    assert report == {
        "kind": "lenskit.browser_gate_environment_check",
        "version": "v1",
        "status": "pass",
        "expected_browser_root": "/ms-playwright",
        "observed_browser_root": "/ms-playwright",
        "expected_versions": EXPECTED_VERSIONS,
        "observed_versions": EXPECTED_VERSIONS,
        "chromium_executable": BROWSER_EXECUTABLE,
        "chromium_version": "123.0",
        "smoke_page_title": "lenskit-browser-gate-smoke",
        "findings": [],
        "does_not_establish": [
            "coverage of every browser interaction",
            "cross-browser compatibility",
            "absence of rendering regressions",
            "dependency safety",
            "test completeness",
        ],
    }
