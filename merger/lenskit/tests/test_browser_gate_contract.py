import ast
from pathlib import Path

import yaml

from scripts.ci.check_browser_gate_environment import EXPECTED_VERSIONS

ROOT = Path(__file__).resolve().parents[3]
IMAGE = (
    "mcr.microsoft.com/playwright/python:v1.61.0-noble@sha256:"
    "a9731514f24121d1dcd25d58d0a38146646d290a5998fd80d3e533e7b5e21c69"
)

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
    assert steps[0]["uses"] == (
        "actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd"
    )
    commands = "\n".join(str(step.get("run", "")) for step in steps)
    assert (
        "--require-hashes -r requirements/repobrief-browser.lock.txt"
        in commands
    )
    assert "scripts/ci/check_browser_gate_environment.py" in commands
    assert "-m browser merger/lenskit/tests/test_webui_payload.py" in commands
    assert "--browser chromium" in commands
    assert "--tracing retain-on-failure" in commands

    upload = next(step for step in steps if step.get("name") == "Upload browser diagnostics after failure")
    assert upload["if"] == "failure()"
    assert upload["uses"] == (
        "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f"
    )


def test_browser_suite_contains_all_current_browser_flows() -> None:
    path = ROOT / "merger/lenskit/tests/test_webui_payload.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    tests = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    assert len(tests) >= 10
