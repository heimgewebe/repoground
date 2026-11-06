"""Conservative cross-repository Nix Flake dependency proof from exact Git objects.

Only a literal GitHub SHA input that agrees with flake.lock and an explicitly
supplied target Git commit is promoted to S1. No Nix evaluation or runtime claim.
"""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
from pathlib import Path
from typing import Any

from merger.repoground.architecture.declared_relations import _nix_without_trivia
from .federation import _artifact_evidence, _git_object_bytes
from .history_lens import _git_tree, _repo_root, _revision

KIND = "repoground.flake-revision-relations"
VERSION = "1"
_URL = re.compile(
    r'^\s*(?P<root>inputs\.)?(?P<alias>[A-Za-z_][\w-]*)\.url\s*=\s*"github:'
    r'(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/'
    r'(?P<sha>[0-9a-f]{40})"\s*;\s*(?:#.*)?$'
)
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_MODULE = re.compile(r"\./modules/[A-Za-z0-9_.-]+\.nix")


def _literal_urls(text: str) -> tuple[dict[str, tuple[str, str, int]], list[str]]:
    """Accept only root inputs.NAME.url or direct fields of root inputs = { }.

    This intentionally excludes similarly named URLs inside arbitrary Nix
    attributes. Complex flake structures need a real Nix parser, not S1 guesses.
    """
    original = text.splitlines()
    masked = _nix_without_trivia(text).splitlines()
    found: dict[str, tuple[str, str, int]] = {}
    gaps: list[str] = []
    depth = 0
    inputs_depth: int | None = None
    for number, (line, code) in enumerate(zip(original, masked), 1):
        opening_inputs = (
            depth == 1
            and re.match(r"^\s*inputs\s*=\s*\{", code) is not None
        )
        if opening_inputs:
            inputs_depth = depth + 1
        match = _URL.fullmatch(line)
        if match is not None:
            alias = match["alias"]
            prefix = ("inputs." if match["root"] else "") + alias + ".url"
            is_direct_root_input = bool(match["root"]) and depth == 1
            is_member_of_root_inputs = (
                not match["root"] and inputs_depth is not None and depth == inputs_depth
            )
            if code.lstrip().startswith(prefix) and (
                is_direct_root_input or is_member_of_root_inputs
            ):
                if alias in found:
                    gaps.append("duplicate_flake_input:" + alias)
                    del found[alias]
                elif "duplicate_flake_input:" + alias not in gaps:
                    found[alias] = (
                        match["owner"] + "/" + match["repo"], match["sha"], number
                    )
            elif code.lstrip().startswith(prefix):
                gaps.append("flake_url_outside_root_inputs:" + alias)
        depth += code.count("{") - code.count("}")
        if inputs_depth is not None and depth < inputs_depth:
            inputs_depth = None
    return found, gaps


def _record(kind: str, src: dict[str, Any], dst: dict[str, Any],
            supporting: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "relation_type": kind, "direction": "source_to_target",
        "evidence_level": "S1", "resolution_status": "resolved",
        "source": src, "target": dst, "supporting_evidence": supporting,
        "asserts_runtime_dependency": False,
    }


def _locked_inputs(lock: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        document = json.loads(lock.decode("utf-8"))
        nodes = document["nodes"]
        root_inputs = nodes[document["root"]]["inputs"]
        if not isinstance(nodes, dict) or not isinstance(root_inputs, dict):
            raise ValueError("bad flake lock")
        return nodes, root_inputs
    except (ValueError, UnicodeError, KeyError, TypeError) as exc:
        raise ValueError("invalid flake.lock at requested Git revision") from exc


def _unsupported_input_layout(
    alias: str, source_text: str, node: dict[str, Any], locked: dict[str, Any],
) -> bool:
    """Do not bind root flake.nix for subdirectory or non-flake inputs."""
    syntax = _nix_without_trivia(source_text)
    # Our bounded lexical producer supports the root flake of an ordinary input
    # only. A declared dir or flake modifier changes input evaluation semantics.
    attr = r"(?:inputs\.)?" + re.escape(alias) + r"\.(?:dir|flake)\s*="
    if re.search(r"(?m)^\s*" + attr, syntax):
        return True
    nested = re.escape(alias) + r"\s*=\s*\{[^}]{0,2048}\b(?:dir|flake)\s*="
    if re.search(nested, syntax):
        return True
    for entry in (node, locked, node.get("original")):
        if isinstance(entry, dict) and (
            "dir" in entry or entry.get("flake") is False
        ):
            return True
    return False


def _resolved_target(
    alias: str, dependency: str, declared_sha: str,
    nodes: dict[str, Any], root_inputs: dict[str, Any],
    targets: dict[str, tuple[str | Path, str]], gaps: list[str],
    source_text: str,
) -> tuple[str, dict[str, str], bytes] | None:
    node_key = root_inputs.get(alias)
    node = nodes.get(node_key) if isinstance(node_key, str) else None
    locked = node.get("locked") if isinstance(node, dict) else None
    owner, repo = dependency.split("/", 1)
    if (
        not isinstance(locked, dict)
        or locked.get("type") != "github"
        or locked.get("owner") != owner
        or locked.get("repo") != repo
        or locked.get("rev") != declared_sha
    ):
        gaps.append("flake_lock_mismatch:" + alias)
        return None
    if _unsupported_input_layout(alias, source_text, node, locked):
        gaps.append("unsupported_flake_input_layout:" + alias)
        return None
    spec = targets.get(dependency)
    if spec is None:
        gaps.append("target_not_provided:" + dependency)
        return None
    target_root, requested_sha = spec
    if requested_sha != declared_sha or not _SHA.fullmatch(requested_sha):
        gaps.append("target_commit_mismatch:" + dependency)
        return None
    try:
        target_path = _repo_root(Path(target_root))
        target_sha = _revision(target_path, requested_sha)
        target_tree, capped = _git_tree(target_path, target_sha)
    except (ValueError, OSError):
        gaps.append("target_commit_unavailable:" + dependency)
        return None
    if capped:
        gaps.append("target_tree_capped:" + dependency)
        return None
    target_flake = _git_object_bytes(target_path, target_tree, "flake.nix")
    if target_flake is None:
        gaps.append("target_flake_unavailable:" + dependency)
        return None
    return target_sha, target_tree, target_flake



def _brace_depths(syntax: str) -> list[int]:
    """Track lexical brace nesting after Nix trivia/string masking."""
    result: list[int] = []
    depth = 0
    for char in syntax:
        result.append(depth)
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
    return result


def _let_body_opener(syntax: str, start: int) -> int:
    """Find the returned attrset of an outputs let, not a nested let value."""
    nested = 0
    for token in re.finditer(r"\blet\b|\bin\b", syntax[start:]):
        nested += 1 if token.group() == "let" else -1
        if nested == 0:
            after = start + token.end()
            # An output can be guarded by exactly one static Nix assert.
            # Refuse nested attrsets, semicolons or ambiguous expressions.
            matched = re.match(
                r"\s*(?:assert\s+[^;{}]{1,4096};\s*)?\{", syntax[after:]
            )
            return after + matched.end() - 1 if matched else -1
        if nested < 0:
            break
    return -1


def _returned_output_span(syntax: str) -> tuple[int, int] | None:
    """Bound a literal outputs attrset, excluding later sibling attrsets."""
    depths = _brace_depths(syntax)
    matches = list(re.finditer(
        r"(?m)^\s*outputs\s*=\s*\{[^{}]*\}\s*:", syntax,
    ))
    if len(matches) != 1 or depths[matches[0].start()] != 1:
        return None
    tail = matches[0].end()
    immediate = re.match(r"\s*\{", syntax[tail:])
    if immediate is not None:
        opener = tail + immediate.end() - 1
    elif re.match(r"\s*let\b", syntax[tail:]):
        opener = _let_body_opener(syntax, tail)
    else:
        return None
    if opener < 0 or depths[opener] != 1 or syntax[opener] != "{":
        return None
    closer = next(
        (i for i in range(opener + 1, len(syntax))
         if syntax[i] == "}" and depths[i] == 2),
        None,
    )
    return (opener, closer) if closer is not None else None


def _inner_host_modules_reaches_output(inner: bytes) -> bool:
    syntax = _nix_without_trivia(inner.decode("utf-8"))
    span = _returned_output_span(syntax)
    if span is None:
        return False
    body = syntax[span[0] + 1:span[1]]
    # These are the bounded, explicitly supported uses of the let-bound list.
    return bool(re.search(
        r"(?<![\w-])(?:modules\s*=\s*hostModules\b|inherit\s+hostModules\s*;)",
        body,
    ))


def _verified_output_export(target_flake: bytes) -> bool:
    """Only direct properties of the returned outputs attrset establish S1."""
    syntax = _nix_without_trivia(target_flake.decode("utf-8", errors="replace"))
    span = _returned_output_span(syntax)
    if span is None:
        return False
    depths = _brace_depths(syntax)
    for item in re.finditer(r"(?m)^[ \t]*nixosModules\.default\s*=", syntax):
        if span[0] < item.start() < span[1] and depths[item.start()] == 2:
            return True
    return False


def _verified_inner_flake(
    outer: bytes, inner: bytes, alias: str,
    dependency: str, declared_sha: str, module_flake_path: str,
) -> bool:
    """An inner same-named input is not an alias of the outer Flake by name."""
    if module_flake_path != "nixos/system/flake.nix":
        return False
    outer_syntax = _nix_without_trivia(outer.decode("utf-8"))
    depths = _brace_depths(outer_syntax)
    links = list(re.finditer(
        r"(?m)^\s*outputs\s*=\s*inputs@\{([^{}]*)\}\s*:\s*"
        r"\(import\s+\./nixos/system/flake\.nix\)\.outputs\s+inputs\s*;",
        outer_syntax,
    ))
    if len(links) != 1 or depths[links[0].start()] != 1:
        return False
    if alias not in re.findall(r"[A-Za-z_][A-Za-z0-9_-]*", links[0].group(1)):
        return False
    inner_text = inner.decode("utf-8")
    inner_urls, gaps = _literal_urls(inner_text)
    if gaps or alias not in inner_urls:
        return False
    actual_repo, actual_sha, _ = inner_urls[alias]
    if (actual_repo, actual_sha) != (dependency, declared_sha):
        return False
    inner_syntax = _nix_without_trivia(inner_text)
    # A local let-bound name shadows the passed Flake input parameter.
    # Scope-ambiguous cases remain S0 rather than a fabricated S1 link.
    if re.search(r"(?m)^[ \t]*" + re.escape(alias) + r"\s*=", inner_syntax):
        return False
    inner_depths = _brace_depths(inner_syntax)
    declarations = list(re.finditer(
        r"(?m)^\s*outputs\s*=\s*\{([^{}]*)\}\s*:", inner_syntax,
    ))
    return (
        len(declarations) == 1
        and inner_depths[declarations[0].start()] == 1
        and alias in re.findall(
            r"[A-Za-z_][A-Za-z0-9_-]*", declarations[0].group(1)
        )
    )


def _host_module_list_tokens(
    line: str, alias: str,
) -> tuple[bool, list[str]] | None:
    """Return verified alias membership independently of local module paths."""
    matched = re.fullmatch(r"\s*hostModules\s*=\s*\[([^\[\]]*)\]\s*;\s*", line)
    if matched is None:
        return None
    tokens = matched.group(1).split()
    expected = alias + ".nixosModules.default"
    if expected not in tokens:
        return False, []
    if any(
        item != expected and (
            not re.fullmatch(r"\.{1,2}/[A-Za-z0-9_./-]+", item)
            or (item.startswith("./modules/") and not _MODULE.fullmatch(item))
        )
        for item in tokens
    ):
        return None
    return True, [
        item for item in tokens
        if re.fullmatch(r"\./modules/[A-Za-z0-9_.-]+\.nix", item)
    ]


def _module_result_open(
    syntax: str, depths: list[int], tail: int,
) -> int | None:
    direct = re.match(r"\s*\{", syntax[tail:])
    if direct is not None:
        return tail + direct.end() - 1
    opening_let = re.match(r"\s*let(?![\w-])", syntax[tail:])
    if opening_let is None:
        return None
    cursor = tail + opening_let.end()
    nested = 1
    for word in re.finditer(
        r"(?<![\w-])(?:let|in)(?![\w-])", syntax[cursor:]
    ):
        position = cursor + word.start()
        if depths[position] != 0:
            continue
        nested += 1 if word.group() == "let" else -1
        if nested == 0:
            after = cursor + word.end()
            opening = re.match(r"\s*\{", syntax[after:])
            return after + opening.end() - 1 if opening is not None else None
    return None


def _module_return_scope(
    syntax: str, depths: list[int],
) -> tuple[int, int] | None:
    """Only inspect the attrset returned by a root Nix module lambda."""
    start = re.match(r"\s*\{", syntax)
    if start is None:
        return None
    lambda_close = next(
        (i for i, ch in enumerate(syntax) if ch == "}" and depths[i] == 1),
        None,
    )
    if lambda_close is None:
        return None
    colon = re.match(r"\s*:", syntax[lambda_close + 1:])
    if colon is None:
        return None
    tail = lambda_close + 1 + colon.end()
    opener = _module_result_open(syntax, depths, tail)
    if opener is None:
        return None
    if depths[opener] != 0:
        return None
    closing = next(
        (i for i in range(opener + 1, len(syntax))
         if syntax[i] == "}" and depths[i] == 1),
        None,
    )
    return (opener, closing) if closing is not None else None


def _module_service_scopes(
    syntax: str, depths: list[int],
) -> list[tuple[int, int, int]]:
    root = _module_return_scope(syntax, depths)
    if root is None:
        return []
    scopes = [(root[0], root[1], 1)]
    config = re.compile(
        r"(?m)^[ \t]*config\s*=\s*"
        r"(?:lib\.mkIf\s+[A-Za-z_][A-Za-z0-9_-]*\s*)?\{"
    )
    for match in config.finditer(syntax):
        opener = match.end() - 1
        if not root[0] < opener < root[1] or depths[match.start()] != 1:
            continue
        closing = next(
            (i for i in range(opener + 1, root[1])
             if syntax[i] == "}" and depths[i] == 2),
            None,
        )
        if closing is not None:
            scopes.append((opener, closing, 2))
    return scopes


def _declared_services(
    source_repo: str, commit: str, tree: dict[str, str],
    candidate: str, host_module: bytes,
    module_export: dict[str, Any], target_evidence: dict[str, Any],
    rows: list[dict[str, Any]], gaps: list[str],
) -> None:
    syntax = _nix_without_trivia(host_module.decode("utf-8"))
    depths = _brace_depths(syntax)
    scopes = _module_service_scopes(syntax, depths)
    for found in re.finditer(
        r"(?m)^[ \t]*(services\.nixer|systemd\.user\.services\.nixer)\s*=",
        syntax,
    ):
        if not any(
            opening < found.start() < closing and depths[found.start()] == level
            for opening, closing, level in scopes
        ):
            gaps.append("service_scope_unverified:" + candidate)
            continue
        line = syntax.count("\n", 0, found.start()) + 1
        rows.append(_record(
            "nixos_service_declaration",
            _artifact_evidence(
                source_repo, commit, candidate, tree, host_module, line,
            ),
            {"repo_id": source_repo, "commit": commit,
             "symbol": found.group(1), "status": "declared_only"},
            [module_export, target_evidence],
        ))

def _lexical_line_depths(syntax: str):
    """Yield masked Nix source lines with the depth of their first token."""
    depths = _brace_depths(syntax)
    offset = 0
    for number, line in enumerate(syntax.splitlines(keepends=True), 1):
        if line.strip():
            token = offset + len(line) - len(line.lstrip())
            at_depth = depths[token]
        else:
            at_depth = 0  # No identifier is present to attribute to a scope.
        yield number, line.rstrip("\n"), at_depth
        offset += len(line)


def _append_local_module_relation(
    root: Path, tree: dict[str, str], source_repo: str, commit: str,
    module_flake_path: str, relative: str,
    module_export: dict[str, Any], target_evidence: dict[str, Any],
    lock_evidence: dict[str, Any],
    rows: list[dict[str, Any]], gaps: list[str],
) -> None:
    candidate = posixpath.normpath(
        posixpath.join(posixpath.dirname(module_flake_path), relative)
    )
    host_module = _git_object_bytes(root, tree, candidate)
    if host_module is None:
        gaps.append("host_module_path_missing:" + candidate)
        return
    host_module_evidence = _artifact_evidence(
        source_repo, commit, candidate, tree, host_module,
    )
    rows.append(_record(
        "nixos_local_module_inclusion", module_export,
        host_module_evidence, [target_evidence, lock_evidence],
    ))
    _declared_services(
        source_repo, commit, tree, candidate, host_module,
        module_export, target_evidence, rows, gaps,
    )


def _module_binding_problem(
    target_flake: bytes, outer: bytes, inner: bytes,
    alias: str, dependency: str, declared_sha: str, module_flake_path: str,
) -> str | None:
    if not _verified_output_export(target_flake):
        return "target_module_export_unverified:" + dependency
    if not _verified_inner_flake(
        outer, inner, alias, dependency, declared_sha, module_flake_path
    ):
        return "inner_flake_input_unverified:" + alias
    if not _inner_host_modules_reaches_output(inner):
        return "host_modules_output_unverified:" + alias
    return None


def _declared_host_modules(
    root: Path, tree: dict[str, str], source_repo: str, commit: str,
    module_flake_path: str, outer: bytes, inner: bytes | None, alias: str,
    dependency: str, declared_sha: str, target_flake: bytes, target_evidence: dict[str, Any],
    root_evidence: dict[str, Any], lock_evidence: dict[str, Any],
    rows: list[dict[str, Any]], gaps: list[str],
) -> None:
    if inner is None:
        gaps.append("host_module_flake_unavailable:" + alias)
        return
    problem = _module_binding_problem(
        target_flake, outer, inner, alias, dependency, declared_sha,
        module_flake_path,
    )
    if problem is not None:
        gaps.append(problem)
        return
    for number, line, depth in _lexical_line_depths(
        _nix_without_trivia(inner.decode("utf-8"))
    ):
        if not re.match(r"^\s*hostModules\s*=", line):
            continue
        if depth != 1:
            gaps.append("host_modules_scope_unverified:" + alias)
            continue
        checked = _host_module_list_tokens(line, alias)
        if checked is None:
            gaps.append("host_modules_list_unverified:" + alias)
            continue
        alias_present, members = checked
        if not alias_present:
            continue
        module_export = _artifact_evidence(
            source_repo, commit, module_flake_path, tree, inner, number,
        )
        rows.append(_record(
            "nixos_module_binding", module_export, target_evidence,
            [root_evidence, lock_evidence],
        ))
        for relative in sorted(set(members)):
            _append_local_module_relation(
                root, tree, source_repo, commit, module_flake_path,
                relative, module_export, target_evidence,
                lock_evidence, rows, gaps,
            )




def _request_guard(source_repo: str, targets: object, module_flake_path: str) -> None:
    if not isinstance(source_repo, str) or not _REPO.fullmatch(source_repo):
        raise ValueError("source_repo must be an exact owner/repo identity")
    if not isinstance(targets, dict) or len(targets) > 16 or any(
        not isinstance(key, str) or not _REPO.fullmatch(key)
        for key in targets
    ):
        raise ValueError("targets must be bounded owner/repo mappings")
    if module_flake_path != "nixos/system/flake.nix":
        raise ValueError("unsupported module flake path")


def flake_revision_relations(
    source_root: str | Path, source_commit: str, *,
    source_repo: str,
    targets: dict[str, tuple[str | Path, str]],
    module_flake_path: str = "nixos/system/flake.nix",
) -> dict[str, Any]:
    """Prove only revision-pinned declarations; no fetch, evaluation or runtime claim."""
    _request_guard(source_repo, targets, module_flake_path)
    root = _repo_root(Path(source_root))
    commit = _revision(root, source_commit)
    tree, capped = _git_tree(root, commit)
    outer = _git_object_bytes(root, tree, "flake.nix")
    lock = _git_object_bytes(root, tree, "flake.lock")
    inner = _git_object_bytes(root, tree, module_flake_path)
    gaps = ["source_tree_capped"] if capped else []
    rows: list[dict[str, Any]] = []
    if outer is None or lock is None:
        gaps.append("source_flake_or_lock_unavailable")
    else:
        nodes, root_inputs = _locked_inputs(lock)
        urls, url_gaps = _literal_urls(outer.decode("utf-8"))
        gaps.extend(url_gaps)
        for alias, (dependency, declared_sha, url_line) in sorted(urls.items()):
            resolved = _resolved_target(
                alias, dependency, declared_sha, nodes, root_inputs, targets, gaps,
                outer.decode("utf-8"),
            )
            if resolved is None:
                continue
            target_sha, target_tree, target_flake = resolved
            root_evidence = _artifact_evidence(
                source_repo, commit, "flake.nix", tree, outer, url_line,
            )
            lock_evidence = _artifact_evidence(
                source_repo, commit, "flake.lock", tree, lock,
            )
            target_evidence = _artifact_evidence(
                dependency, target_sha, "flake.nix", target_tree, target_flake,
            )
            rows.append(_record(
                "flake_pinned_input", root_evidence, target_evidence, [lock_evidence],
            ))
            _declared_host_modules(
                root, tree, source_repo, commit, module_flake_path,
                outer, inner, alias, dependency, declared_sha, target_flake,
                target_evidence, root_evidence, lock_evidence,
                rows, gaps,
            )
    rows.sort(key=lambda row: (
        row["relation_type"], row["source"].get("path", ""),
        row["source"].get("line_start") or 0, row["target"].get("path", ""),
    ))
    result = {
        "kind": KIND, "version": VERSION, "source_repo": source_repo,
        "source_commit": commit, "status": "partial" if gaps else "ok",
        "relations": rows, "gaps": sorted(set(gaps)),
        "does_not_establish": [
            "complete_input_coverage", "nix_evaluation",
            "built_artifact", "active_generation", "running_service",
            "runtime_dependency", "impact_completeness",
        ],
    }
    result["evidence_sha256"] = hashlib.sha256(json.dumps(
        result, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    return result
