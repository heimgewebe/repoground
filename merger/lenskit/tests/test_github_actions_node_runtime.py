from __future__ import annotations

import re
from pathlib import Path


WORKFLOW_ROOT = Path(".github/workflows")
MINIMUM_NODE24_MAJORS = {
    "actions/checkout": 5,
    "actions/setup-node": 5,
    "actions/setup-python": 6,
    "actions/upload-artifact": 6,
    "github/codeql-action/analyze": 4,
    "github/codeql-action/autobuild": 4,
    "github/codeql-action/init": 4,
}
USES_RE = re.compile(r"\buses:\s*([^\s#]+)")
MAJOR_RE = re.compile(r"^v(\d+)$")


def _workflow_texts() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in sorted(WORKFLOW_ROOT.glob("*.y*ml"))}


def test_node24_compatibility_override_is_absent() -> None:
    occurrences = [
        str(path)
        for path, text in _workflow_texts().items()
        if "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" in text
    ]

    assert occurrences == []


def test_known_javascript_actions_use_node24_native_majors() -> None:
    seen: dict[str, set[int]] = {name: set() for name in MINIMUM_NODE24_MAJORS}
    invalid: list[str] = []

    for path, text in _workflow_texts().items():
        for raw_use in USES_RE.findall(text):
            if "@" not in raw_use:
                continue
            action, ref = raw_use.rsplit("@", 1)
            if action not in MINIMUM_NODE24_MAJORS:
                continue
            match = MAJOR_RE.fullmatch(ref)
            if match is None:
                invalid.append(f"{path}: {raw_use} is not a reviewable major tag")
                continue
            major = int(match.group(1))
            seen[action].add(major)
            minimum = MINIMUM_NODE24_MAJORS[action]
            if major < minimum:
                invalid.append(f"{path}: {raw_use} is below Node-24 major v{minimum}")

    missing = sorted(action for action, majors in seen.items() if not majors)
    assert missing == []
    assert invalid == []
