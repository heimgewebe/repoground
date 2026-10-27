"""Bounded lexical declarations for languages already represented by the file graph.

No parser dependency or runtime inference: unique literal local references get
S1 file edges, unresolved/dynamic/lexically uncertain declarations remain S0.
All candidate files come from the existing architecture.graph inventory.
"""
from __future__ import annotations

import json
import posixpath
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from merger.repoground.architecture.relationship_projection import _edge, _safe_path, _source

MAX_FILES = 10_000
MAX_SOURCE_BYTES = 250_000
MAX_TOTAL_BYTES = 64_000_000
MAX_DECLARED_EDGES = 200_000
_JS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_TARGET_SUFFIXES = (*_JS_SUFFIXES, ".nix", ".json", ".yaml", ".yml")
_JS_DECLARATION = re.compile(
    r"^[ \t]*(?P<kind>import|export)\s+(?:type\s+)?"
    r"(?:[\w{},* \t\n]{1,250}?\s+from\s+)?"
    r"(?P<quote>['\"])(?P<ref>[^'\"\s]{1,240})(?P=quote)",
    re.DOTALL,
)
_JS_TRIVIA = re.compile(
    r"/\*[\s\S]*?\*/|//[^\n]*|\x60(?:\\.|[^\x60])*\x60"
)
_NIX_TRIVIA = re.compile(
    r"/\*[\s\S]*?\*/|''[\s\S]*?''|\"(?:\\.|[^\"\\])*\"|#[^\n]*"
)
_NIX_LITERAL = re.compile(r"(?<![\w./])(?P<ref>\.{1,2}/[a-zA-Z0-9_./-]+\.nix)(?![\w])")
_JSON_REF = re.compile(r'"\$ref"\s*:\s*"(?P<ref>(?:\\.|[^"\\])*)"')


def _mask(match: re.Match[str]) -> str:
    """Remove trivia while preserving line numbers and column positions."""
    return "".join("\n" if char == "\n" else " " for char in match.group(0))


def _resolve_local(
    source_path: str, ref: str, known_files: set[str], *, extensions: Sequence[str],
) -> tuple[str, str, list[str]]:
    """Resolve only unique repository-local path spellings, never import search paths."""
    if not ref.startswith(("./", "../")):
        return "module:" + ref, "unresolved", []
    basedir = str(PurePosixPath(source_path).parent)
    base = posixpath.normpath(posixpath.join(basedir, ref))
    if base == ".." or base.startswith("../") or base.startswith("/"):
        return "module:" + ref, "unresolved", []
    suffix = PurePosixPath(base).suffix
    paths = [base] if suffix in extensions else [
        *(base + ext for ext in extensions),
        *(base + "/index" + ext for ext in extensions),
    ]
    matches = sorted({"file:" + path for path in paths if "file:" + path in known_files})
    if len(matches) == 1:
        return matches[0], "resolved", matches
    if len(matches) > 1:
        return "module:" + ref, "ambiguous", matches[:20]
    return "module:" + ref, "unresolved", []


def _js_edges(path: str, source: str, known: set[str]) -> list[dict[str, Any]]:
    clean = _JS_TRIVIA.sub(_mask, source)
    lines = clean.splitlines()
    result: list[dict[str, Any]] = []
    for ordinal, line in enumerate(lines):
        if not line.lstrip().startswith(("import ", "export ")):
            continue
        candidate = "\n".join(lines[ordinal : ordinal + 8])
        match = _JS_DECLARATION.match(candidate)
        if match is None:
            continue
        target, status, possibilities = _resolve_local(
            path, match.group("ref"), known, extensions=_JS_SUFFIXES,
        )
        relation = "imports" if match.group("kind") == "import" else "references"
        evidence = _source(path, ordinal + 1, ordinal + 1 + match.group(0).count("\n"))
        result.append(_edge(
            relation, "file:" + path, target, evidence,
            status, "S1" if status == "resolved" else "S0", "js_ts_lexical_declaration",
            candidates=possibilities if status == "ambiguous" else None,
        ))
    return result



_JS_FUNCTION = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+"
    r"(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*\("
)
_JS_CALL = re.compile(r"(?<![.\w$])(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*\(")
_JS_STRING = re.compile(r"""'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*" """ .strip())


def _js_function_edges(path: str, source: str) -> list[dict[str, Any]]:
    """Emit precise lexical declarations and explicitly unresolved same-file callsites.

    This conservative lexer does not model JS lexical scopes, overloads, dynamic
    dispatch or TypeScript type semantics; calls remain S0 even for one candidate.
    """
    clean = _JS_TRIVIA.sub(_mask, source)
    lines = clean.splitlines()
    declarations: dict[str, list[str]] = {}
    declaration_lines: set[int] = set()
    edges: list[dict[str, Any]] = []
    for ordinal, line in enumerate(lines, 1):
        match = _JS_FUNCTION.match(line)
        if match is None:
            continue
        name = match.group("name")
        symbol_id = f"js:{path}:function:{name}:L{ordinal}"
        declarations.setdefault(name, []).append(symbol_id)
        declaration_lines.add(ordinal)
        edges.append(_edge(
            "defines", "file:" + path, symbol_id, _source(path, ordinal, ordinal),
            "resolved", "S1", "js_ts_named_function_syntax",
        ))
    if not declarations:
        return []
    for ordinal, line in enumerate(lines, 1):
        if ordinal in declaration_lines:
            continue
        without_strings = _JS_STRING.sub(_mask, line)
        for match in _JS_CALL.finditer(without_strings):
            name = match.group("name")
            candidates = declarations.get(name)
            if not candidates:
                continue
            site = f"{path}:{ordinal}:{match.start()}:{name}"
            import hashlib
            edges.append(_edge(
                "calls", "file:" + path,
                "unresolved-call:" + hashlib.sha256(site.encode("utf-8")).hexdigest(),
                _source(path, ordinal, ordinal), "candidate", "S0",
                "js_ts_lexical_callsite", candidates=candidates,
            ))
    return edges


def _nix_edges(path: str, source: str, known: set[str]) -> list[dict[str, Any]]:
    clean = _NIX_TRIVIA.sub(_mask, source)
    result: list[dict[str, Any]] = []
    within_imports = False
    lines_in_list = 0
    for ordinal, line in enumerate(clean.splitlines(), 1):
        if re.search(r"^\s*imports\s*=\s*\[", line):
            within_imports = True
            lines_in_list = 0
        active = bool(re.search(r"\bimport\s+", line)) or within_imports
        if active:
            for match in _NIX_LITERAL.finditer(line):
                target, status, options = _resolve_local(
                    path, match.group("ref"), known, extensions=(".nix",),
                )
                result.append(_edge(
                    "imports", "file:" + path, target, _source(path, ordinal, ordinal),
                    status, "S1" if status == "resolved" else "S0", "nix_literal_import",
                    candidates=options if status == "ambiguous" else None,
                ))
        if within_imports:
            lines_in_list += 1
            if "]" in line or lines_in_list >= 50:
                within_imports = False
    return result


def _json_edges(path: str, source: str, known: set[str]) -> list[dict[str, Any]]:
    try:
        json.loads(source)
    except (ValueError, RecursionError):
        return []
    result: list[dict[str, Any]] = []
    for match in _JSON_REF.finditer(source):
        ref = json.loads('"' + match.group("ref") + '"')
        if not isinstance(ref, str) or not ref:
            continue
        file_ref = ref.split("#", 1)[0]
        if not file_ref:
            target, status, candidates = "contract-pointer:" + path + ref, "unresolved", []
        else:
            target, status, candidates = _resolve_local(
                path, file_ref, known, extensions=(".json",),
            )
        line = source.count("\n", 0, match.start()) + 1
        result.append(_edge(
            "declares_contract", "file:" + path, target, _source(path, line, line),
            status, "S1" if status == "resolved" else "S0", "json_schema_declared_ref",
            candidates=candidates if status == "ambiguous" else None,
        ))
    return result


def _compose_edges(path: str, source: str) -> list[dict[str, Any]]:
    """Report literal Compose service keys as S0 candidates, not running services."""
    if not re.search(r"(?:^|/)(?:docker-)?compose(?:\.[a-z0-9_-]+)?\.ya?ml$", path):
        return []
    result: list[dict[str, Any]] = []
    in_services = False
    for lineno, line in enumerate(source.splitlines(), 1):
        if line.startswith("#") or not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            in_services = line.strip() == "services:"
            continue
        if not in_services:
            continue
        match = re.fullmatch(r"  ([A-Za-z0-9_-]{1,100}):\s*(?:#.*)?", line)
        if match is None:
            continue
        result.append(_edge(
            "configures_service", "file:" + path,
            "declared-service:" + path + ":" + match.group(1),
            _source(path, lineno, lineno),
            "candidate", "S0", "compose_service_lexical_key",
        ))
    return result


def _edges_for_source(path: str, source: str, known: set[str]) -> list[dict[str, Any]]:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in _JS_SUFFIXES:
        return _js_edges(path, source, known) + _js_function_edges(path, source)
    if suffix == ".nix":
        return _nix_edges(path, source, known)
    if suffix == ".json":
        return _json_edges(path, source, known)
    if suffix in {".yaml", ".yml"}:
        return _compose_edges(path, source)
    return []


def extract_declared_relations(
    repo_root: Path,
    architecture_graph: Mapping[str, Any],
    *,
    max_files: int = MAX_FILES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
    max_relation_edges: int = MAX_DECLARED_EDGES,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read the existing bounded file inventory and produce declared relationships.

    No traversal beyond the recorded graph inventory, no symlink chasing and
    no guessing runtime or parser completeness. Stable output excludes clocks.
    """
    if isinstance(max_files, bool) or not isinstance(max_files, int) or not 1 <= max_files <= MAX_FILES:
        raise ValueError("max_files outside bounded range")
    if (isinstance(max_total_bytes, bool) or not isinstance(max_total_bytes, int)
            or not 1 <= max_total_bytes <= MAX_TOTAL_BYTES):
        raise ValueError("max_total_bytes outside bounded range")
    if (isinstance(max_relation_edges, bool) or not isinstance(max_relation_edges, int)
            or not 1 <= max_relation_edges <= MAX_DECLARED_EDGES):
        raise ValueError("max_relation_edges outside bounded range")
    nodes = architecture_graph.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("architecture graph inventory is unavailable")
    known = {
        node["node_id"] for node in nodes
        if isinstance(node, dict) and node.get("kind") == "file" and isinstance(node.get("node_id"), str)
    }
    files = sorted(
        _safe_path(node["path"]) for node in nodes
        if isinstance(node, dict) and node.get("kind") == "file"
        and isinstance(node.get("path"), str) and PurePosixPath(node["path"]).suffix.lower()
        in (*_JS_SUFFIXES, ".nix", ".json", ".yaml", ".yml")
    )
    root_resolved = repo_root.resolve()
    emitted: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    bytes_read = 0
    parsed = 0
    for ordinal, name in enumerate(files):
        if ordinal >= max_files:
            skipped["file_count_limit"] += 1
            continue
        target = repo_root / name
        try:
            if target.is_symlink() or not target.resolve().is_relative_to(root_resolved):
                skipped["symlink_or_outside_repo"] += 1
                continue
            size = target.stat().st_size
            if size > MAX_SOURCE_BYTES or bytes_read + size > max_total_bytes:
                skipped["source_byte_limit"] += 1
                continue
            data = target.read_bytes()
            if len(data) != size:
                skipped["source_changed_during_read"] += 1
                continue
            source = data.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            skipped["unreadable_source"] += 1
            continue
        bytes_read += len(data)
        parsed += 1
        found = _edges_for_source(name, source, known)
        remaining = max_relation_edges - len(emitted)
        emitted.extend(found[:remaining])
        if len(found) > remaining:
            skipped["relation_edge_limit"] += len(found) - remaining
            skipped["files_not_scanned_after_relation_limit"] += len(files) - ordinal - 1
            break
        if len(emitted) >= max_relation_edges and ordinal < len(files) - 1:
            skipped["files_not_scanned_after_relation_limit"] += len(files) - ordinal - 1
            break
    edges = sorted(
        {item["id"]: item for item in emitted}.values(),
        key=lambda item: (item["source"]["path"], item["source"]["start_line"],
                          item["relation"], item["dst"], item["id"]),
    )
    coverage = {
        "files_selected": len(files), "files_parsed": parsed, "bytes_read": bytes_read,
        "truncated": any(key in skipped for key in ("file_count_limit", "source_byte_limit", "relation_edge_limit", "files_not_scanned_after_relation_limit")),
        "edge_counts": dict(sorted(Counter(item["relation"] for item in edges).items())),
        "skipped": dict(sorted(skipped.items())),
        "does_not_establish": [
            "runtime_dependencies", "parser_completeness", "schema_pointer_validity",
            "installed_packages", "running_compose_services",
        ],
    }
    return edges, coverage