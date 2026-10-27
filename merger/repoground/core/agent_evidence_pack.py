"""Compact, read-only change evidence from Git revisions and an existing RepoGround bundle.

The Git checkout is the authority for the diff. Bundle hints are explicitly
historical, never assertions about a changed target revision.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import time
from typing import Any

from merger.repoground.core.delta_context import compile_delta_context, parse_unified_diff
from merger.repoground.core.manifest_snapshot import (
    ManifestBindingError, manifest_snapshot, use_manifest_binding,
)

KIND = "repoground.agent_change_evidence"
VERSION = 1
MAX_DIFF_BYTES = 2_000_000
MAX_MANIFEST_BYTES = 4_000_000
MAX_CONTEXT_TOKENS = 4_000
MAX_CHANGED_FILES = 30
MAX_EVIDENCE_ITEMS = 12
MAX_HUNKS_PER_FILE = 16
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
USE_CASES = (
    "explain-change",
    "find-related-tests",
    "contract-impact",
    "cross-repo-impact",
    "what-changed-since",
    "source-and-proof",
)
BOUNDARY = {
    "writes": [],
    "implicit_snapshot_refresh": False,
    "automated_review": False,
    "automated_patch": False,
    "automated_merge": False,
    "authorization": "none; Git, CI and operators decide independently",
}
NOT_ESTABLISHED = [
    "review_verdict",
    "test_sufficiency",
    "runtime_behavior",
    "transitive_impact_completeness",
    "cross_repository_impact_completeness",
    "merge_authorization",
]


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _invalid(reason: str) -> dict[str, Any]:
    return {
        "kind": KIND, "version": VERSION, "status": "invalid", "reason": reason,
        "changed_files": [], "hints": [], "gaps": [{"code": reason}],
        "mutation_boundary": BOUNDARY, "does_not_establish": NOT_ESTABLISHED,
    }


def _bounded_git_stdout(pipe: Any, *, max_bytes: int) -> tuple[bytes | None, str | None]:
    """Stream a finite Git response without allowing unbounded memory use."""
    chunks = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(pipe, selectors.EVENT_READ)
        deadline = time.monotonic() + 15.0
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return None, "git_timeout"
            if not selector.select(min(left, 0.25)):
                continue
            data = os.read(pipe.fileno(), 65536)
            if not data:
                return bytes(chunks), None
            chunks.extend(data)
            if len(chunks) > max_bytes:
                return None, "git_output_limit"


def _bounded_git(root: Path, args: list[str], *, max_bytes: int = 131072) -> tuple[str | None, str | None]:
    """Use only fixed Git builtins without hooks, network, temporary files or index locks."""
    command = [
        "git", "-c", "core.hooksPath=/dev/null", "-c", "color.ui=never",
        "-c", "core.fsmonitor=false", "-c", "diff.external=",
        "-c", "protocol.allow=never", "-c", "protocol.file.allow=never",
        "-C", str(root), *args,
    ]
    # Git partial clones can lazily fetch missing *promisor* objects even
    # during an ordinary "diff". Explicitly prohibit all transports and
    # disable lazy fetch; read-only CLI/MCP must never mutate .git this way.
    # Override hostile inherited GIT_ALLOW_PROTOCOL/GIT_NO_LAZY_FETCH values.
    env = dict(
        os.environ,
        GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0",
        GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="",
        GIT_PROTOCOL_FROM_USER="0",
    )
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, env=env,
        )
        assert process.stdout is not None
        raw, error = _bounded_git_stdout(process.stdout, max_bytes=max_bytes)
        if error:
            return None, error
        if process.wait(timeout=1) != 0:
            return None, "git_command_failed"
        try:
            assert raw is not None
            return raw.decode("utf-8"), None
        except UnicodeDecodeError:
            return None, "git_output_invalid_utf8"
    except (OSError, subprocess.TimeoutExpired):
        return None, "git_unavailable"
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            if process.stdout is not None:
                process.stdout.close()


def _bundle_identity(path: str | Path | None) -> tuple[dict[str, Any], list[str]]:
    """Read exactly the request-pinned snapshot, not a freshly resolved pointer.

    MCP tool dispatch pins one publication generation for the whole request;
    re-resolving its selected symlink could mislabel old hints with new SHA.
    The same bounded capture API also protects direct CLI metadata reads.
    """
    if path is None:
        return {"status": "unavailable", "reason": "no_bundle_supplied"}, ["no_bundle_supplied"]
    try:
        snapshot = manifest_snapshot(path)
    except (ManifestBindingError, OSError, ValueError):
        return {"status": "invalid", "reason": "manifest_not_readable"}, ["manifest_not_readable"]
    if not snapshot.resolved_path.name.endswith(".bundle.manifest.json"):
        return {"status": "invalid", "reason": "invalid_manifest"}, ["invalid_manifest"]
    raw = snapshot.raw
    if len(raw) > MAX_MANIFEST_BYTES:
        return {"status": "invalid", "reason": "manifest_too_large"}, ["manifest_too_large"]
    data = snapshot.json_object()
    provenance = data.get("snapshot_provenance") or {}
    repositories = provenance.get("repositories", []) if isinstance(provenance, dict) else []
    commits = sorted({
        row["git_commit"] for row in repositories
        if isinstance(row, dict) and isinstance(row.get("git_commit"), str)
        and _SHA40.fullmatch(row["git_commit"])
    }) if isinstance(repositories, list) else []
    return {
        "status": "available",
        "manifest_sha256": snapshot.binding.sha256,
        "source_commit": commits[0] if len(commits) == 1 else None,
        "source_commit_binding": "unique" if len(commits) == 1 else "unknown_or_ambiguous",
    }, [] if len(commits) == 1 else ["bundle_source_revision_unknown"]


MAX_TEST_CANDIDATES = 12
MAX_TRACKED_PATHS_BYTES = 1_000_000


def _indexed_test_paths(tracked_paths: str) -> dict[str, list[str]]:
    """Index only tracked Python test paths, never inferred filesystem files."""
    by_name: dict[str, list[str]] = {}
    for relative in tracked_paths.split("\0"):
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            continue
        basename = Path(relative).name
        if (basename.startswith("test_") and basename.endswith(".py")) or basename.endswith("_test.py"):
            by_name.setdefault(basename, []).append(relative)
    return by_name


def _matching_test_candidates(
    source_paths: list[str], by_name: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], str | None]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for changed in sorted(set(source_paths)):
        module_name = Path(changed).stem
        expected = (f"test_{module_name}.py", f"{module_name}_test.py")
        for filename in expected:
            for tracked_path in sorted(by_name.get(filename, [])):
                if (changed, tracked_path) in seen:
                    continue
                seen.add((changed, tracked_path))
                candidates.append({
                    "path": tracked_path,
                    "source_path": changed,
                    "candidate_reason": "exact_module_basename_match",
                    "verified_fact": "test_path_tracked_at_target_commit",
                    "claim_level": "name_candidate_not_verified_coverage",
                })
                if len(candidates) == MAX_TEST_CANDIDATES:
                    return candidates, "test_candidate_limit"
    return candidates, None


def _test_candidates(
    root: Path, target_revision: str, changed_paths: list[str],
) -> tuple[list[dict[str, Any]], str | None]:
    """Git-verified test filenames; naming correlation is NOT coverage evidence."""
    source_paths = [
        path for path in changed_paths
        if path.endswith(".py")
        and not Path(path).name.startswith("test_")
        and not Path(path).name.endswith("_test.py")
    ]
    if not source_paths:
        return [], None
    tracked, error = _bounded_git(
        root, ["ls-tree", "-r", "-z", "--name-only", target_revision, "--"],
        max_bytes=MAX_TRACKED_PATHS_BYTES,
    )
    if error or tracked is None:
        return [], "tracked_test_paths_unavailable"
    return _matching_test_candidates(source_paths, _indexed_test_paths(tracked))


def _is_explicit_contract_path(path: str) -> bool:
    parts = Path(path).parts
    return "contracts" in parts or path.endswith((
        ".schema.json", ".jsonschema", ".proto", ".graphql",
        ".openapi.yaml", ".openapi.yml", ".openapi.json",
    ))


def _request_error(
    use_case: str, context_budget_tokens: int, base_revision: str,
    target_revision: str, expected_diff_sha256: str | None,
) -> str | None:
    """Reject ambiguous selectors before running any Git subprocess."""
    if use_case not in USE_CASES:
        return "unknown_use_case"
    if not isinstance(context_budget_tokens, int) or isinstance(context_budget_tokens, bool) or not 1 <= context_budget_tokens <= MAX_CONTEXT_TOKENS:
        return "invalid_budget"
    if not isinstance(base_revision, str) or not _SHA40.fullmatch(base_revision):
        return "base_must_be_exact_commit_sha"
    if not isinstance(target_revision, str) or not _SHA40.fullmatch(target_revision):
        return "target_must_be_exact_commit_sha"
    if expected_diff_sha256 is not None and (not isinstance(expected_diff_sha256, str) or not _SHA64.fullmatch(expected_diff_sha256)):
        return "invalid_expected_diff_sha256"
    return None


def _diff_inventory_problem(
    root: Path, base_revision: str, target_revision: str, parsed: dict[str, Any],
) -> str | None:
    """Do not let textual Git quotePath parsing silently omit changed files."""
    raw_names, error = _bounded_git(
        root, ["diff", "--no-ext-diff", "--no-textconv", "--no-renames",
               "--ignore-submodules=none", "--name-only", "-z", base_revision, target_revision, "--"],
        max_bytes=MAX_DIFF_BYTES,
    )
    if error or raw_names is None:
        return "diff_path_inventory_unavailable"
    if raw_names and not raw_names.endswith("\0"):
        return "diff_path_inventory_invalid"
    names = sorted(name for name in raw_names.split("\0") if name)
    reported_names = sorted(str(item.get("path")) for item in parsed["files"])
    if names != reported_names:
        return "diff_paths_unresolved"
    return None


def _read_git_delta(
    root: Path, base_revision: str, target_revision: str,
    expected_diff_sha256: str | None,
) -> tuple[tuple[str, str, dict[str, Any]] | None, str | None]:
    top, error = _bounded_git(root, ["rev-parse", "--show-toplevel"])
    if error or top is None or Path(top.strip()).resolve() != root:
        return None, "not_exact_git_root"
    for commit in (base_revision, target_revision):
        resolved, error = _bounded_git(root, ["rev-parse", "--verify", f"{commit}^{{commit}}"])
        if error or resolved is None or resolved.strip() != commit:
            return None, "unavailable_commit"
    diff, error = _bounded_git(
        root, ["diff", "--no-ext-diff", "--no-textconv", "--no-renames",
               "--ignore-submodules=none", "--no-color", "--unified=3", base_revision, target_revision, "--"],
        max_bytes=MAX_DIFF_BYTES,
    )
    if error or diff is None:
        return None, error or "diff_unavailable"
    diff_sha = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    if expected_diff_sha256 is not None and expected_diff_sha256 != diff_sha:
        return None, "diff_sha256_mismatch"
    parsed = parse_unified_diff(diff)
    if not parsed["file_count"] or parsed.get("truncated"):
        return None, "empty_or_truncated_diff"
    problem = _diff_inventory_problem(root, base_revision, target_revision, parsed)
    if problem:
        return None, problem
    return (diff, diff_sha, parsed), None


def _bundle_revision_gaps(
    bundle: dict[str, Any], worktree_state: str,
    base_revision: str, target_revision: str,
) -> list[str]:
    codes: list[str] = []
    if worktree_state != "clean":
        codes.append("worktree_" + worktree_state)
    source_commit = bundle.get("source_commit")
    if source_commit is not None and source_commit not in {base_revision, target_revision}:
        codes.append("bundle_revision_not_in_diff")
    if source_commit is None and bundle.get("status") == "available":
        codes.append("bundle_revision_unverified")
    return codes


def _valid_navigation_path(path: Any) -> bool:
    return (
        isinstance(path, str) and bool(path)
        and not path.startswith("/") and ".." not in path.split("/")
    )


def _navigation_path(item: dict[str, Any]) -> str | None:
    """Normalize actual delta-context source shapes, never trust bundle impact."""
    source = item.get("source")
    if source == "python_symbol_index_json":
        symbol = item.get("symbol")
        path = symbol.get("path") if isinstance(symbol, dict) else None
        return path if _valid_navigation_path(path) else None
    if source == "relation_cards_jsonl":
        for path in (item.get("source_path"), item.get("target_path")):
            if _valid_navigation_path(path):
                return path
        return None
    path = item.get("path")
    return path if _valid_navigation_path(path) else None


def _navigation_hint(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict) or item.get("source") == "diff":
        return None
    path = _navigation_path(item)
    if path is None:
        return None
    source = item.get("source")
    hint = {"path": path[:500], "source": str(source)[:64],
            "claim_level": "bundle_navigation_hint_not_verified_impact"}
    for key in ("line_range", "source_range", "range"):
        candidate = item.get(key)
        if isinstance(candidate, dict):
            a, b = candidate.get("start_line"), candidate.get("end_line")
            if type(a) is int and type(b) is int and 0 < a <= b:
                hint["range"] = {"start_line": a, "end_line": b}
                break
    return hint

def _bundle_navigation_hints(
    diff: str, bundle_manifest: str | Path | None, bundle: dict[str, Any],
    use_case: str, context_budget_tokens: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Existing delta compiler supplies suggestions, never impact truth."""
    hints: list[dict[str, Any]] = []
    gap_codes: list[str] = []
    try:
        delta = compile_delta_context(
            diff_text=diff, bundle_manifest=bundle_manifest if bundle["status"] == "available" else None,
            task=use_case, context_budget_tokens=context_budget_tokens,
            signal_k=8, context_window_lines=5,
        )
        if delta.get("status") == "invalid":
            gap_codes.append("delta_compiler_invalid")
        for item in delta.get("review_context", [])[:MAX_EVIDENCE_ITEMS * 4]:
            hint = _navigation_hint(item)
            if hint is None:
                continue
            hints.append(hint)
            if len(hints) >= MAX_EVIDENCE_ITEMS:
                break
        if delta.get("omitted_context"):
            gap_codes.append("context_budget_omitted_candidates")
        if delta.get("signal_quality") == "degraded":
            gap_codes.append("bundle_signal_degraded")
    except (OSError, TypeError, ValueError):
        gap_codes.append("bundle_hint_compiler_unavailable")
    return hints, gap_codes


def _changed_git_rows(parsed: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    changed: list[dict[str, Any]] = []
    hunks_truncated = False
    for item in parsed["files"][:MAX_CHANGED_FILES]:
        path = item.get("path")
        if not isinstance(path, str):
            continue
        ranges = []
        hunks = item.get("hunks", [])
        if len(hunks) > MAX_HUNKS_PER_FILE:
            hunks_truncated = True
        for hunk in hunks[:MAX_HUNKS_PER_FILE]:
            if not isinstance(hunk, dict):
                continue
            candidate = hunk.get("new_range")
            if not isinstance(candidate, dict):
                continue
            start, end = candidate.get("start_line"), candidate.get("end_line")
            if type(start) is int and type(end) is int and 0 < start <= end:
                ranges.append({"start_line": start, "end_line": end})
        changed.append({
            "path": path, "change_status": item.get("change_status"),
            "ranges": ranges, "claim_level": "direct_git_diff",
        })
    return changed, hunks_truncated


def _case_candidates_and_gaps(
    root: Path, target_revision: str, use_case: str,
    changed: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    test_candidates: list[dict[str, Any]] = []
    gap_codes: list[str] = []
    if use_case in {"explain-change", "find-related-tests"}:
        test_candidates, test_gap = _test_candidates(
            root, target_revision, [item["path"] for item in changed],
        )
        if test_gap:
            gap_codes.append(test_gap)
    if use_case == "find-related-tests":
        gap_codes.append("test_coverage_unverified")
    if use_case == "contract-impact":
        gap_codes.append("contract_consumer_relations_unverified")
    if use_case == "cross-repo-impact":
        gap_codes.append("cross_repository_relations_unverified")
    return test_candidates, gap_codes


def _build_evidence_pack_bound(
    *,
    repo_root: str | Path,
    base_revision: str,
    target_revision: str,
    bundle_manifest: str | Path | None = None,
    use_case: str = "explain-change",
    context_budget_tokens: int = 1_200,
    expected_diff_sha256: str | None = None,
) -> dict[str, Any]:
    """Build deterministic hints, not an interpretation or an execution order."""
    problem = _request_error(
        use_case, context_budget_tokens, base_revision,
        target_revision, expected_diff_sha256,
    )
    if problem:
        return _invalid(problem)
    root = Path(repo_root).expanduser().resolve()
    if not root.is_dir():
        return _invalid("repository_not_found")
    delta, problem = _read_git_delta(root, base_revision, target_revision, expected_diff_sha256)
    if problem or delta is None:
        return _invalid(problem or "diff_unavailable")
    diff, diff_sha, parsed = delta

    dirty, dirty_error = _bounded_git(root, ["status", "--porcelain", "--untracked-files=normal"])
    worktree_state = "unknown" if dirty_error else ("dirty" if dirty else "clean")
    bundle, gap_codes = _bundle_identity(bundle_manifest)
    gap_codes.extend(_bundle_revision_gaps(bundle, worktree_state, base_revision, target_revision))
    hints, hint_gaps = _bundle_navigation_hints(
        diff, bundle_manifest, bundle, use_case, context_budget_tokens,
    )
    gap_codes.extend(hint_gaps)
    changed, hunks_truncated = _changed_git_rows(parsed)
    if hunks_truncated:
        gap_codes.append("hunk_range_display_limit")
    if parsed["file_count"] > MAX_CHANGED_FILES:
        gap_codes.append("changed_file_display_limit")
    changed_contracts = [
        {"path": item["path"], "claim_level": "direct_git_diff"}
        for item in changed if _is_explicit_contract_path(item["path"])
    ]
    test_candidates, case_gaps = _case_candidates_and_gaps(
        root, target_revision, use_case, changed,
    )
    gap_codes.extend(case_gaps)

    result = {
        "kind": KIND, "version": VERSION, "status": "warn" if gap_codes else "pass",
        "use_case": use_case,
        "revision": {
            "base": base_revision, "target": target_revision, "diff_sha256": diff_sha,
            "worktree": worktree_state, "source": "local_git_read_only",
        },
        "bundle": bundle, "changed_files": changed,
        "changed_file_count": parsed["file_count"],
        "change_status_counts": parsed["change_status_counts"],
        "changed_contracts": changed_contracts,
        "test_candidates": test_candidates,
        "hints": hints,
        "gaps": [{"code": code} for code in sorted(set(gap_codes))],
        "limits": {"max_diff_bytes": MAX_DIFF_BYTES,
                   "max_changed_files": MAX_CHANGED_FILES,
                   "max_hunks_per_file": MAX_HUNKS_PER_FILE,
                   "max_hints": MAX_EVIDENCE_ITEMS,
                   "max_test_candidates": MAX_TEST_CANDIDATES,
                   "context_budget_tokens": context_budget_tokens},
        "mutation_boundary": BOUNDARY, "does_not_establish": NOT_ESTABLISHED,
        "fallback": "Use git diff, rg, tests and CI directly; no snapshot is refreshed.",
    }
    result["response_sha256"] = hashlib.sha256(_json_bytes(result)).hexdigest()
    return result


def build_evidence_pack(
    *,
    repo_root: str | Path,
    base_revision: str,
    target_revision: str,
    bundle_manifest: str | Path | None = None,
    use_case: str = "explain-change",
    context_budget_tokens: int = 1_200,
    expected_diff_sha256: str | None = None,
) -> dict[str, Any]:
    """Pin one manifest for the complete CLI/core invocation, not only MCP.

    Both manifest metadata and delta navigation must share the same request
    snapshot even if a mutable selected symlink moves while Git is read.
    The explicit no-bundle Git-only fallback remains available.
    """
    kwargs = {
        "repo_root": repo_root, "base_revision": base_revision,
        "target_revision": target_revision, "bundle_manifest": bundle_manifest,
        "use_case": use_case, "context_budget_tokens": context_budget_tokens,
        "expected_diff_sha256": expected_diff_sha256,
    }
    if bundle_manifest is None:
        return _build_evidence_pack_bound(**kwargs)
    try:
        snapshot = manifest_snapshot(bundle_manifest)
        with use_manifest_binding(snapshot.binding):
            return _build_evidence_pack_bound(**kwargs)
    except (ManifestBindingError, OSError, ValueError):
        return _invalid("manifest_not_readable")


def _append_markdown_section(
    lines: list[str], heading: str, rows: list[str], empty_note: str,
) -> None:
    lines.extend(["", heading])
    if rows:
        lines.extend(rows)
    else:
        lines.append(empty_note)


def render_evidence_markdown(pack: dict[str, Any]) -> str:
    """Render only the canonical JSON fields; no extra retrieval or side effects."""
    if pack.get("status") == "invalid":
        return "# RepoGround evidence unavailable\n\n" + str(pack.get("reason")) + "\n"
    rev = pack["revision"]
    lines = [
        "# RepoGround change evidence",
        "",
        f"Use case: {pack['use_case']} | Status: {pack['status']}",
        f"Base: {rev['base']}",
        f"Target: {rev['target']}",
        f"Diff SHA-256: {rev['diff_sha256']}",
        f"Worktree: {rev['worktree']}",
        f"Bundle SHA-256: {pack['bundle'].get('manifest_sha256', 'unavailable')}",
        f"Bundle source commit: {pack['bundle'].get('source_commit') or 'unknown'}",
        "",
        "## Direct changes (Git evidence)",
    ]
    for item in pack["changed_files"]:
        spans = ", ".join(f"{r['start_line']}-{r['end_line']}" for r in item["ranges"])
        lines.append(f"- {item['path']} ({item['change_status']}; lines: {spans or 'unknown'})")
    _append_markdown_section(
        lines, "## Tracked test-path candidates (not coverage evidence)",
        [f"- {item['path']} (name matches {item['source_path']})" for item in pack["test_candidates"]],
        "- No tracked exact-name candidates found",
    )
    _append_markdown_section(
        lines, "## Directly changed contract paths",
        [f"- {item['path']} (direct Git diff)" for item in pack["changed_contracts"]],
        "- No explicit contract paths in displayed changes",
    )
    _append_markdown_section(
        lines, "## Existing bundle navigation hints (not verified impact)",
        [f"- {item['path']} ({item['source']})" for item in pack["hints"]],
        "- No supported relationship candidates",
    )
    _append_markdown_section(
        lines, "## Gaps / limits",
        [f"- {item['code']}" for item in pack["gaps"]],
        "- No reported processing gaps; completeness is not established",
    )
    lines.extend(["", pack["fallback"],
                  "No review verdict, patch, merge permission or test sufficiency is established.",
                  f"Response SHA-256: {pack['response_sha256']}", ""])
    return "\n".join(lines)
