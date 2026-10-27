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

KIND = "repoground.agent_change_evidence"
VERSION = 1
MAX_DIFF_BYTES = 2_000_000
MAX_MANIFEST_BYTES = 4_000_000
MAX_CONTEXT_TOKENS = 4_000
MAX_CHANGED_FILES = 30
MAX_EVIDENCE_ITEMS = 12
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


def _bounded_git(root: Path, args: list[str], *, max_bytes: int = 131072) -> tuple[str | None, str | None]:
    """Use only Git builtins without hooks, network access or index locking.

    Bounded pipe reads stop very large diffs without materializing them or writing
    a temporary file. Commands are fixed by this module; no shell is involved.
    """
    command = [
        "git", "-c", "core.hooksPath=/dev/null",
        "-c", "core.fsmonitor=false", "-c", "diff.external=",
        "-c", "protocol.file.allow=never", "-C", str(root), *args,
    ]
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    process: subprocess.Popen[bytes] | None = None
    chunks = bytearray()
    error: str | None = None
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, env=env,
        )
        assert process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + 15.0
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    error = "git_timeout"
                    break
                ready = selector.select(min(left, 0.25))
                if not ready:
                    continue
                data = os.read(process.stdout.fileno(), 65536)
                if not data:
                    break
                chunks.extend(data)
                if len(chunks) > max_bytes:
                    error = "git_output_limit"
                    break
        if error:
            return None, error
        if process.wait(timeout=1) != 0:
            return None, "git_command_failed"
        try:
            return bytes(chunks).decode("utf-8"), None
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
    if path is None:
        return {"status": "unavailable", "reason": "no_bundle_supplied"}, ["no_bundle_supplied"]
    manifest = Path(path).expanduser().resolve()
    if not manifest.name.endswith(".bundle.manifest.json") or not manifest.is_file():
        return {"status": "invalid", "reason": "invalid_manifest"}, ["invalid_manifest"]
    if manifest.stat().st_size > MAX_MANIFEST_BYTES:
        return {"status": "invalid", "reason": "manifest_too_large"}, ["manifest_too_large"]
    try:
        raw = manifest.read_bytes()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("not a manifest object")
    except (OSError, UnicodeError, ValueError):
        return {"status": "invalid", "reason": "manifest_not_readable"}, ["manifest_not_readable"]
    provenance = data.get("snapshot_provenance") or {}
    repositories = provenance.get("repositories", []) if isinstance(provenance, dict) else []
    commits = sorted({
        row["git_commit"] for row in repositories
        if isinstance(row, dict) and isinstance(row.get("git_commit"), str)
        and _SHA40.fullmatch(row["git_commit"])
    }) if isinstance(repositories, list) else []
    return {
        "status": "available",
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "source_commit": commits[0] if len(commits) == 1 else None,
        "source_commit_binding": "unique" if len(commits) == 1 else "unknown_or_ambiguous",
    }, [] if len(commits) == 1 else ["bundle_source_revision_unknown"]


MAX_TEST_CANDIDATES = 12
MAX_TRACKED_PATHS_BYTES = 1_000_000


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
    by_name: dict[str, list[str]] = {}
    for relative in tracked.split("\0"):
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            continue
        basename = Path(relative).name
        if basename.startswith("test_") and basename.endswith(".py"):
            by_name.setdefault(basename, []).append(relative)
        elif basename.endswith("_test.py"):
            by_name.setdefault(basename, []).append(relative)
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


def _is_explicit_contract_path(path: str) -> bool:
    parts = Path(path).parts
    return "contracts" in parts or path.endswith((
        ".schema.json", ".jsonschema", ".proto", ".graphql",
        ".openapi.yaml", ".openapi.yml", ".openapi.json",
    ))


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
    """Build deterministic hints, not an interpretation or an execution order."""
    if use_case not in USE_CASES:
        return _invalid("unknown_use_case")
    if not isinstance(context_budget_tokens, int) or isinstance(context_budget_tokens, bool) or not 1 <= context_budget_tokens <= MAX_CONTEXT_TOKENS:
        return _invalid("invalid_budget")
    if not isinstance(base_revision, str) or not _SHA40.fullmatch(base_revision):
        return _invalid("base_must_be_exact_commit_sha")
    if not isinstance(target_revision, str) or not _SHA40.fullmatch(target_revision):
        return _invalid("target_must_be_exact_commit_sha")
    if expected_diff_sha256 is not None and (not isinstance(expected_diff_sha256, str) or not _SHA64.fullmatch(expected_diff_sha256)):
        return _invalid("invalid_expected_diff_sha256")
    root = Path(repo_root).expanduser().resolve()
    if not root.is_dir():
        return _invalid("repository_not_found")
    top, error = _bounded_git(root, ["rev-parse", "--show-toplevel"])
    if error or top is None or Path(top.strip()).resolve() != root:
        return _invalid("not_exact_git_root")
    for commit in (base_revision, target_revision):
        resolved, error = _bounded_git(root, ["rev-parse", "--verify", f"{commit}^{{commit}}"])
        if error or resolved is None or resolved.strip() != commit:
            return _invalid("unavailable_commit")
    diff, error = _bounded_git(
        root, ["diff", "--no-ext-diff", "--no-textconv", "--no-renames",
               "--unified=3", base_revision, target_revision, "--"],
        max_bytes=MAX_DIFF_BYTES,
    )
    if error or diff is None:
        return _invalid(error or "diff_unavailable")
    diff_sha = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    if expected_diff_sha256 is not None and expected_diff_sha256 != diff_sha:
        return _invalid("diff_sha256_mismatch")

    parsed = parse_unified_diff(diff)
    if not parsed["file_count"] or parsed.get("truncated"):
        return _invalid("empty_or_truncated_diff")
    dirty, dirty_error = _bounded_git(root, ["status", "--porcelain", "--untracked-files=normal"])
    worktree_state = "unknown" if dirty_error else ("dirty" if dirty else "clean")
    bundle, gap_codes = _bundle_identity(bundle_manifest)
    if worktree_state != "clean":
        gap_codes.append("worktree_" + worktree_state)
    source_commit = bundle.get("source_commit")
    if source_commit is not None and source_commit not in {base_revision, target_revision}:
        gap_codes.append("bundle_revision_not_in_diff")
    if source_commit is None and bundle.get("status") == "available":
        gap_codes.append("bundle_revision_unverified")

    # The existing delta compiler is the single source of retrieval hints.
    # Source text itself is not returned; these are navigational hints only.
    hints: list[dict[str, Any]] = []
    try:
        delta = compile_delta_context(
            diff_text=diff, bundle_manifest=bundle_manifest if bundle["status"] == "available" else None,
            task=use_case, context_budget_tokens=context_budget_tokens,
            signal_k=8, context_window_lines=5,
        )
        if delta.get("status") == "invalid":
            gap_codes.append("delta_compiler_invalid")
        for item in delta.get("review_context", [])[:MAX_EVIDENCE_ITEMS * 4]:
            if not isinstance(item, dict):
                continue
            source = item.get("source")
            if source == "diff":
                continue
            path = item.get("path")
            if not isinstance(path, str) or not path or path.startswith("/") or ".." in path.split("/"):
                continue
            hint = {"path": path[:500], "source": str(source)[:64],
                    "claim_level": "bundle_navigation_hint_not_verified_impact"}
            for key in ("line_range", "source_range", "range"):
                candidate = item.get(key)
                if isinstance(candidate, dict):
                    a, b = candidate.get("start_line"), candidate.get("end_line")
                    if type(a) is int and type(b) is int and 0 < a <= b:
                        hint["range"] = {"start_line": a, "end_line": b}
                        break
            hints.append(hint)
            if len(hints) >= MAX_EVIDENCE_ITEMS:
                break
        if delta.get("omitted_context"):
            gap_codes.append("context_budget_omitted_candidates")
        if delta.get("signal_quality") == "degraded":
            gap_codes.append("bundle_signal_degraded")
    except (OSError, TypeError, ValueError):
        gap_codes.append("bundle_hint_compiler_unavailable")

    changed = []
    for item in parsed["files"][:MAX_CHANGED_FILES]:
        path = item.get("path")
        if not isinstance(path, str):
            continue
        ranges = []
        for hunk in item.get("hunks", [])[:16]:
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
    if parsed["file_count"] > MAX_CHANGED_FILES:
        gap_codes.append("changed_file_display_limit")
    changed_contracts = [
        {"path": item["path"], "claim_level": "direct_git_diff"}
        for item in changed if _is_explicit_contract_path(item["path"])
    ]
    test_candidates: list[dict[str, Any]] = []
    if use_case in {"explain-change", "find-related-tests"}:
        test_candidates, test_gap = _test_candidates(
            root, target_revision, [item["path"] for item in changed],
        )
        if test_gap:
            gap_codes.append(test_gap)
    if use_case == "find-related-tests":
        # Even matching *tracked* test file names do not establish test coverage.
        gap_codes.append("test_coverage_unverified")
    if use_case == "contract-impact":
        gap_codes.append("contract_consumer_relations_unverified")
    if use_case == "cross-repo-impact":
        gap_codes.append("cross_repository_relations_unverified")

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
                   "max_hints": MAX_EVIDENCE_ITEMS,
                   "max_test_candidates": MAX_TEST_CANDIDATES,
                   "context_budget_tokens": context_budget_tokens},
        "mutation_boundary": BOUNDARY, "does_not_establish": NOT_ESTABLISHED,
        "fallback": "Use git diff, rg, tests and CI directly; no snapshot is refreshed.",
    }
    result["response_sha256"] = hashlib.sha256(_json_bytes(result)).hexdigest()
    return result


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
    lines.extend(["", "## Tracked test-path candidates (not coverage evidence)"])
    for item in pack["test_candidates"]:
        lines.append(f"- {item['path']} (name matches {item['source_path']})")
    if not pack["test_candidates"]:
        lines.append("- No tracked exact-name candidates found")
    lines.extend(["", "## Directly changed contract paths"])
    for item in pack["changed_contracts"]:
        lines.append(f"- {item['path']} (direct Git diff)")
    if not pack["changed_contracts"]:
        lines.append("- No explicit contract paths in displayed changes")
    lines.extend(["", "## Existing bundle navigation hints (not verified impact)"])
    for item in pack["hints"]:
        lines.append(f"- {item['path']} ({item['source']})")
    if not pack["hints"]:
        lines.append("- No supported relationship candidates")
    lines.extend(["", "## Gaps / limits"])
    for item in pack["gaps"]:
        lines.append(f"- {item['code']}")
    if not pack["gaps"]:
        lines.append("- No reported processing gaps; completeness is not established")
    lines.extend(["", pack["fallback"],
                  "No review verdict, patch, merge permission or test sufficiency is established.",
                  f"Response SHA-256: {pack['response_sha256']}", ""])
    return "\n".join(lines)