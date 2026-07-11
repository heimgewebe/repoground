#!/usr/bin/env python3
"""Verify the pinned Playwright browser environment and launch Chromium once."""

from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path

EXPECTED_VERSIONS = {
    "playwright": "1.61.0",
    "pytest": "9.0.3",
    "pytest-asyncio": "1.4.0",
    "pytest-base-url": "2.1.0",
    "pytest-playwright": "0.8.0",
}
EXPECTED_BROWSER_ROOT = Path("/ms-playwright")
KIND = "lenskit.browser_gate_environment_check"
VERSION = "v1"


def inspect_environment() -> dict[str, object]:
    findings: list[str] = []
    observed_versions: dict[str, str | None] = {}
    for package, expected in sorted(EXPECTED_VERSIONS.items()):
        try:
            observed = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            observed = None
        observed_versions[package] = observed
        if observed != expected:
            findings.append(
                f"package version mismatch for {package}: expected {expected}, found {observed}"
            )

    configured_root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
    if configured_root != EXPECTED_BROWSER_ROOT:
        findings.append(
            "PLAYWRIGHT_BROWSERS_PATH mismatch: expected "
            f"{EXPECTED_BROWSER_ROOT}, found {configured_root}"
        )

    executable: str | None = None
    browser_version: str | None = None
    title: str | None = None
    if not findings:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                executable_path = Path(playwright.chromium.executable_path)
                executable = str(executable_path)
                try:
                    executable_path.relative_to(EXPECTED_BROWSER_ROOT)
                except ValueError:
                    findings.append(
                        "Chromium executable is outside the pinned browser root: "
                        f"{executable_path}"
                    )
                if not executable_path.is_file():
                    findings.append(f"Chromium executable is missing: {executable_path}")
                if not findings:
                    browser = playwright.chromium.launch(headless=True)
                    browser_version = browser.version
                    page = browser.new_page()
                    page.set_content("<title>lenskit-browser-gate-smoke</title>")
                    title = page.title()
                    browser.close()
                    if title != "lenskit-browser-gate-smoke":
                        findings.append(f"unexpected smoke page title: {title!r}")
        except Exception as exc:  # noqa: BLE001 - diagnostic boundary
            findings.append(f"Chromium launch smoke failed: {type(exc).__name__}: {exc}")

    return {
        "kind": KIND,
        "version": VERSION,
        "status": "pass" if not findings else "fail",
        "expected_browser_root": str(EXPECTED_BROWSER_ROOT),
        "observed_browser_root": str(configured_root),
        "expected_versions": EXPECTED_VERSIONS,
        "observed_versions": observed_versions,
        "chromium_executable": executable,
        "chromium_version": browser_version,
        "smoke_page_title": title,
        "findings": findings,
        "does_not_establish": [
            "coverage of every browser interaction",
            "cross-browser compatibility",
            "absence of rendering regressions",
            "dependency safety",
            "test completeness",
        ],
    }


def main() -> int:
    report = inspect_environment()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
