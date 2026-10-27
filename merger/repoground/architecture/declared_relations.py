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
_NIX_TRIVIA = re.compile(
    r"/\*[\s\S]*?\*/|''(?:''(?:\$\{|\\|')|(?!'')[\s\S])*''|\"(?:\\.|[^\"\\])*\"|#[^\n]*"
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
    if not ref.startswith(("./", "../")) or "%" in ref:
        return "module:" + ref, "unresolved", []
    basedir = str(PurePosixPath(source_path).parent)
    base = posixpath.normpath(posixpath.join(basedir, ref))
    if base == ".." or base.startswith("../") or base.startswith("/"):
        return "module:" + ref, "unresolved", []
    suffix = PurePosixPath(base).suffix
    if suffix and suffix not in extensions:
        candidate = "file:" + base
        return "module:" + ref, "unresolved", (
            [candidate] if candidate in known_files else []
        )
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
    syntax_lines, source_lines = _js_sources(source, jsx=path.endswith((".jsx", ".tsx")))
    result: list[dict[str, Any]] = []
    for ordinal, line in enumerate(syntax_lines):
        if not line.lstrip().startswith(("import ", "export ")):
            continue
        candidate = "\n".join(source_lines[ordinal : ordinal + 8])
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
            candidates=possibilities if status != "resolved" else None,
        ))
    return result



_JS_FUNCTION = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+"
    r"(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*\("
)
_JS_CALL = re.compile(r"(?<![.\w$])(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*\(")
def _masked(text: str) -> list[str]:
    return ["\n" if char == "\n" else " " for char in text]


_JSX_ELEMENT = re.compile(
    r"<(?P<tag>[A-Za-z][A-Za-z0-9_.:-]*)\b[^<>]*>[\s\S]*?</(?P=tag)\s*>"
)
_JSX_FRAGMENT = re.compile(r"<>[\s\S]*?</>")

_JS_REGEX_CONTEXT = re.compile(r"\b(?:return|throw|case|yield)\s*$")


def _js_regex_end(source: str, start: int) -> int | None:
    """Recognize a bounded regular-expression token only in expression-start context.

    Division and regex are grammar-ambiguous without a JS parser. Restrict this
    to common unambiguous lexical positions; other syntax remains unproven.
    """
    before = source[max(0, start - 100):start].rstrip()
    if not before or (
        before[-1] not in "=([{:,!?"
        and _JS_REGEX_CONTEXT.search(before) is None
    ):
        return None
    index = start + 1
    inside_class = False
    while index < len(source) and source[index] not in "\r\n":
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            inside_class = True
        elif char == "]":
            inside_class = False
        elif char == "/" and not inside_class:
            index += 1
            while index < len(source) and source[index].isalpha():
                index += 1
            return index
        index += 1
    return None


def _js_quoted_end(source: str, start: int) -> int:
    quote = source[start]
    index = start + 1
    while index < len(source):
        if source[index] == "\\":
            index = min(index + 2, len(source))
        elif source[index] == quote:
            return index + 1
        else:
            index += 1
    return len(source)


def _js_comment_end(source: str, start: int) -> int | None:
    if source.startswith("//", start):
        newline = source.find("\n", start + 2)
        return len(source) if newline < 0 else newline
    if source.startswith("/*", start):
        end = source.find("*/", start + 2)
        return len(source) if end < 0 else end + 2
    return None


def _js_template_end(source: str, start: int, *, depth: int = 0) -> int:
    """Mask all template text, including recursively nested interpolations."""
    if depth > 24:
        return len(source)
    index = start + 1
    while index < len(source):
        if source[index] == "\\":
            index = min(index + 2, len(source))
        elif source.startswith("$" + "{", index):
            index = _js_template_expr_end(source, index + 2, depth=depth + 1)
        elif source[index] == chr(96):
            return index + 1
        else:
            index += 1
    return len(source)


def _js_template_expr_end(source: str, start: int, *, depth: int) -> int:
    """Skip JS-like interpolation expression to the balanced closing brace."""
    braces = 1
    index = start
    while index < len(source):
        comment_end = _js_comment_end(source, index)
        if comment_end is not None:
            index = comment_end
            continue
        character = source[index]
        if character in ("'", '"'):
            index = _js_quoted_end(source, index)
            continue
        if character == chr(96):
            index = _js_template_end(source, index, depth=depth)
            continue
        if character == "/":
            regex_end = _js_regex_end(source, index)
            if regex_end is not None:
                index = regex_end
                continue
        if character == "{":
            braces += 1
        elif character == "}":
            braces -= 1
            if braces == 0:
                return index + 1
        index += 1
    return len(source)


def _js_sources(source: str, *, jsx: bool = False) -> tuple[list[str], list[str]]:
    """Mask comments and strings in one ordered lexical pass.

    Only the literal-preserving view supplies an import specifier after
    an eligible syntax token has been seen. We do not parse template
    interpolation or general JS expressions: missing edges are preferable
    to promoting characters in comments to S1 dependencies.
    """
    syntax = list(source)
    literals = list(source)
    length = len(source)
    index = 0
    while index < length:
        comment_end = _js_comment_end(source, index)
        if comment_end is not None:
            syntax[index:comment_end] = _masked(source[index:comment_end])
            literals[index:comment_end] = _masked(source[index:comment_end])
            index = comment_end
            continue
        if source[index] == "/":
            regex_end = _js_regex_end(source, index)
            if regex_end is not None:
                syntax[index:regex_end] = _masked(source[index:regex_end])
                literals[index:regex_end] = _masked(source[index:regex_end])
                index = regex_end
                continue
        quote = source[index]
        if quote in ("'", '"', chr(96)):
            end = (
                _js_template_end(source, index) if quote == chr(96)
                else _js_quoted_end(source, index)
            )
            syntax[index:end] = _masked(source[index:end])
            if quote == chr(96):
                literals[index:end] = _masked(source[index:end])
            index = end
            continue
        index += 1
    if jsx:
        # JSX child text is not executable JS. Mask entire balanced elements
        # rather than claiming lexically observed imports/functions inside them.
        text = "".join(syntax)
        for pattern in (_JSX_ELEMENT, _JSX_FRAGMENT):
            for match in pattern.finditer(text):
                masked = _masked(source[match.start():match.end()])
                syntax[match.start():match.end()] = masked
                literals[match.start():match.end()] = masked
    return "".join(syntax).splitlines(), "".join(literals).splitlines()


def _js_function_edges(path: str, source: str) -> list[dict[str, Any]]:
    """Emit precise lexical declarations and explicitly unresolved same-file callsites.

    This conservative lexer does not model JS lexical scopes, overloads, dynamic
    dispatch or TypeScript type semantics; calls remain S0 even for one candidate.
    """
    lines, _ = _js_sources(source, jsx=path.endswith((".jsx", ".tsx")))
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
        for match in _JS_CALL.finditer(line):
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


_NIX_DIRECT_IMPORT = re.compile(
    r"(?<![\w.'-])import\s+(?P<ref>\.{1,2}/[A-Za-z0-9_./-]+\.nix)(?=$|[\s;,\)\]\}])"
)
_NIX_IMPORTS_START = re.compile(r"^\s*imports\s*=\s*\[")
_NIX_LIST_CONTENT = re.compile(r"\s*(?:(?:\.{1,2}/[A-Za-z0-9_./-]+\.nix)\s*)*")


def _nix_literal_edge(
    path: str, ref: str, ordinal: int, known: set[str],
) -> dict[str, Any]:
    target, status, options = _resolve_local(
        path, ref, known, extensions=(".nix",),
    )
    return _edge(
        "imports", "file:" + path, target, _source(path, ordinal, ordinal),
        status, "S1" if status == "resolved" else "S0", "nix_literal_import",
        candidates=options if status == "ambiguous" else None,
    )


def _nix_edges(path: str, source: str, known: set[str]) -> list[dict[str, Any]]:
    """Only lexical import arguments and plain imports-list path items are S1.

    Attribute values supplied to import, nested expressions and arbitrary
    sibling paths are not themselves imports. Complex list expressions not
    proven to consist solely of paths remain outside the S1 projection.
    """
    clean = _NIX_TRIVIA.sub(_mask, source)
    edges: list[dict[str, Any]] = []
    list_active = False
    list_lines = 0
    for ordinal, line in enumerate(clean.splitlines(), 1):
        for direct in _NIX_DIRECT_IMPORT.finditer(line):
            edges.append(_nix_literal_edge(path, direct.group("ref"), ordinal, known))
        start = _NIX_IMPORTS_START.search(line)
        if start is not None:
            list_active = True
            list_lines = 0
            content = line[start.end():]
        elif list_active:
            content = line
        else:
            continue
        # A closing bracket ends the recognized lexical list. Expressions
        # containing attribute sets, calls or nested brackets are not scanned
        # for S1 imports merely because they mention a path.
        element_text = content.split("]", 1)[0]
        if _NIX_LIST_CONTENT.fullmatch(element_text):
            for match in _NIX_LITERAL.finditer(element_text):
                edges.append(_nix_literal_edge(path, match.group("ref"), ordinal, known))
        list_lines += 1
        if "]" in content or list_lines >= 50:
            list_active = False
    return list({edge["id"]: edge for edge in edges}.values())


_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _resolve_schema_ref(
    source_path: str, ref: str, known: set[str],
) -> tuple[str, str, list[str]]:
    """Resolve exactly the URI path component, never JS extension search."""
    filename = ref.split("#", 1)[0]
    if not filename:
        return "contract-pointer:" + source_path + ref, "unresolved", []
    if (
        _URI_SCHEME.match(filename)
        or filename.startswith("/")
        or "\\" in filename
        or "%" in filename
        or "\x00" in filename
        or "?" in filename
    ):
        return "schema-ref:" + ref, "unresolved", []
    basedir = str(PurePosixPath(source_path).parent)
    resolved = posixpath.normpath(posixpath.join(basedir, filename))
    if resolved.startswith(("../", "/")) or resolved == "..":
        return "schema-ref:" + ref, "unresolved", []
    candidate = "file:" + resolved
    if candidate in known:
        return candidate, "resolved", [candidate]
    return "schema-ref:" + ref, "unresolved", []


def _schema_has_id_scope(value: Any) -> bool:
    """Any nested $id may rebase refs; S1 requires modeled URI scope."""
    remaining = [value]
    while remaining:
        entry = remaining.pop()
        if isinstance(entry, dict):
            if "$id" in entry:
                return True
            remaining.extend(entry.values())
        elif isinstance(entry, list):
            remaining.extend(entry)
    return False


_SCHEMA_SINGLE = frozenset({
    "not", "items", "additionalItems", "additionalProperties", "contains",
    "propertyNames", "if", "then", "else", "unevaluatedItems",
    "unevaluatedProperties", "contentSchema",
})
_SCHEMA_MAP = frozenset({
    "properties", "patternProperties", "$defs", "definitions", "dependentSchemas",
})
_SCHEMA_LIST = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})


def _schema_ref_counts(schema: Any) -> Counter[str]:
    """Only schema-valued locations can prove a JSON Schema $ref declaration."""
    refs: Counter[str] = Counter()
    pending = [schema]
    seen = 0
    while pending and seen < 10000:
        entry = pending.pop()
        seen += 1
        if not isinstance(entry, dict):
            continue
        ref = entry.get("$ref")
        if isinstance(ref, str):
            refs[ref] += 1
        for key, value in entry.items():
            if key in _SCHEMA_SINGLE:
                pending.append(value)
            elif key in _SCHEMA_LIST and isinstance(value, list):
                pending.extend(value)
            elif key in _SCHEMA_MAP and isinstance(value, dict):
                pending.extend(value.values())
    return refs if not pending else Counter()


def _json_edges(path: str, source: str, known: set[str]) -> list[dict[str, Any]]:
    try:
        schema = json.loads(source)
    except (ValueError, RecursionError):
        return []
    has_id_scope = _schema_has_id_scope(schema)
    # A textual $ref inside default/const/examples is instance data, not
    # a schema declaration. Ambiguous repeated spellings stay S0.
    lexical = [
        (match, json.loads('"' + match.group("ref") + '"'))
        for match in _JSON_REF.finditer(source)
    ]
    counts = Counter(ref for _, ref in lexical)
    schema_counts = _schema_ref_counts(schema)
    result: list[dict[str, Any]] = []
    for match, ref in lexical:
        if not isinstance(ref, str) or not ref:
            continue
        file_ref = ref.split("#", 1)[0]
        if not file_ref:
            target, status, candidates = "contract-pointer:" + path + ref, "unresolved", []
        else:
            target, status, candidates = _resolve_schema_ref(path, ref, known)
        proven_location = (
            schema_counts[ref] > 0 and schema_counts[ref] == counts[ref]
        )
        if status == "resolved" and (has_id_scope or not proven_location):
            candidates = [target]
            target, status = "schema-ref:" + ref, "unresolved"
        line = source.count("\n", 0, match.start()) + 1
        result.append(_edge(
            "declares_contract", "file:" + path, target, _source(path, line, line),
            status, "S1" if status == "resolved" else "S0", "json_schema_declared_ref",
            candidates=candidates if status in {"ambiguous", "unresolved"} else None,
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



def _read_declared_source(
    repo_root: Path,
    name: str,
    root_resolved: Path,
    bytes_read: int,
    max_total_bytes: int,
) -> tuple[str | None, int, str | None]:
    """Read one inventory file with the existing symlink and byte-budget guards."""
    target = repo_root / name
    try:
        if target.is_symlink() or not target.resolve().is_relative_to(root_resolved):
            return None, 0, "symlink_or_outside_repo"
        size = target.stat().st_size
        if size > MAX_SOURCE_BYTES or bytes_read + size > max_total_bytes:
            return None, 0, "source_byte_limit"
        data = target.read_bytes()
        if len(data) != size:
            return None, 0, "source_changed_during_read"
        return data.decode("utf-8"), size, None
    except (OSError, UnicodeDecodeError):
        return None, 0, "unreadable_source"

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
        source, source_size, skip_reason = _read_declared_source(
            repo_root, name, root_resolved, bytes_read, max_total_bytes,
        )
        if skip_reason is not None:
            skipped[skip_reason] += 1
            continue
        assert source is not None
        bytes_read += source_size
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