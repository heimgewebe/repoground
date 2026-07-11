#!/usr/bin/env python3
"""Reject mutable external GitHub Action and reusable-workflow references."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator

USES_RE = re.compile(r"^(?P<indent>\s*)(?:-\s*)?uses:\s*(?P<value>[^#\s]+)")
BLOCK_RE = re.compile(r"^(?P<indent>\s*)(?:-\s*)?(?:run|script):\s*[|>]\s*[+-]?\s*$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
DOCKER_DIGEST_RE = re.compile(r"^docker://.+@sha256:[0-9a-f]{64}$")
YAML_SUFFIXES = {".yml", ".yaml"}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    reference: str
    code: str
    detail: str


def _candidate_files(root: Path) -> Iterator[Path]:
    roots = (root / ".github" / "workflows", root / ".github" / "actions")
    for candidate_root in roots:
        if not candidate_root.is_dir():
            continue
        for path in sorted(candidate_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in YAML_SUFFIXES:
                yield path


def _uses_entries(path: Path) -> Iterator[tuple[int, str]]:
    block_indent: int | None = None
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if block_indent is not None:
            if indent > block_indent:
                continue
            block_indent = None
        block_match = BLOCK_RE.match(line)
        if block_match:
            block_indent = len(block_match.group("indent"))
            continue
        match = USES_RE.match(line)
        if match:
            yield line_no, match.group("value").strip("'\"")


def _finding(path: Path, root: Path, line: int, ref: str) -> Finding | None:
    relative = path.relative_to(root).as_posix()
    if ref.startswith("./"):
        return None
    if ref.startswith("docker://"):
        if DOCKER_DIGEST_RE.fullmatch(ref):
            return None
        return Finding(
            relative,
            line,
            ref,
            "mutable_docker_reference",
            "Docker action references must use an immutable sha256 digest.",
        )
    if "${{" in ref:
        return Finding(
            relative,
            line,
            ref,
            "dynamic_action_reference",
            "External action references must not be computed dynamically.",
        )
    if "@" not in ref:
        return Finding(
            relative,
            line,
            ref,
            "missing_action_ref",
            "External action references must include an immutable commit ref.",
        )
    _, commit = ref.rsplit("@", 1)
    if not SHA40_RE.fullmatch(commit):
        return Finding(
            relative,
            line,
            ref,
            "mutable_action_ref",
            "External actions and reusable workflows must use a 40-character lowercase commit SHA.",
        )
    return None


def scan(root: Path) -> list[Finding]:
    resolved_root = root.resolve()
    findings: list[Finding] = []
    for path in _candidate_files(resolved_root):
        for line, ref in _uses_entries(path):
            finding = _finding(path, resolved_root, line, ref)
            if finding is not None:
                findings.append(finding)
    return findings


def _report(root: Path, findings: Iterable[Finding]) -> dict[str, object]:
    items = list(findings)
    return {
        "kind": "lenskit.github_actions_pin_check",
        "version": "1.0",
        "root": ".",
        "status": "pass" if not items else "fail",
        "finding_count": len(items),
        "findings": [asdict(item) for item in items],
        "does_not_establish": [
            "absence of malicious code in pinned dependencies",
            "transitive immutability inside externally maintained reusable workflows",
            "future compatibility of pinned dependencies",
            "workflow correctness or least privilege outside the inspected files",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    findings = scan(args.root)
    report = _report(args.root, findings)
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif findings:
        for item in findings:
            print(f"{item.path}:{item.line}: {item.code}: {item.reference} — {item.detail}")
    else:
        print("GitHub Actions pin check: pass")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
