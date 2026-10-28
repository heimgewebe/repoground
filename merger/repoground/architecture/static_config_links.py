"""Conservative lexical file/config references for the existing relationship graph.

Only known, literal repository files are S1. Runtime-dependent shell paths,
systemd unit names, Caddy imports and external Actions remain S0. Neither
these declarations nor their presence establishes deployment or execution.
"""
from __future__ import annotations

import posixpath
import re
from pathlib import PurePosixPath
from typing import Any

from merger.repoground.architecture.relationship_projection import _edge, _source

_MD_LINK = re.compile(
    r"""!?\[[^\]\n]{1,200}\]\(\s*(?P<ref><[^>\n]{1,240}>|[^()\s]{1,240})(?:\s+"[^"\n]{0,80}")?\s*\)"""
)
_MD_FENCE = re.compile(r"^ {0,3}(?P<marks>\x60{3,}|~{3,})(?:[^\n]*)$")
_MD_COMMENT = re.compile(r"<!--[\s\S]*?(?:-->|$)")
_YAML_USES = re.compile(
    r"""^[ \t]*(?:-[ \t]+)?uses:[ \t]*(?P<value>"[^"\n]+"|'[^'\n]+'|[^\s#]+)[ \t]*(?:#.*)?$"""
)
_YAML_BLOCK = re.compile(
    r"""^(?P<indent>[ \t]*)(?P<prefix>-[ \t]+)?(?:[a-zA-Z_][\w.-]*|"[a-zA-Z_][\w.-]*"|'[a-zA-Z_][\w.-]*'):[ \t]*[|>](?:[-+][1-9]?|[1-9][-+]?)?[ \t]*(?:#.*)?$"""
)
_YAML_PARENT = re.compile(
    r"""^[ \t]*(?P<prefix>-[ \t]+)?(?P<key>[A-Za-z_][\w.-]*|"[A-Za-z_][\w.-]*"|'[A-Za-z_][\w.-]*'):[ \t]*(?:&[A-Za-z0-9_-]+[ \t]*)?(?:#.*)?$"""
)
_YAML_QUOTED_VALUE = re.compile(
    r"""^[ \t]*(?:-[ \t]+)?(?:[A-Za-z_][\w.-]*|"[A-Za-z_][\w.-]*"|'[A-Za-z_][\w.-]*'):[ \t]*(?P<quote>["'])"""
)

_SHELL_SOURCE = re.compile(
    r"""^\s*(?:source|\.)\s+(?P<ref>\.{1,2}/[A-Za-z0-9_./+-]+)(?:\s*(?:#.*)?)?$"""
)
_CADDY_IMPORT = re.compile(r"^[ \t]*import[ \t]+(?P<ref>[^\s#{}]{1,240})(?:[ \t]|$)")
_SYSTEMD_SECTION = re.compile(r"^[ \t]*\[(?P<section>[A-Za-z]+)\][ \t]*$")
_SYSTEMD_UNIT_REF = re.compile(r"^[A-Za-z0-9_.@:-]+\.(?:service|socket|timer|target|path)$")
_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_UNIT_SUFFIXES = {".service", ".socket", ".target", ".timer", ".path"}


def _mask_span(text: str) -> str:
    return "".join("\n" if char == "\n" else " " for char in text)


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
        if raw.startswith("$/"):
            raw = raw[2:]
        elif raw.startswith("./"):
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


def _without_inline_code(paragraph: str) -> str:
    """Mask only paired exact-width backtick spans within one prose paragraph.

    An unmatched backtick is literal CommonMark text and must not hide links.
    Matching positions are calculated backwards, bounded linearly by source size.
    """
    marker = chr(96)
    runs: list[tuple[int, int]] = []
    index = 0
    while index < len(paragraph):
        start = paragraph.find(marker, index)
        if start < 0:
            break
        end = start + 1
        while end < len(paragraph) and paragraph[end] == marker:
            end += 1
        runs.append((start, end))
        index = end

    next_run: list[int | None] = [None] * len(runs)
    following: dict[int, int] = {}
    for index in range(len(runs) - 1, -1, -1):
        start, end = runs[index]
        width = end - start
        next_run[index] = following.get(width)
        following[width] = index

    visible = list(paragraph)
    index = 0
    while index < len(runs):
        if _escaped_markdown_opener(paragraph, runs[index][0]):
            index += 1
            continue
        closing = next_run[index]
        if closing is None:
            index += 1
            continue
        for position in range(runs[index][0], runs[closing][1]):
            if visible[position] != "\n":
                visible[position] = " "
        index = closing + 1
    return "".join(visible)


def _markdown_indented_code(line: str) -> bool:
    """Exclude possible CommonMark indented code, even in ambiguous lists.

    A tab stops at the next multiple of four columns; skipping ambiguous
    nested-list content favors a missed link over a false proven S1 edge.
    """
    columns = 0
    for char in line:
        if char == " ":
            columns += 1
        elif char == "\t":
            columns += 4 - columns % 4
        else:
            break
        if columns >= 4:
            return True
    return False


def _escaped_markdown_opener(text: str, start: int) -> bool:
    """Odd backslash parity escapes Markdown links or image openers."""
    count = 0
    while start > count and text[start - count - 1] == "\\":
        count += 1
    return count % 2 == 1


_MD_QUOTE_PREFIX = re.compile(r"^ {0,3}>[ \\t]?")


def _markdown_quote_info(line: str) -> tuple[str, int]:
    """Peel CommonMark blockquotes and retain their enclosing depth."""
    content = line
    depth = 0
    while (prefix := _MD_QUOTE_PREFIX.match(content)) is not None:
        content = content[prefix.end():]
        depth += 1
    return content, depth


def _markdown_prose_edges(
    path: str, lines: list[tuple[int, str]], known: set[str],
) -> list[dict[str, Any]]:
    """Only this contiguous, unfenced paragraph can pair inline code markers."""
    if not lines:
        return []
    visible = _without_inline_code("\n".join(line for _, line in lines))
    edges: list[dict[str, Any]] = []
    for (ordinal, _), line in zip(lines, visible.split("\n"), strict=True):
        for match in _MD_LINK.finditer(line):
            if _escaped_markdown_opener(line, match.start()):
                continue
            ref = match.group("ref").removeprefix("<").removesuffix(">")
            if ref.startswith(("#", "/", "//")) or _URL_SCHEME.match(ref):
                continue
            edges.append(_reference(
                path, ref, ordinal, known, artifact="markdown_literal_link",
            ))
    return edges


_MD_LIST_FENCE_PREFIX = re.compile(
    r"^ {0,3}(?:[-+*]|[0-9]{1,9}[.)])[ \\t]{1,4}(?![ \\t])"
)


def _markdown_fence_text(
    content: str, list_indent: int | None = None,
) -> tuple[str, int | None]:
    """Remove only a real list-item marker or matching container indentation."""
    if list_indent is not None:
        return (
            content[list_indent:] if content.startswith(" " * list_indent) else content,
            list_indent,
        )
    match = _MD_LIST_FENCE_PREFIX.match(content)
    if match is not None:
        return content[match.end():], match.end()
    return content, None


def _markdown_fence_continues(
    content: str, quote_depth: int,
    fenced: tuple[str, int, int | None, int],
) -> bool:
    """An unclosed fence ends when its quote or list container ends."""
    if quote_depth < fenced[3]:
        return False
    list_indent = fenced[2]
    return (
        list_indent is None
        or not content.strip()
        or content.startswith(" " * list_indent)
    )


def _markdown_backtick_pairs(
    line: str,
) -> tuple[list[tuple[int, int]], list[int | None]]:
    """Find exact-width backtick closures once, before linear prose scanning."""
    runs = [(match.start(), match.end())
            for match in re.finditer(r"`+", line)]
    following: dict[int, int] = {}
    next_run: list[int | None] = [None] * len(runs)
    for index in range(len(runs) - 1, -1, -1):
        width = runs[index][1] - runs[index][0]
        next_run[index] = following.get(width)
        following[width] = index
    return runs, next_run


def _next_markdown_comment_tokens(
    runs: list[tuple[int, int]], openings: list[int],
    cursor: int, run_index: int, comment_index: int, size: int,
) -> tuple[int, int, int, int]:
    """Advance past already consumed tokens; each index only moves forward."""
    while run_index < len(runs) and runs[run_index][0] < cursor:
        run_index += 1
    while comment_index < len(openings) and openings[comment_index] < cursor:
        comment_index += 1
    next_tick = runs[run_index][0] if run_index < len(runs) else size
    next_comment = openings[comment_index] if comment_index < len(openings) else size
    return run_index, comment_index, next_tick, next_comment


def _mask_markdown_comment_line(
    line: str, comment_open: bool,
) -> tuple[str, bool]:
    """One bounded forward pass over comments and exact-width inline code.

    A comment beginning before a backtick span hides its internal backticks;
    paired backticks beginning first hide literal HTML-comment-looking text.
    """
    chars = list(line)
    cursor = 0
    if comment_open:
        closing = line.find("-->")
        if closing < 0:
            return _mask_span(line), True
        chars[:closing + 3] = " " * (closing + 3)
        cursor = closing + 3
    runs, partners = _markdown_backtick_pairs(line)
    openings = [match.start() for match in re.finditer("<!--", line)]
    run_index = 0
    comment_index = 0
    while True:
        run_index, comment_index, next_tick, next_comment = (
            _next_markdown_comment_tokens(
                runs, openings, cursor, run_index, comment_index, len(line),
            )
        )
        if next_tick == next_comment == len(line):
            break
        if next_comment < next_tick:
            closing = line.find("-->", next_comment + 4)
            if closing < 0:
                chars[next_comment:] = " " * (len(line) - next_comment)
                return "".join(chars), True
            chars[next_comment:closing + 3] = " " * (closing + 3 - next_comment)
            cursor = closing + 3
            continue
        partner = partners[run_index]
        if partner is not None and not _escaped_markdown_opener(
            line, runs[run_index][0],
        ):
            cursor = runs[partner][1]
            run_index = partner + 1
        else:
            cursor = runs[run_index][1]
            run_index += 1
    return "".join(chars), False


def _markdown_mask_html_comments(source: str) -> str:
    """Preserve fences when HTML comment syntax is literal code content."""
    masked: list[str] = []
    fenced: tuple[str, int, int | None, int] | None = None
    comment_open = False
    for raw in source.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        ending = raw[len(line):]
        if comment_open:
            clean, comment_open = _mask_markdown_comment_line(line, True)
            masked.append(clean + ending)
            continue
        content, quote_depth = _markdown_quote_info(line)
        if fenced is not None and not _markdown_fence_continues(
            content, quote_depth, fenced,
        ):
            fenced = None
        if fenced is not None:
            candidate, _ = _markdown_fence_text(content, fenced[2])
            closing = _MD_FENCE.match(candidate)
            if closing is not None:
                marks = closing.group("marks")
                if (marks[0] == fenced[0] and len(marks) >= fenced[1]
                        and not candidate[closing.end("marks"):].strip()):
                    fenced = None
            masked.append(raw)
            continue
        candidate, indent = _markdown_fence_text(content)
        opening = _MD_FENCE.match(candidate)
        if opening is not None:
            marks = opening.group("marks")
            fenced = marks[0], len(marks), indent, quote_depth
            masked.append(raw)
            continue
        clean, comment_open = _mask_markdown_comment_line(line, False)
        masked.append(clean + ending)
    return "".join(masked)


_MD_HTML_CODE_TAG = re.compile(
    r"<(?P<closing>/)?(?P<tag>code|pre)\b[^>]*>", flags=re.IGNORECASE,
)


def _mask_markdown_html_code(
    line: str, active_tag: str | None,
) -> tuple[str, str | None]:
    """Hide only HTML code containers, preserving prose around closed spans."""
    # A tag rendered inside Markdown backticks is literal documentation.
    visible = _without_inline_code(line)
    chars = list(line)
    cursor = 0
    for tag in _MD_HTML_CODE_TAG.finditer(visible):
        name = tag.group("tag").lower()
        if active_tag is None:
            if tag.group("closing"):
                continue
            active_tag = name
            cursor = tag.start()
        if active_tag is not None:
            chars[cursor:tag.end()] = " " * (tag.end() - cursor)
            if tag.group("closing") and name == active_tag:
                active_tag = None
        cursor = tag.end()
    if active_tag is not None:
        chars[cursor:] = " " * (len(chars) - cursor)
    return "".join(chars), active_tag


def _markdown_edges(path: str, source: str, known: set[str]) -> list[dict[str, Any]]:
    sanitized = _markdown_mask_html_comments(source)
    edges: list[dict[str, Any]] = []
    fenced: tuple[str, int, int | None, int] | None = None
    html_code_tag: str | None = None
    paragraph: list[tuple[int, str]] = []
    for ordinal, (raw_line, line) in enumerate(
        zip(source.splitlines(), sanitized.splitlines(), strict=True), 1,
    ):
        content, quote_depth = _markdown_quote_info(line)
        raw_content, _ = _markdown_quote_info(raw_line)
        if fenced is not None and not _markdown_fence_continues(
            content, quote_depth, fenced,
        ):
            fenced = None
        if fenced is not None:
            edges.extend(_markdown_prose_edges(path, paragraph, known))
            paragraph.clear()
            candidate, _ = _markdown_fence_text(content, fenced[2])
            closing = _MD_FENCE.match(candidate)
            if closing is not None:
                marks = closing.group("marks")
                if (marks[0] == fenced[0] and len(marks) >= fenced[1]
                        and not candidate[closing.end("marks"):].strip()):
                    fenced = None
            continue
        # Masked comments turn into spaces, not Markdown indentation.
        if _markdown_indented_code(raw_line) or _markdown_indented_code(raw_content):
            edges.extend(_markdown_prose_edges(path, paragraph, known))
            paragraph.clear()
            continue
        if html_code_tag is not None:
            # HTML code can end mid-line; links after its closing tag count.
            prose, html_code_tag = _mask_markdown_html_code(line, html_code_tag)
            if prose.strip():
                paragraph.append((ordinal, prose))
            else:
                edges.extend(_markdown_prose_edges(path, paragraph, known))
                paragraph.clear()
            continue
        candidate, list_indent = _markdown_fence_text(content)
        opener = _MD_FENCE.match(candidate)
        if opener is not None:
            edges.extend(_markdown_prose_edges(path, paragraph, known))
            paragraph.clear()
            marks = opener.group("marks")
            fenced = marks[0], len(marks), list_indent, quote_depth
            continue
        # HTML code spans mask only their own text and tags, not nearby prose.
        # Backtick code is masked while recognizing tags so literal examples
        # cannot accidentally open an HTML code container.
        prose, html_code_tag = _mask_markdown_html_code(line, html_code_tag)
        if not prose.strip():
            edges.extend(_markdown_prose_edges(path, paragraph, known))
            paragraph.clear()
            continue
        paragraph.append((ordinal, prose))
    edges.extend(_markdown_prose_edges(path, paragraph, known))
    return edges


def _yaml_quote_continues(line: str, quote: str, start: int = 0) -> bool:
    """Detect a YAML quoted scalar that has not yet closed on this line."""
    index = start
    while index < len(line):
        if quote == '"' and line[index] == "\\":
            index += 2
        elif line[index] == quote:
            if quote == "'" and line[index:index + 2] == "''":
                index += 2
            else:
                return False
        else:
            index += 1
    return True


def _yaml_uses_edges(path: str, source: str, known: set[str]) -> list[dict[str, Any]]:
    """Parse explicit workflow/action metadata use fields, not YAML scalar text."""
    if not (
        path.startswith(".github/workflows/")
        or PurePosixPath(path).name in {"action.yml", "action.yaml"}
    ):
        return []
    edges: list[dict[str, Any]] = []
    blocked_indent: int | None = None
    quoted_scalar: str | None = None
    context: list[tuple[int, str]] = []
    for ordinal, line in enumerate(source.splitlines(), 1):
        if quoted_scalar is not None:
            if not _yaml_quote_continues(line, quoted_scalar):
                quoted_scalar = None
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        if blocked_indent is not None:
            if indent > blocked_indent:
                continue
            blocked_indent = None
        indentless_step = line.lstrip().startswith(("- ", "-\t"))
        while context and (
            context[-1][0] > indent
            or (context[-1][0] == indent and not (
                indentless_step and context[-1][1] == "steps"
            ))
        ):
            context.pop()
        block = _YAML_BLOCK.match(line)
        if block is not None:
            blocked_indent = len(block.group("indent")) + len(block.group("prefix") or "")
            continue
        quoted = _YAML_QUOTED_VALUE.match(line)
        if quoted is not None and _yaml_quote_continues(
            line, quoted.group("quote"), quoted.end(),
        ):
            quoted_scalar = quoted.group("quote")
            continue
        parent = _YAML_PARENT.match(line)
        if parent is not None:
            context.append((indent + len(parent.group("prefix") or ""), parent.group("key").strip("'\"")))
            continue
        match = _YAML_USES.match(line)
        if match is None:
            continue
        # A workflow job uses a reusable workflow directly under jobs.<id>.
        # A step uses an action only under a literal steps list. We refuse
        # env/with/metadata text that happens to contain a 'uses' mapping key.
        job_use = (
            len(context) == 2 and context[0][1] == "jobs"
            and path.startswith(".github/workflows/")
        )
        workflow_step = (
            len(context) == 3 and context[0][1] == "jobs"
            and context[-1][1] == "steps"
            and path.startswith(".github/workflows/")
        )
        composite_step = (
            len(context) == 2 and context[0][1] == "runs"
            and context[-1][1] == "steps"
            and PurePosixPath(path).name in {"action.yml", "action.yaml"}
        )
        if not (job_use or workflow_step or composite_step):
            continue
        ref = match.group("value").strip("'\"")
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
                continue
            # Step uses expects an action DIRECTORY containing metadata.
            # Pointing directly at a workflow .yml is not a proven action
            # dependency, even when that YAML file exists in the inventory.
            directory = ref[2:].rstrip("/")
            metadata_prefix = directory + "/" if directory else ""
            metadata = [
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
    """Pure lexical extension; never scans paths or calls another graph producer."""
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