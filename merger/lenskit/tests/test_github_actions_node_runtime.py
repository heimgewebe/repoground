from __future__ import annotations

import re
from pathlib import Path


WORKFLOW_ROOT = Path(".github/workflows")
ALLOWED_NODE24_MAJORS = {
    "actions/checkout": {5, 6, 7},
    "actions/setup-node": {5, 6, 7},
    "actions/setup-python": {6},
    "actions/upload-artifact": {6, 7},
    "github/codeql-action/analyze": {4},
    "github/codeql-action/autobuild": {4},
    "github/codeql-action/init": {4},
}
USES_LINE_RE = re.compile(
    r"^\s*(?:-\s*)?uses:\s*([^\s#]+)(?:\s+#\s*(.*?))?\s*$",
    re.MULTILINE,
)
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_COMMENT_RE = re.compile(r"^v(\d+)(?:\.\d+){0,2}(?:\s|$)")


def _workflow_texts() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in sorted(WORKFLOW_ROOT.glob("*.y*ml"))
    }


def test_node24_compatibility_override_is_absent() -> None:
    occurrences = [
        str(path)
        for path, text in _workflow_texts().items()
        if "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" in text
    ]

    assert occurrences == []


def test_known_javascript_actions_use_reviewed_node24_majors() -> None:
    seen: dict[str, set[int]] = {name: set() for name in ALLOWED_NODE24_MAJORS}
    invalid: list[str] = []

    for path, text in _workflow_texts().items():
        for raw_use, comment in USES_LINE_RE.findall(text):
            if "@" not in raw_use:
                continue
            action, ref = raw_use.rsplit("@", 1)
            if action not in ALLOWED_NODE24_MAJORS:
                continue
            if SHA40_RE.fullmatch(ref) is None:
                invalid.append(f"{path}: {raw_use} is not pinned to a full commit SHA")
                continue
            match = VERSION_COMMENT_RE.match(comment)
            if match is None:
                invalid.append(
                    f"{path}: {raw_use} lacks a reviewable '# vN' or '# vN.N.N' comment"
                )
                continue
            major = int(match.group(1))
            seen[action].add(major)
            allowed = ALLOWED_NODE24_MAJORS[action]
            if major not in allowed:
                rendered = ", ".join(f"v{item}" for item in sorted(allowed))
                invalid.append(
                    f"{path}: {raw_use} claims unreviewed major v{major}; allowed: {rendered}"
                )

    missing = sorted(action for action, majors in seen.items() if not majors)
    assert missing == []
    assert invalid == []
