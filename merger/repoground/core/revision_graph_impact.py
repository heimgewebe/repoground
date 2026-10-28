"""Revision-bound structural change-impact over the existing RepoGround producers.

Unlike a path-only diff this projects changed Python symbols and static incoming
and outgoing edges. Every claim is tied to an immutable Git pair and a clean
checkout at the exact head. It neither mutates Git nor performs review decisions.
An ephemeral tree identity is NOT a published RepoGround bundle manifest.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from merger.repoground.architecture.import_graph import _GRAPH_FILE_LANGUAGES, _SKIP_DIRECTORIES
from merger.repoground.architecture.symbol_index import EXCLUDED_DIRS
from merger.repoground.architecture.relationship_projection import (
    generate_relationship_document,
)
from merger.repoground.architecture.symbol_index import _SymbolVisitor
from merger.repoground.core.delta_context import parse_unified_diff

KIND = "repobrief.revision_graph_impact"
VERSION = "1.0"
MAX_DIFF_BYTES = 5_000_000
MAX_SOURCE_BYTES = 512_000
MAX_IMPACTS = 200
MAX_FILES = 200
_SHA = re.compile(r"^[0-9a-f]{40}$")
NONCLAIMS = (
    "runtime_impact", "complete_blast_radius", "dynamic_dispatch_resolution",
    "test_sufficiency", "review_verdict", "merge_readiness",
)


def _git(repo: Path, args: list[str], *, max_bytes: int = MAX_DIFF_BYTES) -> bytes:
    """Execute fixed local read-only git commands with bounded result storage."""
    command = [
        "git", "--no-optional-locks", "-c", "core.hooksPath=/dev/null",
        "-c", "core.fsmonitor=false", "-c", "diff.external=",
        "-c", "pager.diff=false", "-c", "core.pager=cat",
        "-C", str(repo), *args,
    ]
    with tempfile.TemporaryFile() as out:
        try:
            run = subprocess.run(
                command, stdout=out, stderr=subprocess.PIPE,
                check=False, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"git_source_unavailable:{type(exc).__name__}") from exc
        if run.returncode != 0:
            raise ValueError("git_command_failed:" + args[0])
        size = out.tell()
        if size > max_bytes:
            raise ValueError("git_output_exceeds_limit")
        out.seek(0)
        return out.read(max_bytes + 1)


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ValueError(f"{name} must be a complete lowercase Git SHA")
    return value


def _revision(repo: Path, sha: str) -> str:
    actual = _git(repo, ["rev-parse", "--verify", f"{sha}^{{commit}}"], max_bytes=100)
    return actual.decode("ascii").strip()


def _identity(repo: Path, base: str, head: str) -> dict[str, Any]:
    if _revision(repo, base) != base or _revision(repo, head) != head:
        raise ValueError("commit_identity_mismatch")
    checked_out = _git(repo, ["rev-parse", "--verify", "HEAD"], max_bytes=100)
    if checked_out.decode("ascii").strip() != head:
        raise ValueError("checkout_head_not_requested_revision")
    status = _git(
        repo, ["status", "--porcelain=v1", "--untracked-files=all"], max_bytes=100_000
    )
    if status:
        raise ValueError("checkout_dirty_or_untracked")
    command = [
        "git", "--no-optional-locks", "-C", str(repo),
        "merge-base", "--is-ancestor", base, head,
    ]
    try:
        result = subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            check=False, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("ancestry_check_unavailable") from exc
    if result.returncode != 0:
        raise ValueError("base_not_ancestor_of_head")
    tree = _git(repo, ["rev-parse", "--verify", f"{head}^{{tree}}"], max_bytes=100)
    tree_sha = tree.decode("ascii").strip()
    material = json.dumps(
        {"kind": "derived_clean_git_tree", "version": 1, "commit": head, "tree": tree_sha},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return {
        "source_commit": head, "source_tree": tree_sha,
        "manifest_identity": {
            "kind": "derived_clean_git_tree", "sha256": hashlib.sha256(material).hexdigest(),
            "status": "derived_not_published", "is_bundle_manifest": False,
        },
    }


def _is_graph_source_path(path: str) -> bool:
    """Mirror the producer traversal eligibility, excluding generated caches."""
    parts = PurePosixPath(path).parts
    if not parts or path.startswith("/") or ".." in parts:
        return True  # Invalid names must never be silently trusted.
    parent = parts[:-1]
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".py":
        symbol_source = not any(part in EXCLUDED_DIRS for part in parent)
        # Import graph also reads Python under build/dist, unlike symbol_index.
        import_source = ".github" not in parent and not any(
            part in _SKIP_DIRECTORIES or part.startswith(".") for part in parent
        )
        return symbol_source or import_source
    if any(part in _SKIP_DIRECTORIES or (part.startswith(".") and part != ".github") for part in parent):
        return False
    if path.endswith(".graph.json"):
        return False
    return suffix in _GRAPH_FILE_LANGUAGES


def _reject_source_index_trust_flags(repo: Path) -> None:
    """Refuse Git index hints that conceal on-disk producer changes from status."""
    flagged = _git(repo, ["ls-files", "-v", "-z"], max_bytes=8_000_000)
    for record in flagged.split(b"\x00"):
        if not record:
            continue
        tag, separator, raw_path = record.partition(b" ")
        if separator != b" " or len(tag) != 1:
            raise ValueError("tracked_source_flags_invalid")
        if (tag.islower() or tag == b"S") and _is_graph_source_path(raw_path.decode("utf-8")):
            raise ValueError("tracked_source_index_trust_flags")


def _source_inventory_safe(repo: Path) -> None:
    """Fail closed when a producer could read bytes absent from Git HEAD.

    Normal cleanliness checks ignore files by design. Existing source producers
    walk the checkout; even ignored source can otherwise become falsely
    revision-bound S1 evidence. Do not alter those producers or assume that a
    clean porcelain result establishes source inventory equality.
    """
    ignored = _git(
        repo, ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
        max_bytes=8_000_000,
    )
    for raw in ignored.split(b"\x00"):
        if raw and _is_graph_source_path(raw.decode("utf-8")):
            raise ValueError("ignored_source_not_in_head")
    _reject_source_index_trust_flags(repo)
    stage = _git(repo, ["ls-files", "--stage", "-z"], max_bytes=8_000_000)
    for raw in stage.split(b"\x00"):
        if not raw:
            continue
        header, separator, name = raw.partition(b"\t")
        if separator != b"\t":
            raise ValueError("tracked_source_inventory_invalid")
        mode = header.split(b" ", 1)[0]
        if mode == b"160000":
            # Producers traverse Gitlink directories, whose contents do not
            # belong to the superproject tree bound by the report.
            raise ValueError("tracked_submodule_untrusted")
        if mode == b"120000" and _is_graph_source_path(name.decode("utf-8")):
            raise ValueError("tracked_source_symlink_untrusted")


def _include_decorators(
    symbols: list[dict[str, Any]], tree: ast.AST
) -> list[dict[str, Any]]:
    """Expand change-intersection ranges, keeping producer symbol identities."""
    starts: dict[tuple[int, str], int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            starts[(node.lineno, node.name)] = min(
                [node.lineno, *(dec.lineno for dec in node.decorator_list)]
            )
    projected: list[dict[str, Any]] = []
    for symbol in symbols:
        first = starts.get((symbol["start_line"], symbol["name"]), symbol["start_line"])
        if first < symbol["start_line"]:
            updated = dict(symbol)
            updated["start_line"] = first
            updated["range_ref"] = f"file:{symbol['path']}#L{first}-L{symbol['end_line']}"
            projected.append(updated)
        else:
            projected.append(symbol)
    return projected


def _head_symbols_for_changes(
    repo: Path, head: str, path: str, symbols: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str | None]:
    if not symbols or not path.endswith(".py"):
        return symbols, None
    try:
        content = _git(repo, ["show", f"{head}:{path}"], max_bytes=MAX_SOURCE_BYTES)
        parsed = ast.parse(content.decode("utf-8"), filename=path)
    except (ValueError, UnicodeDecodeError, SyntaxError):
        return symbols, "head_decorator_range_unavailable"
    return _include_decorators(symbols, parsed), None


def _old_symbols(repo: Path, base: str, path: str) -> tuple[list[dict[str, Any]], str | None]:
    """Parse only changed base-side Python files, not a second repository graph."""
    if not path.endswith(".py"):
        return [], None
    try:
        size = int(_git(repo, ["cat-file", "-s", f"{base}:{path}"], max_bytes=40))
        if size > MAX_SOURCE_BYTES:
            return [], "base_source_too_large"
        content = _git(repo, ["show", f"{base}:{path}"], max_bytes=MAX_SOURCE_BYTES)
    except ValueError:
        return [], "base_source_absent_or_unavailable"
    try:
        tree = ast.parse(content.decode("utf-8"), filename=path)
    except (UnicodeDecodeError, SyntaxError):
        return [], "base_python_parse_failed"
    visitor = _SymbolVisitor(path)
    visitor.visit(tree)
    return _include_decorators(visitor.symbols, tree), None


def _intersects(record: Mapping[str, Any], hunks: list[dict[str, Any]], basis: str) -> bool:
    for hunk in hunks:
        span = hunk.get(basis + "_range", {})
        if not span or span.get("empty") or not span.get("line_count"):
            continue
        if record["start_line"] <= span["end_line"] and span["start_line"] <= record["end_line"]:
            return True
    return False


def _changes(
    repo: Path, base: str, head: str, diff_files: list[dict[str, Any]],
    head_symbols: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str], set[str]]:
    by_path: dict[str, list[dict[str, Any]]] = {}
    for item in head_symbols:
        by_path.setdefault(item["path"], []).append(item)
    direct: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    changed_symbol_ids: set[str] = set()
    changed_paths: set[str] = set()
    for file in diff_files:
        new_path = file.get("new_path") or file.get("path")
        old_path = file.get("old_path") or file.get("path")
        if not isinstance(new_path, str):
            continue
        changed_paths.add(new_path)
        hunks = file.get("hunks", [])
        head_candidates, head_error = _head_symbols_for_changes(
            repo, head, new_path, by_path.get(new_path, []),
        )
        if head_error:
            gaps.append({"path": new_path, "reason": head_error, "evidence_level": "S0"})
        new_symbols = [
            symbol for symbol in head_candidates
            if _intersects(symbol, hunks, "new")
        ]
        old_symbols, error = _old_symbols(repo, base, old_path)
        old_changed = [s for s in old_symbols if _intersects(s, hunks, "old")]
        if error is not None and old_path.endswith(".py") and file["change_status"] != "added":
            gaps.append({"path": old_path, "reason": error, "evidence_level": "S0"})
        new_ids = {symbol["id"] for symbol in new_symbols}
        for symbol, basis in [
            *((s, "head") for s in new_symbols),
            *((s, "base") for s in old_changed if s["id"] not in new_ids),
        ]:
            changed_symbol_ids.add(symbol["id"])
            direct.append({
                "category": "directly_changed_symbol", "basis": basis,
                "path": symbol["path"], "symbol_id": symbol["id"],
                "range_ref": symbol["range_ref"], "kind": symbol["kind"],
            })
        if not new_symbols and not old_changed:
            direct.append({
                "category": "directly_changed_file",
                "basis": "head" if file["change_status"] != "deleted" else "base",
                "path": new_path,
                "change_status": file["change_status"],
                "hunks": [
                    {"old_range": hunk.get("old_range"), "new_range": hunk.get("new_range")}
                    for hunk in hunks
                ],
            })
            if new_path.endswith(".py"):
                gaps.append({
                    "path": new_path, "reason": "changed_python_ranges_without_symbol_match",
                    "evidence_level": "S0",
                })
        if file.get("binary"):
            gaps.append({"path": new_path, "reason": "binary_diff", "evidence_level": "S0"})
    direct.sort(key=lambda e: (e["path"], e.get("symbol_id", ""), e["category"], e["basis"]))
    return direct, gaps, changed_symbol_ids, changed_paths


def _impact_from_relations(
    relations: list[dict[str, Any]], changed_symbols: set[str], changed_files: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    affected: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    tests: set[str] = set()
    targets = changed_symbols | {"file:" + path for path in changed_files}
    for edge in relations:
        src, dst = edge["src"], edge["dst"]
        if edge["relation"] == "defines":
            continue
        candidates = edge.get("candidate_target_ids", [])
        candidate_hit = (
            edge["resolution_status"] != "resolved"
            and isinstance(candidates, list)
            and bool(targets.intersection(candidates))
        )
        touching = src in targets or dst in targets or candidate_hit
        if not touching:
            continue
        record = {
            "relation_id": edge["id"], "relation": edge["relation"],
            "source": edge["source"], "source_id": src, "target_id": dst,
            "evidence_level": edge["evidence_level"], "resolution_status": edge["resolution_status"],
            "direction": "outgoing" if src in targets else "incoming",
        }
        if edge["resolution_status"] == "resolved" and edge["evidence_level"] == "S1":
            affected.append(record)
            if edge["relation"] == "tests" and dst in targets:
                tests.add(edge["source"]["path"])
        else:
            record["reason"] = "static_target_not_proven"
            if candidate_hit:
                record["candidate_target_ids"] = sorted(set(candidates))[:20]
            uncertain.append(record)
    sort_key = lambda row: (
        row["source"]["path"], row["source"]["start_line"],
        row["relation"], row["relation_id"],
    )
    affected.sort(key=sort_key)
    uncertain.sort(key=sort_key)
    return affected, uncertain, sorted(tests)


def _validated_revision_diff(
    root: Path, base_sha: str, head_sha: str,
) -> tuple[bytes, dict[str, Any]]:
    """Bound and compare both patch and raw Git path inventory."""
    diff = _git(
        root, ["diff", "--no-ext-diff", "--no-textconv", "--no-color",
               "--unified=0", base_sha, head_sha, "--"],
        max_bytes=MAX_DIFF_BYTES,
    )
    parsed = parse_unified_diff(diff.decode("utf-8"), context_window_lines=0)
    if parsed["truncated"] or parsed["file_count"] > MAX_FILES:
        raise ValueError("diff_file_limit_exceeded")
    # Raw NUL-delimited paths reject silently skipped Git-quoted filenames.
    raw_names = _git(
        root, ["diff", "--name-only", "-z", base_sha, head_sha, "--"],
        max_bytes=MAX_DIFF_BYTES,
    )
    names = {part.decode("utf-8") for part in raw_names.split(b"\x00") if part}
    parsed_names = {item["path"] for item in parsed["files"]}
    if names != parsed_names:
        raise ValueError("unsupported_or_unparsed_git_diff_paths")
    return diff, parsed


def _unexamined_incoming_relation_gaps(
    files: list[dict[str, Any]], changed_symbols: set[str],
    head_symbols: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Report targets whose base-side incoming edges cannot be checked at HEAD."""
    gaps: list[dict[str, Any]] = []
    missing_symbols = changed_symbols - {item["id"] for item in head_symbols}
    if missing_symbols:
        gaps.append({
            "reason": "deleted_symbol_incoming_relations_not_analyzed",
            "count": len(missing_symbols), "evidence_level": "S0",
        })
    deleted_paths = {
        file.get("old_path") or file.get("path")
        for file in files if file.get("change_status") == "deleted"
    }
    if deleted_paths:
        gaps.append({
            "reason": "deleted_file_incoming_relations_not_analyzed",
            "count": len(deleted_paths), "evidence_level": "S0",
        })
    renamed_away_paths = {
        file.get("old_path")
        for file in files
        if file.get("change_status") == "renamed"
        and isinstance(file.get("old_path"), str)
        and file.get("old_path") != file.get("new_path")
    }
    if renamed_away_paths:
        gaps.append({
            "reason": "renamed_away_file_incoming_relations_not_analyzed",
            "count": len(renamed_away_paths), "evidence_level": "S0",
        })
    return gaps


def compile_revision_graph_impact(
    repo_root: Path,
    *,
    base_sha: str,
    head_sha: str,
    max_items: int = MAX_IMPACTS,
) -> dict[str, Any]:
    """Analyze a clean HEAD checkout against an ancestral immutable base SHA.

    No review verdicts. No bundle is invented or refreshed; an ephemeral Git tree
    identity is explicitly distinguished from a published bundle manifest.
    """
    _sha(base_sha, "base_sha")
    _sha(head_sha, "head_sha")
    if isinstance(max_items, bool) or not isinstance(max_items, int) or not 1 <= max_items <= MAX_IMPACTS:
        raise ValueError("max_items must be between 1 and 200")
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise ValueError("repository_root_unavailable")
    top_level = _git(root, ["rev-parse", "--show-toplevel"], max_bytes=4096)
    if Path(top_level.decode("utf-8").strip()).resolve() != root:
        raise ValueError("repository_root_must_be_worktree_toplevel")
    identity = _identity(root, base_sha, head_sha)
    _source_inventory_safe(root)
    diff, parsed = _validated_revision_diff(root, base_sha, head_sha)
    diff_sha = hashlib.sha256(diff).hexdigest()
    from merger.repoground.architecture.symbol_index import extract_python_symbols

    symbols, symbol_skip_count, symbol_errors = extract_python_symbols(root)
    direct, gaps, ids, paths = _changes(root, base_sha, head_sha, parsed["files"], symbols)
    context = generate_relationship_document(
        root, "revision-impact:" + head_sha,
        identity["manifest_identity"]["sha256"],
        max_edges=250_000,
    )
    proven, unresolved, relevant_tests = _impact_from_relations(context["edges"], ids, paths)
    gaps.extend(_unexamined_incoming_relation_gaps(parsed["files"], ids, symbols))
    graph_coverage = context["coverage"]
    source_truncated = bool(
        graph_coverage.get("producer_repository_truncated")
        or graph_coverage.get("declared_source_coverage", {}).get("truncated")
    )
    if source_truncated:
        gaps.append({"reason": "producer_graph_coverage_truncated", "evidence_level": "S0"})
    for message in symbol_errors:
        gaps.append({"reason": "symbol_parse_skipped", "detail": message, "evidence_level": "S0"})
    if symbol_skip_count > len(symbol_errors):
        gaps.append({
            "reason": "more_symbol_errors_suppressed",
            "count": symbol_skip_count - len(symbol_errors), "evidence_level": "S0",
        })
    if context["coverage"]["truncated"]:
        gaps.append({"reason": "relationship_projection_truncated", "evidence_level": "S0"})
    # Reject a race between source reads and git HEAD/working tree changes.
    _source_inventory_safe(root)
    if _identity(root, base_sha, head_sha) != identity:
        raise ValueError("source_changed_during_analysis")
    truncated = (
        any(len(records) > max_items for records in (direct, proven, unresolved, gaps, relevant_tests))
        or bool(context["coverage"]["truncated"])
        or source_truncated
    )
    return {
        "kind": KIND, "version": VERSION,
        "status": "truncated" if truncated else "bounded",
        "base_sha": base_sha, "head_sha": head_sha,
        "diff_sha256": diff_sha, "diff_bytes": len(diff),
        "source_provenance": identity,
        "directly_changed": direct[:max_items],
        "potentially_affected": proven[:max_items],
        "unresolved": unresolved[:max_items],
        "gaps": gaps[:max_items],
        "expected_checks": [
            {"kind": "inspect_test", "path": path, "authority": "S1_lexical_reference"}
            for path in relevant_tests[:max_items]
        ],
        "coverage": {
            "changed_files": parsed["file_count"],
            "changed_symbols": len(ids),
            "direct_count": len(direct),
            "proven_relation_count": len(proven),
            "unresolved_relation_count": len(unresolved),
            "symbol_parser_skipped_files": symbol_skip_count,
            "graph": context["coverage"],
            "truncated": truncated,
        },
        "does_not_establish": list(NONCLAIMS),
    }