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
    r'^\s*(?P<alias>[A-Za-z_][\w-]*)\.url\s*=\s*"github:'
    r'(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/'
    r'(?P<sha>[0-9a-f]{40})"\s*;\s*(?:#.*)?$'
)
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_MODULE = re.compile(r"\./modules/[A-Za-z0-9_.-]+\.nix")


def _literal_urls(text: str) -> tuple[dict[str, tuple[str, str, int]], list[str]]:
    original = text.splitlines()
    masked = _nix_without_trivia(text).splitlines()
    found: dict[str, tuple[str, str, int]] = {}
    gaps: list[str] = []
    for number, line in enumerate(original, 1):
        match = _URL.fullmatch(line)
        if match is None or number > len(masked):
            continue
        alias = match["alias"]
        if not masked[number - 1].lstrip().startswith(alias + ".url"):
            continue  # comment/string which only resembles a declaration
        if alias in found:
            gaps.append("duplicate_flake_input:" + alias)
            del found[alias]
            continue
        if "duplicate_flake_input:" + alias in gaps:
            continue
        found[alias] = (
            match["owner"] + "/" + match["repo"], match["sha"], number
        )
    return found, gaps


def _record(kind: str, src: dict[str, Any], dst: dict[str, Any],
            supporting: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "relation_type": kind, "direction": "source_to_target",
        "evidence_level": "S1", "resolution_status": "resolved",
        "source": src, "target": dst, "supporting_evidence": supporting,
        "asserts_runtime_dependency": False,
    }


def flake_revision_relations(
    source_root: str | Path, source_commit: str, *,
    source_repo: str,
    targets: dict[str, tuple[str | Path, str]],
    module_flake_path: str = "nixos/system/flake.nix",
) -> dict[str, Any]:
    """Project only proven source->target dependencies, never fetch or evaluate.

    targets is keyed by exact owner/repo; each target supplies its own Git root
    and independently verified commit. No Fleet membership is required.
    """
    if not isinstance(source_repo, str) or not _REPO.fullmatch(source_repo):
        raise ValueError("source_repo must be an exact owner/repo identity")
    if not isinstance(targets, dict) or len(targets) > 16 or any(
        not isinstance(key, str) or not _REPO.fullmatch(key)
        for key in targets
    ):
        raise ValueError("targets must be bounded owner/repo mappings")
    if module_flake_path != "nixos/system/flake.nix":
        raise ValueError("unsupported module flake path")
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
        try:
            text = outer.decode("utf-8")
            lock_doc = json.loads(lock.decode("utf-8"))
            nodes = lock_doc["nodes"]
            root_inputs = nodes[lock_doc["root"]]["inputs"]
            if not isinstance(nodes, dict) or not isinstance(root_inputs, dict):
                raise ValueError("bad flake lock")
        except (ValueError, UnicodeError, KeyError, TypeError) as exc:
            raise ValueError("invalid flake.lock at requested Git revision") from exc
        urls, url_gaps = _literal_urls(text)
        gaps.extend(url_gaps)
        for alias, (dependency, declared_sha, url_line) in sorted(urls.items()):
            node_key = root_inputs.get(alias)
            lock_node = nodes.get(node_key) if isinstance(node_key, str) else None
            locked = lock_node.get("locked") if isinstance(lock_node, dict) else None
            if (
                not isinstance(locked, dict)
                or locked.get("type") != "github"
                or locked.get("owner") != dependency.split("/", 1)[0]
                or locked.get("repo") != dependency.split("/", 1)[1]
                or locked.get("rev") != declared_sha
            ):
                gaps.append("flake_lock_mismatch:" + alias)
                continue
            spec = targets.get(dependency)
            if spec is None:
                gaps.append("target_not_provided:" + dependency)
                continue
            target_root, requested_sha = spec
            if requested_sha != declared_sha or not _SHA.fullmatch(requested_sha):
                gaps.append("target_commit_mismatch:" + dependency)
                continue
            try:
                target_path = _repo_root(Path(target_root))
                target_sha = _revision(target_path, requested_sha)
                target_tree, target_capped = _git_tree(target_path, target_sha)
            except (ValueError, OSError):
                gaps.append("target_commit_unavailable:" + dependency)
                continue
            if target_capped:
                gaps.append("target_tree_capped:" + dependency)
                continue
            target_flake = _git_object_bytes(target_path, target_tree, "flake.nix")
            if target_flake is None:
                gaps.append("target_flake_unavailable:" + dependency)
                continue
            root_evidence = _artifact_evidence(
                source_repo, commit, "flake.nix", tree, outer, url_line
            )
            lock_evidence = _artifact_evidence(
                source_repo, commit, "flake.lock", tree, lock
            )
            target_evidence = _artifact_evidence(
                dependency, target_sha, "flake.nix", target_tree, target_flake
            )
            rows.append(_record(
                "flake_pinned_input", root_evidence, target_evidence,
                [lock_evidence]
            ))
            if inner is None:
                gaps.append("host_module_flake_unavailable:" + alias)
                continue
            # The target must declare the module export in syntax, not only
            # mention its name in a string or comment.
            export_syntax = _nix_without_trivia(
                target_flake.decode("utf-8", errors="replace")
            )
            if not re.search(r"(?<![\w.])nixosModules\.default\s*=", export_syntax):
                gaps.append("target_module_export_unverified:" + dependency)
                continue
            masked = _nix_without_trivia(inner.decode("utf-8"))
            for number, line in enumerate(masked.splitlines(), 1):
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
                        [root_evidence, lock_evidence, host_module_evidence]
                    ))
                    rows.append(_record(
                        "nixos_local_module_inclusion", module_export,
                        host_module_evidence, [target_evidence, lock_evidence],
                    ))
                    for service, token in (
                        ("services.nixer", "services.nixer ="),
                        ("systemd.user.services.nixer", "systemd.user.services.nixer ="),
                    ):
                        for service_line, source_line in enumerate(
                            _nix_without_trivia(host_module.decode("utf-8")).splitlines(), 1
                        ):
                            if source_line.lstrip().startswith(token):
                                rows.append(_record(
                                    "nixos_service_declaration",
                                    _artifact_evidence(
                                        source_repo, commit, candidate, tree,
                                        host_module, service_line
                                    ),
                                    {"repo_id": source_repo, "commit": commit,
                                     "symbol": service, "status": "declared_only"},
                                    [module_export, target_evidence],
                                ))
    rows.sort(key=lambda row: (
        row["relation_type"], row["source"].get("path", ""),
        row["source"].get("line_start") or 0, row["target"].get("path", ""),
    ))
    result = {
        "kind": KIND, "version": VERSION, "source_repo": source_repo,
        "source_commit": commit,
        "status": "partial" if gaps else "ok",
        "relations": rows, "gaps": sorted(set(gaps)),
        "does_not_establish": [
            "complete_input_coverage", "nix_evaluation",
            "built_artifact", "active_generation", "running_service",
            "runtime_dependency", "impact_completeness",
        ],
    }
    result["evidence_sha256"] = hashlib.sha256(json.dumps(
        result, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    return result
