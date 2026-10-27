from __future__ import annotations

from collections import defaultdict
import ast
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time
from typing import Any, Iterable, Mapping

KIND = "repobrief.history_lens"
VERSION = "1.0"
PROFILES = ("disabled", "summary", "full")
DOES_NOT_ESTABLISH = [
    "canonical_content_truth",
    "person_blame",
    "ownership_verdict",
    "correctness",
    "completeness",
    "live_github_state",
    "ci_state",
    "pull_request_state",
    "merge_readiness",
    "security_correctness",
]
FORBIDDEN_VERDICTS = [
    "person_blame",
    "ownership",
    "correctness",
    "completeness",
    "merge_readiness",
]


def _record_path(record: Mapping[str, Any]) -> str | None:
    path = record.get("path") or record.get("file_path")
    return str(path) if isinstance(path, str) and path else None


def _commit_id(record: Mapping[str, Any]) -> str | None:
    commit = record.get("commit") or record.get("commit_sha") or record.get("sha")
    return str(commit) if isinstance(commit, str) and commit else None


def _public_record(record: Mapping[str, Any], *, include_author_metadata: bool) -> dict[str, Any]:
    item: dict[str, Any] = {}
    for key in ("commit", "commit_sha", "sha", "pr", "pull_request", "path", "file_path", "summary"):
        value = record.get(key)
        if isinstance(value, (str, int, float, bool)):
            item[key] = value
    if include_author_metadata:
        for key in ("author", "author_email", "committer"):
            value = record.get(key)
            if isinstance(value, str):
                item[key] = value
    return item


def build_history_lens(
    records: Iterable[Mapping[str, Any]],
    *,
    profile: str = "summary",
    include_author_metadata: bool = False,
) -> dict[str, Any]:
    """Build a derived history navigation surface from explicit history records.

    This function does not call Git or GitHub. It only summarizes records supplied by
    the caller and marks the result as derived navigation/diagnosis, not canonical truth.
    """
    if profile not in PROFILES:
        raise ValueError(f"unsupported history lens profile: {profile}")
    if profile == "disabled":
        return {
            "kind": KIND,
            "version": VERSION,
            "status": "not_applicable",
            "profile": profile,
            "derived_navigation": True,
            "canonical_content_truth": False,
            "export_policy": {
                "profile": profile,
                "history_metadata_included": False,
                "author_metadata_included": False,
                "allowed_profiles": list(PROFILES),
            },
            "file_churn": [],
            "provenance_chains": [],
            "forbidden_verdicts": list(FORBIDDEN_VERDICTS),
            "live_state_boundary": "Use live GitHub/CI/PR checks for current work; History Lens does not replace them.",
            "does_not_establish": list(DOES_NOT_ESTABLISH),
        }

    churn: dict[str, set[str]] = defaultdict(set)
    provenance: list[dict[str, Any]] = []
    for record in records:
        path = _record_path(record)
        commit = _commit_id(record)
        if path and commit:
            churn[path].add(commit)
        if profile == "full":
            public = _public_record(record, include_author_metadata=include_author_metadata)
            if public:
                provenance.append(public)

    file_churn = [
        {"path": path, "commit_count": len(commits), "navigation_only": True}
        for path, commits in sorted(churn.items())
    ]
    return {
        "kind": KIND,
        "version": VERSION,
        "status": "ok",
        "profile": profile,
        "derived_navigation": True,
        "canonical_content_truth": False,
        "export_policy": {
            "profile": profile,
            "history_metadata_included": True,
            "author_metadata_included": bool(include_author_metadata),
            "allowed_profiles": list(PROFILES),
        },
        "file_churn": file_churn,
        "provenance_chains": provenance,
        "forbidden_verdicts": list(FORBIDDEN_VERDICTS),
        "live_state_boundary": "Use live GitHub/CI/PR checks for current work; History Lens does not replace them.",
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }

# Thread 2: an on-demand, revision-addressed Git projection. It is deliberately
# not a second persisted history index, and never refreshes a repo or a bundle.

_TIMELINE_KIND = "repoground.git-history"
_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_REPO_RE = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
_MAX_GIT_BYTES = 2_000_000
_MAX_TREE_ROWS = 4096
_MAX_PUBLIC_ROWS = 256
_MAX_SYMBOL_FILES = 20


def _read_bounded_git_stdout(proc: subprocess.Popen[bytes], max_bytes: int, deadline: float) -> bytes:
    """Drain at most max_bytes+1 bytes directly from the pipe, never buffering more."""
    assert proc.stdout is not None
    chunks: list[bytes] = []
    used = 0
    with selectors.DefaultSelector() as selector:
        selector.register(proc.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise ValueError("Git read timed out")
            chunk = os.read(proc.stdout.fileno(), min(65_536, max_bytes + 1 - used))
            if not chunk:
                return b"".join(chunks)
            used += len(chunk)
            if used > max_bytes:
                raise ValueError("Git evidence exceeds bounded read limit")
            chunks.append(chunk)


def _git_read(repo: Path, *arguments: str, max_bytes: int = _MAX_GIT_BYTES) -> bytes:
    """Strictly bounded local Git read: no lazy fetch, unbounded pipe or shell."""
    if not isinstance(max_bytes, int) or not 1 <= max_bytes <= _MAX_GIT_BYTES:
        raise ValueError("Git read output budget is invalid")
    env = os.environ.copy()
    env.update({
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_LITERAL_PATHSPECS": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    })
    proc = subprocess.Popen(
        ["git", "--no-optional-locks", "-c", "core.hooksPath=/dev/null",
         "-c", "diff.external=", "-C", str(repo), *arguments],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env=env, start_new_session=True,
    )
    complete = False
    deadline = time.monotonic() + 15
    try:
        output = _read_bounded_git_stdout(proc, max_bytes, deadline)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Git read timed out")
        try:
            code = proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Git read timed out") from exc
        if code:
            raise ValueError("Git source unavailable or revision could not be verified")
        complete = True
        return output
    finally:
        if not complete:
            # The Git process is in its own session so spawned children are
            # terminated as well. Reap the leader on every error path.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=2)
        finally:
            if proc.stdout is not None:
                proc.stdout.close()


def _repo_root(repo: Path) -> Path:
    root = Path(repo).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Git repository must be an existing directory")
    actual = Path(_git_read(root, "rev-parse", "--show-toplevel").decode().strip()).resolve(strict=True)
    if actual != root:
        raise ValueError("Git root must be explicit, not a subdirectory")
    return root


def _repo_id(repo_id: str) -> str:
    if not isinstance(repo_id, str) or not _REPO_RE.fullmatch(repo_id):
        raise ValueError("repo_id must be a bounded literal repository identifier")
    return repo_id


def _revision(root: Path, revision: str) -> str:
    if not isinstance(revision, str) or not _SHA_RE.fullmatch(revision):
        raise ValueError("commit must be a full lowercase Git object ID")
    return _git_read(root, "rev-parse", "--verify", "--end-of-options",
                     f"{revision}^{{commit}}").decode().strip()


class _GitBlobTree(dict[str, str]):
    """Git blob OIDs with Git tree modes kept together for exact deltas."""

    def __init__(self) -> None:
        super().__init__()
        self.modes: dict[str, str] = {}


def _git_tree(root: Path, commit: str) -> tuple[_GitBlobTree, bool]:
    raw = _git_read(root, "ls-tree", "-r", "-z", commit)
    tree = _GitBlobTree()
    skipped = False
    for index, row in enumerate(raw.split(b"\0")):
        if not row:
            continue
        if index >= _MAX_TREE_ROWS:
            skipped = True
            break
        metadata, separator, raw_path = row.partition(b"\t")
        if not separator:
            continue
        parts = metadata.decode("ascii", "strict").split()
        if len(parts) != 3 or parts[1] != "blob" or parts[0] == "120000":
            # A submodule or symlink is not treated as a traversable file.
            skipped = True
            continue
        path = raw_path.decode("utf-8", "surrogateescape")
        if path.startswith(".git/"):
            continue
        tree[path] = parts[2]
        tree.modes[path] = parts[0]
    return tree, skipped


def _artifact_type(path: str) -> str:
    if "contracts/" in path or path.endswith(".schema.json"):
        return "contract"
    if path.endswith((".nix", ".yaml", ".yml", ".toml", ".json", ".ini", ".cfg")):
        return "config"
    return "source"


def _symbol_names(root: Path, oid: str) -> list[str] | None:
    try:
        raw = _git_read(root, "cat-file", "blob", oid, max_bytes=250_000)
        source = ast.parse(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, SyntaxError, RecursionError):
        return None
    names = set()
    def visit(node: ast.AST, prefix: str = "") -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + child.name
                names.add(name)
                visit(child, name + ".")
            else:
                visit(child, prefix)
    try:
        visit(source)
    except RecursionError:
        # A valid but deeply nested AST must not abort the entire Git delta.
        return None
    if len(names) > 1000:
        # Truncated before/after sets can manufacture symbol removals. Withhold
        # symbol comparisons rather than claiming a complete inventory.
        return None
    return sorted(names)


def git_revision_view(repository: Path, repo_id: str, commit: str) -> dict[str, Any]:
    """Answer 'what existed at SHA?' from Git objects, not the working tree."""
    root = _repo_root(repository)
    repo_id = _repo_id(repo_id)
    sha = _revision(root, commit)
    tree, limited = _git_tree(root, sha)
    paths = sorted(tree)
    return {
        "kind": _TIMELINE_KIND, "version": "1", "operation": "revision",
        "status": "partial" if limited or len(paths) > _MAX_PUBLIC_ROWS else "ok",
        "repo_id": repo_id, "source_commit": sha,
        "committer_time_reported": _git_read(root, "show", "-s", "--format=%cI", sha).decode().strip(),
        "observation_time": None, "publication_time": None,
        "files_total_observed": len(paths),
        "artifacts": [
            {"path": p, "blob_oid": tree[p], "mode": tree.modes[p],
             "artifact_type": _artifact_type(p),
             "source_commit": sha, "origin": "git_tree", "confidence": "observed"}
            for p in paths[:_MAX_PUBLIC_ROWS]
        ],
        "gaps": (["tree_capped_or_non_file_entries"] if limited else []) +
                (["public_artifact_limit"] if len(paths) > _MAX_PUBLIC_ROWS else []),
        "does_not_establish": ["runtime_deployment", "test_result", "causality", "future_revisions"],
    }


def git_revision_delta(repository: Path, repo_id: str, base: str, head: str) -> dict[str, Any]:
    """Bounded material Git tree delta, with transient Python AST name changes."""
    root = _repo_root(repository)
    repo_id = _repo_id(repo_id)
    old_sha, new_sha = _revision(root, base), _revision(root, head)
    before, limited_before = _git_tree(root, old_sha)
    after, limited_after = _git_tree(root, new_sha)
    # An incomplete tree cannot prove that an absent path was removed. Do not
    # emit fabricated added/removed edges from two truncated inventories.
    if limited_before or limited_after:
        return {
            "kind": _TIMELINE_KIND, "version": "1", "operation": "delta",
            "status": "partial", "repo_id": repo_id,
            "base_commit": old_sha, "head_commit": new_sha,
            "source_revision_time": {
                "base_committer_reported": _git_read(root, "show", "-s", "--format=%cI", old_sha).decode().strip(),
                "head_committer_reported": _git_read(root, "show", "-s", "--format=%cI", new_sha).decode().strip(),
            },
            "observation_time": None, "publication_time": None,
            "changed_files_observed": None,
            "file_changes": [], "python_symbol_changes": [],
            "gaps": ["git_tree_incomplete_delta_omitted"],
            "does_not_establish": [
                "any_file_change", "absence_of_changes", "runtime_impact",
                "canonical_dependency_resolution", "test_result", "causality"
            ],
        }
    changed = [
        p for p in sorted(before.keys() | after.keys())
        if (before.get(p), before.modes.get(p)) != (after.get(p), after.modes.get(p))
    ]
    file_changes = []
    symbol_changes = []
    gaps = []
    for p in changed[:_MAX_PUBLIC_ROWS]:
        original, current = before.get(p), after.get(p)
        action = "added" if original is None else "removed" if current is None else "modified"
        file_changes.append({
            "path": p, "action": action, "artifact_type": _artifact_type(p),
            "before_blob_oid": original, "after_blob_oid": current,
            "before_mode": before.modes.get(p), "after_mode": after.modes.get(p),
            "before_commit": old_sha, "after_commit": new_sha,
            "evidence_type": (
                "git_tree_oid_comparison" if original != current
                else "git_tree_mode_comparison"
            ),
        })
    for p in (p for p in changed if p.endswith(".py") and before.get(p) != after.get(p)):
        if len(symbol_changes) >= _MAX_SYMBOL_FILES:
            gaps.append("python_ast_file_limit")
            break
        old_names = _symbol_names(root, before[p]) if p in before else []
        new_names = _symbol_names(root, after[p]) if p in after else []
        if old_names is None or new_names is None:
            gaps.append("python_ast_unavailable:" + p)
            continue
        symbol_changes.append({
            "path": p, "added": sorted(set(new_names) - set(old_names)),
            "removed": sorted(set(old_names) - set(new_names)),
            "analysis": "transient_python_ast_names_not_canonical_symbol_graph",
        })
    if limited_before or limited_after:
        gaps.append("git_tree_capped_or_non_file_entries")
    if len(changed) > _MAX_PUBLIC_ROWS:
        gaps.append("file_changes_public_limit")
    return {
        "kind": _TIMELINE_KIND, "version": "1", "operation": "delta",
        "status": "partial" if gaps else "ok",
        "repo_id": repo_id, "base_commit": old_sha, "head_commit": new_sha,
        "source_revision_time": {
            "base_committer_reported": _git_read(root, "show", "-s", "--format=%cI", old_sha).decode().strip(),
            "head_committer_reported": _git_read(root, "show", "-s", "--format=%cI", new_sha).decode().strip(),
        },
        "observation_time": None, "publication_time": None,
        "changed_files_observed": len(changed),
        "file_changes": file_changes, "python_symbol_changes": symbol_changes,
        "gaps": sorted(set(gaps)),
        "does_not_establish": [
            "runtime_impact", "canonical_dependency_resolution", "test_result", "causality"
        ],
    }


def git_path_history(repository: Path, repo_id: str, commit: str,
                     path: str, limit: int = 30) -> dict[str, Any]:
    """Return explicit earlier commits touching a path, never a causal verdict."""
    root = _repo_root(repository)
    _repo_id(repo_id)
    sha = _revision(root, commit)
    if (not isinstance(path, str) or not path or path.startswith("/") or
            "\\" in path or "\0" in path or ".." in Path(path).parts or
            path.startswith(".git/")):
        raise ValueError("path must be a safe relative Git pathname")
    if not isinstance(limit, int) or limit < 1 or limit > 50:
        raise ValueError("history limit must be 1..50")
    output = _git_read(root, "log", f"--max-count={limit}", "--format=%H%x09%cI",
                       sha, "--", path).decode()
    entries = []
    for line in output.splitlines():
        event_sha, separator, reported_time = line.partition("\t")
        if separator and _SHA_RE.fullmatch(event_sha):
            entries.append({"commit": event_sha, "committer_time_reported": reported_time,
                            "evidence": "git_path_history", "causality": "unknown"})
    return {"kind": _TIMELINE_KIND, "version": "1", "operation": "path_history",
            "status": "ok", "repo_id": repo_id, "source_commit": sha,
            "path": path, "history": entries, "history_limit": limit,
            "observation_time": None, "does_not_establish": ["why_change_happened", "pr_or_ci_outcome"]}


def bind_external_history(repository: Path, repo_id: str, commit: str,
                          records: Iterable[Mapping[str, Any]],
                          path: str | None = None) -> dict[str, Any]:
    """Bind *caller-provided* primary-source references to verified Git history.

    Does not call external APIs, infer PR/CI success, store event bodies or
    manufacture timestamps. Producer/permission verification is the caller's job.
    """
    root = _repo_root(repository)
    repo_id = _repo_id(repo_id)
    sha = _revision(root, commit)
    relevant_commits = {sha}
    if path is not None:
        history = git_path_history(root, repo_id, sha, path)
        relevant_commits.update(event["commit"] for event in history["history"])
    allowed = {"commit", "pr", "ci", "test", "chronik", "operator_receipt", "runtime_snapshot"}
    ref_pattern = re.compile(r"(?:https://github\.com/[A-Za-z0-9_./#-]+|(?:github|chronik|grabowski|ci):[A-Za-z0-9_./:#-]+)\Z")
    matched = []
    gaps: list[str] = []
    for n, record in enumerate(records):
        if n >= 100:
            gaps.append("event_limit")
            break
        if not isinstance(record, Mapping):
            gaps.append("invalid_event_record")
            continue
        kind = record.get("event_kind")
        event_sha = record.get("commit")
        evidence_ref = record.get("evidence_ref")
        if kind not in allowed or not isinstance(event_sha, str) or not _SHA_RE.fullmatch(event_sha):
            gaps.append("event_identity_missing")
            continue
        if record.get("repo_id") != repo_id:
            gaps.append("event_repo_mismatch")
            continue
        if not isinstance(evidence_ref, str) or not ref_pattern.fullmatch(evidence_ref):
            gaps.append("event_evidence_ref_rejected")
            continue
        if event_sha not in relevant_commits:
            gaps.append("event_sha_outside_explicit_history")
            continue
        matched.append({
            "event_kind": kind, "repo_id": repo_id, "commit": event_sha,
            "evidence_ref": evidence_ref,
            "reported_event_time": record.get("event_time") if isinstance(record.get("event_time"), str)
                                   and re.fullmatch(r"\d{4}-\d{2}-\d{2}T[A-Za-z0-9:+.-]{1,50}",
                                                    record["event_time"]) else None,
            "relation": "exact_commit" if event_sha == sha else "same_path_history",
            "verification": "git_commit_match_only;external_source_not_refreshed",
            "causality": "unknown",
        })
    matched.sort(key=lambda x: (x["commit"], x["event_kind"], x["evidence_ref"]))
    return {
        "kind": "repoground.external-history-links", "version": "1",
        "status": "partial" if gaps else ("ok" if matched else "unavailable"),
        "repo_id": repo_id, "source_commit": sha, "path": path,
        "events": matched, "gaps": sorted(set(gaps)),
        "observation_time": None, "publication_time": None,
        "does_not_establish": [
            "external_event_authenticity", "pr_state", "ci_success",
            "runtime_state", "causality", "relevance_beyond_exact_commit_or_path"
        ],
    }