from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.release.build_release_candidate import (
    LICENSE_EXPRESSION,
    LOCK_PATHS,
    VERSION_RE,
)

INPUT_PATHS = (
    "requirements/repobrief-runtime.in",
    "requirements/repobrief-dev.in",
    "requirements/repobrief-browser.in",
    "requirements/repobrief-lock-tools.in",
)

REQUIRED_FILES = (
    "RELEASE_VERSION",
    "LICENSE",
    "CHANGELOG.md",
    "docs/release/licensing.md",
    "docs/release/release-policy.md",
    "docs/release/upgrade-rollback.md",
    "scripts/release/build_release_candidate.py",
    "scripts/release/verify_release_candidate.py",
    "scripts/release/compile_dependency_locks.sh",
    *INPUT_PATHS,
    *LOCK_PATHS,
)


def _finding(code: str, path: str, detail: str) -> dict[str, str]:
    return {"code": code, "path": path, "detail": detail}


def _check_lock(path: Path, relative: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    text = path.read_text(encoding="utf-8")
    if "Python 3.12" not in text:
        findings.append(
            _finding(
                "LOCK_PYTHON_VERSION",
                relative,
                "lock must be compiled with Python 3.12",
            )
        )

    lines = text.splitlines()
    package_starts: list[tuple[int, str]] = []
    for lineno, line in enumerate(lines, 1):
        if not line or line[0].isspace() or line.startswith(("#", "--")):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s\\]+)\s+\\", line)
        if match is None:
            findings.append(
                _finding(
                    "LOCK_REQUIREMENT_UNSUPPORTED",
                    relative,
                    f"line {lineno}: {line}",
                )
            )
            continue
        package_starts.append((lineno - 1, match.group(1)))

    if not package_starts:
        findings.append(
            _finding("LOCK_EMPTY", relative, "no exact package pins found")
        )
        return findings

    for index, (start, package) in enumerate(package_starts):
        end = package_starts[index + 1][0] if index + 1 < len(package_starts) else len(lines)
        block = "\n".join(lines[start:end])
        if "--hash=sha256:" not in block:
            findings.append(
                _finding(
                    "LOCK_HASH_MISSING",
                    relative,
                    f"{package} has no SHA-256 hash",
                )
            )
    return findings


def _path_filter_blocks(header: str) -> list[set[str]]:
    lines = header.splitlines()
    blocks: list[set[str]] = []
    index = 0
    while index < len(lines):
        match = re.match(r"^(\s+)paths:\s*$", lines[index])
        if match is None:
            index += 1
            continue
        base_indent = len(match.group(1))
        values: set[str] = set()
        index += 1
        while index < len(lines):
            line = lines[index]
            indent = len(line) - len(line.lstrip())
            if line.strip() and indent <= base_indent:
                break
            item = re.match(r'^\s+-\s+["\']?([^"\']+?)["\']?\s*$', line)
            if item is not None:
                values.add(item.group(1))
            index += 1
        blocks.append(values)
    return blocks


def _check_workflows(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    workflow_dir = root / ".github/workflows"
    paths = sorted(
        {*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")}
    )
    lock_pattern = r"requirements/repobrief-[A-Za-z-]+\.lock\.txt"
    for path in paths:
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if re.search(r"\bpip(?:3)?\s+install\b", stripped):
                if "--upgrade pip" in stripped:
                    findings.append(
                        _finding(
                            "WORKFLOW_PIP_UPGRADE",
                            relative,
                            f"line {lineno}: mutable pip upgrade",
                        )
                    )
                    continue
                if (
                    "--require-hashes" not in stripped
                    or "repobrief-" not in stripped
                    or ".lock.txt" not in stripped
                ):
                    findings.append(
                        _finding(
                            "WORKFLOW_UNLOCKED_INSTALL",
                            relative,
                            f"line {lineno}: {stripped}",
                        )
                    )

        if "\njobs:" not in text:
            continue
        header, jobs = text.split("\njobs:", 1)
        used_locks = set(re.findall(lock_pattern, jobs))
        blocks = _path_filter_blocks(header)
        for block_number, block in enumerate(blocks, 1):
            for lock in sorted(used_locks - block):
                findings.append(
                    _finding(
                        "WORKFLOW_LOCK_TRIGGER_MISSING",
                        relative,
                        f"paths block {block_number} does not include {lock}",
                    )
                )
    return findings


def scan(root: str | Path) -> dict[str, object]:
    repo = Path(root).resolve()
    findings: list[dict[str, str]] = []
    for relative in REQUIRED_FILES:
        if not (repo / relative).is_file():
            findings.append(_finding("RELEASE_FILE_MISSING", relative, "required release file is missing"))
    if findings:
        return {"status": "fail", "findings": findings}

    release_version = (repo / "RELEASE_VERSION").read_text(encoding="utf-8").strip()
    if not VERSION_RE.fullmatch(release_version):
        findings.append(_finding("RELEASE_VERSION_INVALID", "RELEASE_VERSION", release_version))
    license_text = (repo / "LICENSE").read_text(encoding="utf-8")
    if LICENSE_EXPRESSION not in license_text:
        findings.append(_finding("LICENSE_REF_MISSING", "LICENSE", LICENSE_EXPRESSION))
    if "No permission is granted" not in license_text:
        findings.append(_finding("LICENSE_BOUNDARY_MISSING", "LICENSE", "restrictive boundary is absent"))
    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{release_version}]" not in changelog:
        findings.append(_finding("CHANGELOG_VERSION_MISSING", "CHANGELOG.md", release_version))

    for relative in LOCK_PATHS:
        findings.extend(_check_lock(repo / relative, relative))
    findings.extend(_check_workflows(repo))

    task_index = json.loads((repo / "docs/tasks/index.json").read_text(encoding="utf-8"))
    task_ids = {
        item.get("id")
        for item in task_index.get("tasks", [])
        if isinstance(item, dict)
    }
    for task_id in (
        "TASK-LENSKIT-SEMANTIC-LOCK-001",
        "TASK-REPOBRIEF-PUBLIC-LICENSE-DECISION-001",
    ):
        if task_id not in task_ids:
            findings.append(_finding("FOLLOWUP_TASK_MISSING", "docs/tasks/index.json", task_id))

    return {
        "status": "pass" if not findings else "fail",
        "release_version": release_version,
        "lock_count": len(LOCK_PATHS),
        "findings": findings,
        "does_not_establish": [
            "public_distribution_permission",
            "product_readiness",
            "semantic_extension_reproducibility",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check RepoBrief release packaging contracts")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    report = scan(args.root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
