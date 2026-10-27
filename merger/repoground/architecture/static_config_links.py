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
    r"^(?P<indent>[ \t]*)(?:-[ \t]+)?[a-zA-Z_][\w.-]*:[ \t]*[|>](?:[-+][1-9]?|[1-9][-+]?)?[ \t]*(?:#.*)?$"
)
_YAML_PARENT = re.compile(
    r"^[ \t]*(?P<key>[A-Za-z_][\w.-]*):[ \t]*(?:#.*)?$"
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


def _without_inline_code(line: str) -> str:
    """Mask paired Markdown inline code; unclosed spans suppress the whole line."""
    output = list(line)
    marker = chr(96)
    index = 0
    while index < len(line):
        if line[index] != marker:
            index += 1
            continue
        width = 1
        while index + width < len(line) and line[index + width] == marker:
            width += 1
        terminator = marker * width
        close = line.find(terminator, index + width)
        if close < 0:
            return ""
        stop = close + width
        output[index:stop] = list(_mask_span(line[index:stop]))
        index = stop
    return "".join(output)


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


def _markdown_edges(path: str, source: str, known: set[str]) -> list[dict[str, Any]]:
    sanitized = _MD_COMMENT.sub(lambda m: _mask_span(m.group(0)), source)
    edges: list[dict[str, Any]] = []
    fenced: tuple[str, int] | None = None
    in_html_code = False
    for ordinal, line in enumerate(sanitized.splitlines(), 1):
        if _markdown_indented_code(line):
            continue
        if "<pre" in line or "<code" in line:
            in_html_code = True
        if in_html_code:
            if "</pre>" in line or "</code>" in line:
                in_html_code = False
            continue
        fence = _MD_FENCE.match(line)
        if fenced is not None:
            if fence is not None:
                marks = fence.group("marks")
                if marks[0] == fenced[0] and len(marks) >= fenced[1]:
                    fenced = None
            continue
        if fence is not None:
            marks = fence.group("marks")
            fenced = marks[0], len(marks)
            continue
        visible = _without_inline_code(line)
        for match in _MD_LINK.finditer(visible):
            ref = match.group("ref").removeprefix("<").removesuffix(">")
            if ref.startswith(("#", "/", "//")) or _URL_SCHEME.match(ref):
                continue
            edges.append(_reference(
                path, ref, ordinal, known, artifact="markdown_literal_link",
            ))
    return edges


def _yaml_uses_edges(path: str, source: str, known: set[str]) -> list[dict[str, Any]]:
    """Parse explicit workflow/action metadata use fields, not YAML scalar text."""
    if not (
        path.startswith(".github/workflows/")
        or path.endswith("/action.yml") or path.endswith("/action.yaml")
    ):
        return []
    edges: list[dict[str, Any]] = []
    blocked_indent: int | None = None
    context: list[tuple[int, str]] = []
    for ordinal, line in enumerate(source.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        if blocked_indent is not None:
            if indent > blocked_indent:
                continue
            blocked_indent = None
        while context and context[-1][0] >= indent:
            context.pop()
        block = _YAML_BLOCK.match(line)
        if block is not None:
            blocked_indent = len(block.group("indent"))
            continue
        parent = _YAML_PARENT.match(line)
        if parent is not None:
            context.append((indent, parent.group("key")))
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
            and path.endswith(("/action.yml", "/action.yaml"))
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
            metadata = [
                "file:" + directory + "/" + suffix
                for suffix in ("action.yml", "action.yaml")
                if "file:" + directory + "/" + suffix in known
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