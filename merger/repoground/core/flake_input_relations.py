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


def _resolved_target(
    alias: str, dependency: str, declared_sha: str,
    nodes: dict[str, Any], root_inputs: dict[str, Any],
    targets: dict[str, tuple[str | Path, str]], gaps: list[str],
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


def _declared_services(
    source_repo: str, commit: str, tree: dict[str, str],
    candidate: str, host_module: bytes,
    module_export: dict[str, Any], target_evidence: dict[str, Any],
    rows: list[dict[str, Any]],
) -> None:
    syntax = _nix_without_trivia(host_module.decode("utf-8")).splitlines()
    for service, token in (
        ("services.nixer", "services.nixer ="),
        ("systemd.user.services.nixer", "systemd.user.services.nixer ="),
    ):
        for number, line in enumerate(syntax, 1):
            if line.lstrip().startswith(token):
                rows.append(_record(
                    "nixos_service_declaration",
                    _artifact_evidence(
                        source_repo, commit, candidate, tree, host_module, number,
                    ),
                    {"repo_id": source_repo, "commit": commit,
                     "symbol": service, "status": "declared_only"},
                    [module_export, target_evidence],
                ))


def _declared_host_modules(
    root: Path, tree: dict[str, str], source_repo: str, commit: str,
    module_flake_path: str, inner: bytes | None, alias: str,
    target_flake: bytes, target_evidence: dict[str, Any],
    root_evidence: dict[str, Any], lock_evidence: dict[str, Any],
    rows: list[dict[str, Any]], gaps: list[str],
) -> None:
    if inner is None:
        gaps.append("host_module_flake_unavailable:" + alias)
        return
    # Do not promote a mention in a comment or a string to an exported module.
    export_syntax = _nix_without_trivia(
        target_flake.decode("utf-8", errors="replace")
    )
    if not re.search(r"(?<![\w.])nixosModules\.default\s*=", export_syntax):
        gaps.append("target_module_export_unverified:" + target_evidence["repo_id"])
        return
    for number, line in enumerate(_nix_without_trivia(inner.decode("utf-8")).splitlines(), 1):
        if not re.match(r"^\s*hostModules\s*=\s*\[", line):
            continue
        if not re.search(r"\b" + re.escape(alias) + r"\.nixosModules\.default\b", line):
            continue
        for relative in sorted(set(_MODULE.findall(line))):
            candidate = posixpath.normpath(
                posixpath.join(posixpath.dirname(module_flake_path), relative)
            )
            host_module = _git_object_bytes(root, tree, candidate)
            if host_module is None:
                gaps.append("host_module_path_missing:" + candidate)
                continue
            module_export = _artifact_evidence(
                source_repo, commit, module_flake_path, tree, inner, number
            )
            host_module_evidence = _artifact_evidence(
                source_repo, commit, candidate, tree, host_module
            )
            rows.append(_record(
                "nixos_module_binding", module_export, target_evidence,
                [root_evidence, lock_evidence, host_module_evidence],
            ))
            rows.append(_record(
                "nixos_local_module_inclusion", module_export,
                host_module_evidence, [target_evidence, lock_evidence],
            ))
            _declared_services(
                source_repo, commit, tree, candidate, host_module,
                module_export, target_evidence, rows,
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
                root, tree, source_repo, commit, module_flake_path, inner, alias,
                target_flake, target_evidence, root_evidence, lock_evidence,
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
