#!/usr/bin/env python3
"""Validate that every CodeQL path-injection suppression is reviewed and inventoried."""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import subprocess
import tokenize
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

_MARKER_TEXT = "lgtm[py/path-injection]"
_SUPPRESSION_BLOCK_RE = re.compile(
    r"(?P<marker>(?:lgtm|codeql)\s*\[(?P<rules>[^\]]*)\])",
    re.IGNORECASE,
)
_TARGET_TEXT_RE = re.compile(
    r"(?:lgtm|codeql)\s*\[[^\]]*py\s*/\s*path-injection[^\]]*\]",
    re.IGNORECASE,
)
_BOUNDARY_RE = re.compile(r"\bcodeql-boundary:([a-z0-9][a-z0-9-]*)\b")
_EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}


def _load_inventory(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid suppression inventory: {path}") from exc
    if data.get("schema_version") != 1:
        raise ValueError("Suppression inventory schema_version must be 1")
    if data.get("rule") != "py/path-injection":
        raise ValueError("Suppression inventory rule must be py/path-injection")
    if data.get("marker") != _MARKER_TEXT:
        raise ValueError(f"Suppression inventory marker must be {_MARKER_TEXT}")
    boundaries = data.get("boundaries")
    if not isinstance(boundaries, dict) or not boundaries:
        raise ValueError("Suppression inventory boundaries must be a non-empty object")
    return data


def _is_python_source(path: Path) -> bool:
    if path.is_symlink():
        return path.suffix.lower() in {".py", ".pyi", ".pyw"}
    if path.suffix.lower() in {".py", ".pyi", ".pyw"}:
        return True
    if path.suffix:
        return False
    try:
        with path.open("rb") as handle:
            first_line = handle.readline(512).lower()
    except OSError:
        return False
    return first_line.startswith(b"#!") and b"python" in first_line


def _python_sources(root: Path) -> list[Path]:
    root_resolved = root.resolve()
    sources: list[Path] = []
    for directory, child_dirs, filenames in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        child_dirs[:] = sorted(
            name for name in child_dirs if name not in _EXCLUDED_DIRECTORY_NAMES
        )
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if not _is_python_source(path):
                continue
            relative = path.relative_to(root)
            try:
                path.resolve(strict=True).relative_to(root_resolved)
            except (OSError, RuntimeError, ValueError) as exc:
                raise ValueError(
                    f"Python source escapes repository root: {relative.as_posix()}"
                ) from exc
            sources.append(path)
    return sources


def _assert_tracked_python_coverage(root: Path, sources: list[Path]) -> None:
    git_marker = root / ".git"
    if not git_marker.exists():
        return
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("Cannot enumerate tracked Python files") from exc

    tracked = set()
    for item in result.stdout.split(b"\0"):
        if not item:
            continue
        relative = item.decode("utf-8")
        candidate = root / relative
        if _is_python_source(candidate):
            tracked.add(relative)
    scanned = {path.relative_to(root).as_posix() for path in sources}
    missed = sorted(tracked - scanned)
    if missed:
        raise ValueError(
            "Tracked Python files are excluded from suppression scanning: "
            + ", ".join(missed)
        )


def _scope_ranges(module: ast.Module) -> list[tuple[int, int, str]]:
    ranges: list[tuple[int, int, str]] = []

    def visit(body: list[ast.stmt], prefix: str = "") -> None:
        for node in body:
            if not isinstance(
                node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            name = f"{prefix}.{node.name}" if prefix else node.name
            end_line = getattr(node, "end_lineno", node.lineno)
            ranges.append((node.lineno, end_line, name))
            visit(node.body, name)

    visit(module.body)
    return ranges


def _scope_for_line(ranges: list[tuple[int, int, str]], line: int) -> str:
    candidates = [
        (end - start, name)
        for start, end, name in ranges
        if start <= line <= end
    ]
    if not candidates:
        return "<module>"
    return min(candidates, key=lambda item: item[0])[1]

def _target_suppressions(comment: str) -> list[tuple[str, str | None]]:
    matches = list(_SUPPRESSION_BLOCK_RE.finditer(comment))
    found: list[tuple[str, str | None]] = []
    for index, match in enumerate(matches):
        normalized_rules = re.sub(r"\s+", "", match.group("rules")).casefold()
        if "py/path-injection" not in normalized_rules:
            continue
        segment_end = matches[index + 1].start() if index + 1 < len(matches) else len(comment)
        tail = comment[match.end():segment_end]
        boundary_match = _BOUNDARY_RE.search(tail)
        boundary = boundary_match.group(1) if boundary_match else None
        found.append((match.group("marker"), boundary))
    return found


def _scan(root: Path) -> list[tuple[str, int, str, str | None, str, str]]:
    found: list[tuple[str, int, str, str | None, str, str]] = []
    sources = _python_sources(root)
    _assert_tracked_python_coverage(root, sources)
    for path in sources:
        relative = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"Cannot read Python source: {relative}") from exc
        lines = source.splitlines()
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        except (IndentationError, tokenize.TokenError) as exc:
            if _TARGET_TEXT_RE.search(source):
                raise ValueError(
                    f"Cannot tokenize Python source containing suppression: {relative}"
                ) from exc
            continue
        suppression_tokens = [
            token
            for token in tokens
            if token.type == tokenize.COMMENT and _target_suppressions(token.string)
        ]
        if not suppression_tokens:
            continue
        try:
            module = ast.parse(source, filename=relative)
        except SyntaxError as exc:
            raise ValueError(
                f"Cannot parse Python source containing suppression: {relative}"
            ) from exc
        ranges = _scope_ranges(module)
        for token in suppression_tokens:
            line_number, column = token.start
            statement = lines[line_number - 1][:column].strip()
            scope = _scope_for_line(ranges, line_number)
            for marker, boundary in _target_suppressions(token.string):
                found.append(
                    (relative, line_number, marker, boundary, scope, statement)
                )
    return found


def _resolve_inventory_path(root: Path, raw_path: str) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
        return None
    if "\\" in raw_path or raw_path != raw_path.strip():
        return None
    pure = PurePosixPath(raw_path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    if pure.as_posix() != raw_path:
        return None
    candidate = root.joinpath(*pure.parts)
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate


def _test_reference_exists(root: Path, test_ref: str) -> bool:
    parts = test_ref.split("::")
    if len(parts) < 2 or not parts[-1].startswith("test_"):
        return False
    path = _resolve_inventory_path(root, parts[0])
    if path is None or not path.name.startswith("test_") or not path.is_file():
        return False
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return False

    body = module.body
    for name in parts[1:]:
        match = next(
            (
                node
                for node in body
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name
            ),
            None,
        )
        if match is None:
            return False
        body = match.body if isinstance(match, ast.ClassDef) else []
    return True


def validate(root: Path, inventory_path: Path) -> list[str]:
    inventory = _load_inventory(inventory_path)
    boundaries: dict[str, Any] = inventory["boundaries"]
    findings: list[str] = []

    observed = _scan(root)
    counts: Counter[str] = Counter()
    files_by_boundary: dict[str, set[str]] = defaultdict(set)
    sites_by_boundary: dict[str, Counter[tuple[str, str, str]]] = defaultdict(Counter)

    for path, line, marker, boundary, scope, statement in observed:
        if marker != _MARKER_TEXT:
            findings.append(
                f"unsupported suppression marker {marker} at {path}:{line}; "
                f"expected {_MARKER_TEXT}"
            )
            continue
        if boundary is None:
            findings.append(f"unregistered suppression at {path}:{line}")
            continue
        if boundary not in boundaries:
            findings.append(f"unknown boundary {boundary} at {path}:{line}")
            continue
        if not statement:
            findings.append(
                f"suppression {boundary} at {path}:{line} must be inline with its sink"
            )
        counts[boundary] += 1
        files_by_boundary[boundary].add(path)
        sites_by_boundary[boundary][(path, scope, statement)] += 1

    for boundary, record in sorted(boundaries.items()):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", boundary):
            findings.append(f"invalid boundary identifier: {boundary}")
            continue
        if not isinstance(record, dict):
            findings.append(f"boundary {boundary} must be an object")
            continue

        expected = record.get("expected_occurrences")
        if not isinstance(expected, int) or expected <= 0:
            findings.append(f"boundary {boundary} has invalid expected_occurrences")
        elif counts[boundary] != expected:
            findings.append(
                f"boundary {boundary} expected {expected} occurrence(s), "
                f"found {counts[boundary]}"
            )

        expected_files = record.get("files")
        if not isinstance(expected_files, list) or not expected_files or not all(
            isinstance(item, str)
            and _resolve_inventory_path(root, item) is not None
            for item in expected_files
        ):
            findings.append(f"boundary {boundary} has invalid files")
        elif len(set(expected_files)) != len(expected_files):
            findings.append(f"boundary {boundary} contains duplicate files")
        elif set(expected_files) != files_by_boundary[boundary]:
            findings.append(
                f"boundary {boundary} files mismatch: expected {sorted(expected_files)}, "
                f"found {sorted(files_by_boundary[boundary])}"
            )

        expected_sites = record.get("sites")
        if not isinstance(expected_sites, list) or not expected_sites:
            findings.append(f"boundary {boundary} has no site inventory")
        else:
            parsed_sites: Counter[tuple[str, str, str]] = Counter()
            for site in expected_sites:
                if not isinstance(site, dict):
                    findings.append(f"boundary {boundary} has invalid site entry")
                    continue
                site_path = site.get("path")
                scope = site.get("scope")
                statement = site.get("statement")
                if (
                    not isinstance(site_path, str)
                    or _resolve_inventory_path(root, site_path) is None
                    or not isinstance(scope, str)
                    or not scope.strip()
                    or not isinstance(statement, str)
                    or not statement.strip()
                ):
                    findings.append(f"boundary {boundary} has invalid site entry")
                    continue
                parsed_sites[(site_path, scope, statement)] += 1
            if isinstance(expected, int) and sum(parsed_sites.values()) != expected:
                findings.append(
                    f"boundary {boundary} site inventory has "
                    f"{sum(parsed_sites.values())} occurrence(s), expected {expected}"
                )
            if parsed_sites != sites_by_boundary[boundary]:
                expected_rendered = sorted(
                    f"{path}::{scope}: {statement}"
                    for (path, scope, statement), count in parsed_sites.items()
                    for _ in range(count)
                )
                observed_rendered = sorted(
                    f"{path}::{scope}: {statement}"
                    for (path, scope, statement), count in sites_by_boundary[boundary].items()
                    for _ in range(count)
                )
                findings.append(
                    f"boundary {boundary} sites mismatch: "
                    f"expected {expected_rendered}, found {observed_rendered}"
                )

        authority = record.get("authority")
        if not isinstance(authority, str) or not authority.strip():
            findings.append(f"boundary {boundary} has no authority rationale")

        validation = record.get("validation")
        if not isinstance(validation, list) or not validation or not all(
            isinstance(item, str) and item.strip() for item in validation
        ):
            findings.append(f"boundary {boundary} has no validation rationale")

        tests = record.get("tests")
        if not isinstance(tests, list) or not tests or not all(
            isinstance(item, str) and item.strip() for item in tests
        ):
            findings.append(f"boundary {boundary} has no regression tests")
        else:
            for test_ref in tests:
                if not _test_reference_exists(root, test_ref):
                    findings.append(
                        f"boundary {boundary} references missing test: {test_ref}"
                    )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("config/codeql-path-suppressions.v1.json"),
    )
    args = parser.parse_args()

    root = args.root.resolve()
    inventory = args.inventory
    if not inventory.is_absolute():
        inventory = root / inventory

    try:
        findings = validate(root, inventory)
    except ValueError as exc:
        print(f"CodeQL suppression ratchet error: {exc}")
        return 2

    if findings:
        print(f"CodeQL suppression ratchet found {len(findings)} problem(s):")
        for finding in findings:
            print(f"- {finding}")
        return 1

    observed = _scan(root)
    print(
        "CodeQL suppression ratchet passed: "
        f"{len(observed)} suppression(s), all inventoried."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
