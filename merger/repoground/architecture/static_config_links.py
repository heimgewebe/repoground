"""Conservative file/config references for the existing relationship graph.

Only known, literal repository files are S1. Runtime-dependent shell paths,
systemd unit names, Caddy imports and external Actions remain S0. Neither
these declarations nor their presence establishes deployment or execution.
"""
from __future__ import annotations

import posixpath
import re
from bisect import bisect_right
from html.parser import HTMLParser
from itertools import accumulate
from pathlib import PurePosixPath
from typing import Any

from merger.repoground.architecture.relationship_projection import _edge, _source

_SHELL_SOURCE = re.compile(
    r"""^\s*(?:source|\.)\s+(?P<ref>\.{1,2}/[A-Za-z0-9_./+-]+)(?:\s*(?:#.*)?)?$"""
)
_CADDY_IMPORT = re.compile(r"^[ \t]*import[ \t]+(?P<ref>[^\s#{}]{1,240})(?:[ \t]|$)")
_SYSTEMD_SECTION = re.compile(r"^[ \t]*\[(?P<section>[A-Za-z]+)\][ \t]*$")
_SYSTEMD_UNIT_REF = re.compile(r"^[A-Za-z0-9_.@:-]+\.(?:service|socket|timer|target|path)$")
_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_UNIT_SUFFIXES = {".service", ".socket", ".target", ".timer", ".path"}


def _local_target(
    path: str,
    ref: str,
    known: set[str],
    *,
    repo_relative: bool = False,
) -> tuple[str, str, list[str]]:
    """Resolve only exact known repository paths, never speculative suffixes."""
    raw = ref.split("#", 1)[0].split("?", 1)[0].strip()
    if (
        not raw or raw.startswith(("/", "//", "#"))
        or _URL_SCHEME.match(raw)
        or "%" in raw or chr(92) in raw or chr(0) in raw
    ):
        return "module:" + ref, "unresolved", []
    if repo_relative:
        if raw.startswith(("$/", "./")):
            raw = raw[2:]
        else:
            return "module:" + ref, "unresolved", []
        candidate = posixpath.normpath(raw)
    else:
        basedir = str(PurePosixPath(path).parent)
        candidate = posixpath.normpath(posixpath.join(basedir, raw))
    if candidate in {"", ".", ".."} or candidate.startswith(("../", "/")):
        return "module:" + ref, "unresolved", []
    target = "file:" + candidate
    if target in known:
        return target, "resolved", [target]
    return "module:" + ref, "unresolved", []


def _reference(
    path: str, ref: str, line: int, known: set[str], *,
    artifact: str, repo_relative: bool = False,
) -> dict[str, Any]:
    target, status, _ = _local_target(
        path, ref, known, repo_relative=repo_relative,
    )
    return _edge(
        "references", "file:" + path, target, _source(path, line, line),
        status, "S1" if status == "resolved" else "S0", artifact,
    )


def _unproven(
    path: str, target: str, line: int, *,
    artifact: str, relation: str = "references", candidates: list[str] | None = None,
) -> dict[str, Any]:
    return _edge(
        relation, "file:" + path, target, _source(path, line, line),
        "candidate", "S0", artifact, candidates=candidates,
    )


class ConfigSourceUnavailable(ValueError):
    """A source could not be interpreted safely; preserve a coverage gap."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _MarkdownLines:
    """Bind native CommonMark tokens to RepoGround's splitlines source ranges."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.rows = source.split("\n")
        self.starts = list(accumulate(
            (len(row) + 1 for row in self.rows), initial=0,
        ))[:-1]
        self.canonical = list(accumulate(
            (len(row) for row in source.splitlines(keepends=True)), initial=0,
        ))[:-1]

    def bind(self, parent: Any) -> None:
        self.parent = parent
        self.content_rows = parent.content.split("\n")
        self.content_starts = list(accumulate(
            (len(row) + 1 for row in self.content_rows), initial=0,
        ))[:-1]
        self.bound: dict[int, int | None] = {}

    def _bind_row(self, row: int) -> int | None:
        if len(self.content_rows) != self.parent.map[1] - self.parent.map[0]:
            return None
        original = self.parent.map[0] + row
        if not 0 <= original < len(self.rows):
            return None
        content = self.content_rows[row]
        # Container stripping can expand leading tabs to virtual spaces.
        needle = content.lstrip(" \t")
        if not needle:
            return None
        raw = self.rows[original]
        offset = raw.find(needle)
        if offset < 0 or raw.find(needle, offset + 1) >= 0:
            return None
        return self.starts[original] + offset - (len(content) - len(needle))

    def _ordinal(self, position: int) -> int | None:
        if not 0 <= position < len(self.parent.content):
            return None
        row = bisect_right(self.content_starts, position) - 1
        if row not in self.bound:
            self.bound[row] = self._bind_row(row)
        origin = self.bound[row]
        if origin is None:
            return None
        absolute = origin + position - self.content_starts[row]
        if not 0 <= absolute < len(self.source):
            return None
        return bisect_right(self.canonical, absolute)

    def span(self, start: int, end: int) -> tuple[int, int]:
        first, last = self._ordinal(start), self._ordinal(end - 1)
        if first is not None and last is not None and first <= last:
            return first, last
        # An ambiguous point mapping retains the proven enclosing range.
        begin, finish = self.parent.map
        lower = self.starts[begin]
        upper = (
            self.starts[finish] if finish < len(self.starts)
            else len(self.source)
        ) - 1
        return (
            bisect_right(self.canonical, lower),
            bisect_right(self.canonical, max(lower, upper)),
        )


class _MarkdownHtmlContext(HTMLParser):
    """Consume only native HTML tokens, never mask raw Markdown source."""

    LITERAL = frozenset({"code", "pre", "script", "style", "textarea"})
    RAW_TEXT = frozenset({"script", "style", "textarea"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.literal: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if self.literal and self.literal[-1] in self.RAW_TEXT:
            return
        if tag in self.LITERAL:
            self.literal.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.literal and self.literal[-1] == tag:
            self.literal.pop()

    def handle_startendtag(self, tag: str, attrs: Any) -> None:
        self.handle_starttag(tag, attrs)

    def consume(self, token: Any) -> None:
        # Native HTML blocks cannot introduce our inline-only context.
        if token.type == "html_inline" or self.literal:
            self.feed(token.content)
        if not self.literal:
            self.reset()


def _marked_markdown_rule(rule: Any, token_type: str) -> Any:
    def marked(state: Any, silent: bool) -> bool:
        start, count = state.pos, len(state.tokens)
        matched = rule(state, silent)
        if matched and not silent:
            # state.push() may first flush pending text.
            for token in state.tokens[count:]:
                if token.type == token_type:
                    token.meta["repoground_span"] = (start, state.pos)
                    break
        return matched
    return marked


def _markdown_link_edge(
    path: str, token: Any, known: set[str], lines: _MarkdownLines,
) -> dict[str, Any] | None:
    span = token.meta.get("repoground_span")
    if span is None or "label" in token.meta:
        return None
    ref = token.attrGet("src" if token.type == "image" else "href")
    if not ref or len(ref) > 240:
        return None
    if ref.startswith(("#", "/", "//")) or _URL_SCHEME.match(ref):
        return None
    first, last = lines.span(*span)
    target, status, _ = _local_target(path, ref, known)
    return _edge(
        "references", "file:" + path, target, _source(path, first, last),
        status, "S1" if status == "resolved" else "S0",
        "markdown_literal_link",
    )


def _markdown_parser() -> Any:
    try:
        from markdown_it import MarkdownIt
        from markdown_it.rules_inline.image import image
        from markdown_it.rules_inline.link import link
    except ImportError as exc:
        raise ConfigSourceUnavailable("markdown_parser_unavailable") from exc
    parser = MarkdownIt("commonmark", {"html": True, "store_labels": True})
    parser.inline.ruler.at("link", _marked_markdown_rule(link, "link_open"))
    parser.inline.ruler.at("image", _marked_markdown_rule(image, "image"))
    return parser


def _markdown_edges(
    path: str, source: str, known: set[str],
) -> list[dict[str, Any]]:
    # Match CommonMark normalization; other Unicode separators stay literal.
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\0", "\ufffd")
    lines = _MarkdownLines(normalized)
    html = _MarkdownHtmlContext()
    edges: list[dict[str, Any]] = []
    try:
        tokens = _markdown_parser().parse(normalized)
    except RecursionError as exc:
        raise ConfigSourceUnavailable("markdown_nesting_limit") from exc
    for parent in tokens:
        if parent.type == "html_block":
            html.consume(parent)
        if parent.type != "inline":
            continue
        lines.bind(parent)
        # Image children are alt text, not independently rendered links.
        for token in parent.children or ():
            if token.type == "html_inline":
                html.consume(token)
            elif token.type in {"link_open", "image"} and not html.literal:
                edge = _markdown_link_edge(path, token, known, lines)
                if edge is not None:
                    edges.append(edge)
    return edges


_YAML_TAG = "tag:yaml.org,2002:"
_YAML_TAGS = frozenset(
    _YAML_TAG + kind for kind in
    ("str", "null", "bool", "int", "float", "timestamp", "binary", "map", "seq")
)


def _yaml_mapping(node: Any) -> dict[str, tuple[Any, Any]]:
    if node is None or node.id != "mapping":
        return {}
    entries: dict[str, tuple[Any, Any]] = {}
    for key, value in node.value:
        if key.id != "scalar":
            raise ConfigSourceUnavailable("yaml_complex_mapping_key")
        if key.value == "<<" or key.value in entries:
            raise ConfigSourceUnavailable("yaml_duplicate_or_merge_key")
        entries[key.value] = key, value
    return entries


def _yaml_validate_nodes(root: Any) -> None:
    """Reject unsupported tags and ambiguous keys without constructing values."""
    pending = [root] if root is not None else []
    while pending:
        node = pending.pop()
        if (
            node.tag not in _YAML_TAGS
            or (node.id == "mapping" and node.tag != _YAML_TAG + "map")
            or (node.id == "sequence" and node.tag != _YAML_TAG + "seq")
            or (node.id == "scalar" and node.tag in {
                _YAML_TAG + "map", _YAML_TAG + "seq",
            })
        ):
            raise ConfigSourceUnavailable("yaml_unsupported_tag")
        if node.id == "mapping":
            for key, value in _yaml_mapping(node).values():
                pending.extend((key, value))
        elif node.id == "sequence":
            pending.extend(node.value)


def _yaml_compose(source: str) -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise ConfigSourceUnavailable("yaml_parser_unavailable") from exc
    depth = 0
    try:
        for count, event in enumerate(yaml.parse(source, Loader=yaml.SafeLoader), 1):
            if isinstance(event, yaml.AliasEvent):
                raise ConfigSourceUnavailable("yaml_alias_provenance_unavailable")
            if isinstance(event, yaml.CollectionStartEvent):
                depth += 1
            elif isinstance(event, yaml.CollectionEndEvent):
                depth -= 1
            if depth > 64 or count > 50_000:
                raise ConfigSourceUnavailable("yaml_structure_limit")
        root = yaml.compose(source, Loader=yaml.SafeLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise ConfigSourceUnavailable("invalid_yaml") from exc
    _yaml_validate_nodes(root)
    return root


def _yaml_field(node: Any, name: str) -> Any:
    entry = _yaml_mapping(node).get(name)
    if entry is None or entry[0].tag != _YAML_TAG + "str":
        return None
    return entry[1]


def _yaml_node_use_edges(
    path: str, node: Any, known: set[str], *, job_use: bool = False,
) -> list[dict[str, Any]]:
    entry = _yaml_mapping(node).get("uses")
    if entry is None or entry[0].tag != _YAML_TAG + "str":
        return []
    key, value = entry
    if value.id != "scalar" or value.tag != _YAML_TAG + "str":
        raise ConfigSourceUnavailable("yaml_nonliteral_uses")
    first = key.start_mark.line + 1
    last = max(first, value.end_mark.line + int(value.end_mark.column > 0))
    edges = _yaml_use_edges(
        path, value.value, first, known, job_use=job_use,
    )
    if first == last:
        return edges
    return [
        _edge(
            edge["relation"], edge["src"], edge["dst"],
            _source(path, first, last), edge["resolution_status"],
            edge["evidence_level"], edge["origin_artifact"],
            candidates=edge.get("candidate_target_ids"),
        )
        for edge in edges
    ]


def _yaml_step_edges(
    path: str, steps: Any, known: set[str],
) -> list[dict[str, Any]]:
    if steps is None or steps.id != "sequence":
        return []
    return [
        edge for step in steps.value
        for edge in _yaml_node_use_edges(path, step, known)
    ]


def _yaml_uses_edges(
    path: str, source: str, known: set[str],
) -> list[dict[str, Any]]:
    """Read only real workflow/action mapping positions from composed YAML."""
    workflow = path.startswith(".github/workflows/")
    composite = PurePosixPath(path).name in {"action.yml", "action.yaml"}
    if not (workflow or composite):
        return []
    root = _yaml_compose(source)
    if composite:
        return _yaml_step_edges(
            path, _yaml_field(_yaml_field(root, "runs"), "steps"), known,
        )
    edges: list[dict[str, Any]] = []
    for _, job in _yaml_mapping(_yaml_field(root, "jobs")).values():
        edges.extend(_yaml_node_use_edges(path, job, known, job_use=True))
        edges.extend(_yaml_step_edges(path, _yaml_field(job, "steps"), known))
    return edges


def _yaml_use_edges(
    path: str, ref: str, ordinal: int, known: set[str], *, job_use: bool = False,
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    if ref.startswith(("./", "$/")):
        target, status, _ = _local_target(
            path, ref, known, repo_relative=True,
        )
        if job_use:
            # Job-level uses accepts a reusable workflow FILE, never
            # a local action metadata directory. The prefix is an
            # Actions syntax constraint, not runtime execution proof.
            relative = ref[2:]
            valid_workflow = (
                relative.startswith(".github/workflows/")
                and PurePosixPath(relative).suffix in {".yml", ".yaml"}
            )
            if valid_workflow and status == "resolved":
                edges.append(_reference(
                    path, ref, ordinal, known,
                    artifact="github_actions_reusable_workflow_file",
                    repo_relative=True,
                ))
            else:
                edges.append(_unproven(
                    path, "module:" + ref, ordinal,
                    artifact="github_actions_job_uses_unproven",
                    candidates=[target] if status == "resolved" else None,
                ))
            return edges
        # Step uses expects an action DIRECTORY containing metadata.
        # Pointing directly at a workflow .yml is not a proven action
        # dependency, even when that YAML file exists in the inventory.
        raw_directory = ref[2:].rstrip("/")
        directory = posixpath.normpath(raw_directory)
        safe_directory = not (
            directory == ".." or directory.startswith(("../", "/")) or "%" in raw_directory
            or chr(92) in raw_directory or chr(0) in raw_directory
        )
        if directory == ".":
            directory = ""
        metadata_prefix = directory + "/" if directory else ""
        metadata = [] if not safe_directory else [
            "file:" + metadata_prefix + suffix
            for suffix in ("action.yml", "action.yaml")
            if "file:" + metadata_prefix + suffix in known
        ]
        if len(metadata) == 1:
            edges.append(_edge(
                "references", "file:" + path, metadata[0],
                _source(path, ordinal, ordinal), "resolved", "S1",
                "github_actions_local_action_metadata",
            ))
        elif len(metadata) > 1:
            edges.append(_unproven(
                path, "module:" + ref, ordinal,
                artifact="github_actions_ambiguous_action_metadata",
                candidates=metadata,
            ))
        else:
            edges.append(_unproven(
                path, "module:" + ref, ordinal,
                artifact="github_actions_step_uses_unproven",
                candidates=[target] if status == "resolved" else None,
            ))
    elif ref and "$" not in ref and "\x00" not in ref:
        edges.append(_unproven(
            path, "external-action:" + ref, ordinal,
            artifact="github_actions_external_uses",
        ))
    return edges


def _systemd_edges(path: str, source: str) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    section: str | None = None
    seen_section = False
    for ordinal, line in enumerate(source.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        found = _SYSTEMD_SECTION.fullmatch(line)
        if found is not None:
            section = found.group("section")
            seen_section = True
            continue
        if section != "Unit" or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key not in {"Requires", "Wants", "After", "Before", "BindsTo", "PartOf"}:
            continue
        for name in value.split():
            if _SYSTEMD_UNIT_REF.fullmatch(name):
                edges.append(_unproven(
                    path, "declared-unit:" + name, ordinal,
                    artifact="systemd_declared_unit_reference",
                ))
    if seen_section:
        edges.append(_unproven(
            path, "declared-unit:" + PurePosixPath(path).name, 1,
            artifact="systemd_unit_config_file",
            relation="configures_service",
        ))
    return edges


def _shell_edges(path: str, source: str, known: set[str]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for ordinal, line in enumerate(source.splitlines(), 1):
        match = _SHELL_SOURCE.fullmatch(line)
        if match is None:
            continue
        ref = match.group("ref")
        _, status, known_candidates = _local_target(path, ref, known)
        edges.append(_unproven(
            path, "module:" + ref, ordinal,
            artifact="shell_relative_source_cwd_unproven",
            candidates=known_candidates if status == "resolved" else None,
        ))
    return edges


def _caddy_edges(path: str, source: str, known: set[str]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for ordinal, line in enumerate(source.splitlines(), 1):
        line = line.split("#", 1)[0]
        match = _CADDY_IMPORT.match(line)
        if match is None:
            continue
        ref = match.group("ref")
        _, status, known_candidates = _local_target(path, ref, known)
        edges.append(_unproven(
            path, "declared-config-import:" + ref, ordinal,
            artifact="caddy_import_snippet_or_file_unproven",
            candidates=known_candidates if status == "resolved" else None,
        ))
    return edges


def config_reference_edges(
    path: str, source: str, known: set[str],
) -> list[dict[str, Any]]:
    """Pure source projection; never scans paths or calls another graph producer."""
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".md":
        return _markdown_edges(path, source, known)
    if suffix in {".yaml", ".yml"}:
        return _yaml_uses_edges(path, source, known)
    if suffix in _UNIT_SUFFIXES:
        return _systemd_edges(path, source)
    if suffix in {".sh", ".bash", ".zsh"}:
        return _shell_edges(path, source, known)
    if PurePosixPath(path).name == "Caddyfile" or suffix == ".caddy":
        return _caddy_edges(path, source, known)
    return []
