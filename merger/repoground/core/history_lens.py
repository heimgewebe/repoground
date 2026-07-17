from __future__ import annotations

from collections import defaultdict
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
