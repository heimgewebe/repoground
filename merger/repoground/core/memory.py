from __future__ import annotations

import copy
import re
from typing import Any, Mapping, Sequence

KIND = "repobrief.agent_memory_claim"
VERSION = "v1"
RECALL_CHECK_KIND = "repobrief.agent_memory_recall_check"
USABLE_FRESHNESS_STATUSES = ("fresh",)
_CITATION_ID_RE = re.compile(r"^cit_[a-f0-9]{16}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

DOES_NOT_ESTABLISH = (
    "truth",
    "correctness",
    "completeness",
    "runtime_behavior",
    "test_sufficiency",
    "regression_absence",
    "repo_understood",
    "claims_true",
    "forensic_ready",
    "freshness_against_remote",
    "merge_readiness",
)

RECALL_REQUIREMENTS = (
    "memory_record_kind_and_version_are_valid",
    "claim_text_is_non_empty",
    "current_snapshot_hash_matches_recorded_snapshot_hash",
    "current_freshness_status_is_fresh",
    "all_recorded_citation_ids_are_present",
    "all_recorded_citation_records_are_valid",
    "all_recorded_citation_range_hashes_match",
    "all_recorded_citation_range_identities_match",
    "no_citation_id_conflicts",
)


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _is_int_not_bool(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _citation_id_is_valid(value: Any) -> bool:
    return isinstance(value, str) and _CITATION_ID_RE.fullmatch(value) is not None


def _copy_mapping(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return copy.deepcopy(dict(value))


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _range_hash(range_value: Mapping[str, Any] | None) -> str | None:
    if not isinstance(range_value, Mapping):
        return None
    for key in ("range_content_sha256", "content_sha256"):
        value = range_value.get(key)
        if _is_sha256(value):
            return str(value)
    value = range_value.get("sha256")
    if _is_sha256(value) and range_value.get("hash_basis") == "range_content":
        return str(value)
    return None


def _range_identity(range_value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(range_value, Mapping):
        return None
    file_path = _first_not_none(range_value.get("file_path"), range_value.get("artifact_path"))
    start_byte = _first_not_none(range_value.get("start_byte"), range_value.get("artifact_start_byte"))
    end_byte = _first_not_none(range_value.get("end_byte"), range_value.get("artifact_end_byte"))
    if not _is_non_empty_string(file_path):
        return None
    if not _is_int_not_bool(start_byte) or not _is_int_not_bool(end_byte):
        return None
    if start_byte < 0 or end_byte <= start_byte:
        return None
    content_sha256 = _range_hash(range_value)
    if content_sha256 is None:
        return None
    identity: dict[str, Any] = {
        "file_path": str(file_path),
        "start_byte": int(start_byte),
        "end_byte": int(end_byte),
        "content_sha256": content_sha256,
    }
    repo_id = range_value.get("repo_id")
    if _is_non_empty_string(repo_id):
        identity["repo_id"] = str(repo_id)
    start_line = _first_not_none(range_value.get("start_line"), range_value.get("artifact_start_line"))
    end_line = _first_not_none(range_value.get("end_line"), range_value.get("artifact_end_line"))
    if (
        _is_int_not_bool(start_line)
        and _is_int_not_bool(end_line)
        and start_line >= 1
        and end_line >= start_line
    ):
        identity["start_line"] = int(start_line)
        identity["end_line"] = int(end_line)
    source_file_path = range_value.get("source_file_path")
    if _is_non_empty_string(source_file_path):
        identity["source_file_path"] = str(source_file_path)
        source_start_line = range_value.get("source_start_line")
        source_end_line = range_value.get("source_end_line")
        if (
            _is_int_not_bool(source_start_line)
            and _is_int_not_bool(source_end_line)
            and source_start_line >= 1
            and source_end_line >= source_start_line
        ):
            identity["source_start_line"] = int(source_start_line)
            identity["source_end_line"] = int(source_end_line)
    return identity


def _candidate_ranges(citation: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = []
    for key in ("source_range", "citation_range", "canonical_range", "range"):
        value = citation.get(key)
        if isinstance(value, Mapping):
            candidates.append(value)
    return candidates


def _normalize_memory_citation(citation: Mapping[str, Any]) -> dict[str, Any]:
    citation_id = citation.get("citation_id")
    if not _citation_id_is_valid(citation_id):
        raise ValueError("citation_id must match cit_[a-f0-9]{16}")
    source_range = None
    raw_source_range = None
    for candidate in _candidate_ranges(citation):
        identity = _range_identity(candidate)
        if identity is not None:
            source_range = identity
            raw_source_range = _copy_mapping(candidate)
            break
    if source_range is None:
        raise ValueError("citation must include a range with file_path, byte bounds and content sha256")
    repo_id = citation.get("repo_id")
    if _is_non_empty_string(repo_id):
        source_range = dict(source_range)
        source_range["repo_id"] = str(repo_id)
    normalized: dict[str, Any] = {
        "citation_id": citation_id,
        "source_range": source_range,
        "range_content_sha256": source_range["content_sha256"],
    }
    for key in ("chunk_id", "path", "repo_id"):
        value = citation.get(key)
        if _is_non_empty_string(value):
            normalized[key] = value
    citation_range = _copy_mapping(citation.get("citation_range") or citation.get("canonical_range"))
    if citation_range is not None:
        normalized["citation_range"] = citation_range
    if raw_source_range is not None:
        normalized["recorded_range"] = raw_source_range
    return normalized


def _duplicate_citation_ids(citations: Sequence[Mapping[str, Any]]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for citation in citations:
        citation_id = citation.get("citation_id")
        if not isinstance(citation_id, str):
            continue
        if citation_id in seen:
            duplicates.add(citation_id)
        else:
            seen.add(citation_id)
    return duplicates


def citation_from_projection_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a source-citation projection item into a memory citation.

    Projection items are navigation evidence. This helper keeps only the
    stable citation id and a hash-bearing range identity needed for later
    recall revalidation.
    """

    if item.get("citation_resolved") is not True:
        raise ValueError("projection item is not resolved")
    citation_id = item.get("citation_id")
    if not _citation_id_is_valid(citation_id):
        raise ValueError("projection item does not carry a valid citation_id")
    source_range = item.get("source_range")
    if not isinstance(source_range, Mapping):
        raise ValueError("projection item does not carry source_range")
    return _normalize_memory_citation({
        "citation_id": citation_id,
        "chunk_id": item.get("chunk_id"),
        "path": item.get("path"),
        "repo_id": item.get("repo_id"),
        "source_range": source_range,
        "citation_range": item.get("citation_range"),
    })


def build_memory_record(
    *,
    claim_text: str,
    citations: Sequence[Mapping[str, Any]],
    snapshot_stem: str,
    snapshot_hash: str,
    freshness_status: str,
    stored_at: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a durable-memory record that remains citation-bound.

    The record is deliberately not a truth object. It stores the remembered
    claim plus enough citation and snapshot identity to force a recall-time
    freshness/hash check before an agent can reuse the claim.
    """

    if not _is_non_empty_string(claim_text):
        raise ValueError("claim_text must be a non-empty string")
    if not _is_non_empty_string(snapshot_stem):
        raise ValueError("snapshot_stem must be a non-empty string")
    if not _is_sha256(snapshot_hash):
        raise ValueError("snapshot_hash must be a sha256 hex digest")
    if not _is_non_empty_string(freshness_status):
        raise ValueError("freshness_status must be a non-empty string")
    normalized_citations = [_normalize_memory_citation(citation) for citation in citations]
    if not normalized_citations:
        raise ValueError("at least one citation is required")
    duplicate_ids = _duplicate_citation_ids(normalized_citations)
    if duplicate_ids:
        duplicate_list = ", ".join(sorted(duplicate_ids))
        raise ValueError(f"duplicate citation_id values are not allowed: {duplicate_list}")
    record: dict[str, Any] = {
        "kind": KIND,
        "version": VERSION,
        "status": "recorded_requires_recall_check",
        "claim_text": claim_text,
        "evidence": {
            "snapshot": {
                "stem": snapshot_stem,
                "hash": snapshot_hash,
                "freshness_status": freshness_status,
            },
            "citations": normalized_citations,
        },
        "recall_policy": {
            "requires_revalidation": True,
            "usable_only_when": list(RECALL_REQUIREMENTS),
            "memory_is_never_source_truth_without_verified_citations": True,
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    if stored_at is not None:
        record["stored_at"] = stored_at
    if metadata is not None:
        record["metadata"] = copy.deepcopy(dict(metadata))
    return record


def memory_record_from_projection(
    *,
    claim_text: str,
    source_citation_projection: Mapping[str, Any],
    snapshot_stem: str,
    snapshot_hash: str,
    freshness_status: str,
    stored_at: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    items = source_citation_projection.get("items")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise ValueError("source_citation_projection.items must be a sequence")
    unresolved_count = 0
    malformed_count = 0
    citations = []
    for item in items:
        if not isinstance(item, Mapping):
            malformed_count += 1
            continue
        if item.get("citation_resolved") is not True:
            unresolved_count += 1
            continue
        citations.append(citation_from_projection_item(item))
    if malformed_count:
        raise ValueError("source_citation_projection.items must contain only mappings")
    if unresolved_count:
        raise ValueError("source_citation_projection contains unresolved citations")
    return build_memory_record(
        claim_text=claim_text,
        citations=citations,
        snapshot_stem=snapshot_stem,
        snapshot_hash=snapshot_hash,
        freshness_status=freshness_status,
        stored_at=stored_at,
        metadata=metadata,
    )


def _citation_lookup(
    current_citations: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> tuple[dict[str, Mapping[str, Any]], set[str]]:
    lookup: dict[str, Mapping[str, Any]] = {}
    conflicts: set[str] = set()
    if current_citations is None:
        return lookup, conflicts
    if isinstance(current_citations, Mapping):
        for key, value in current_citations.items():
            if not isinstance(key, str) or not isinstance(value, Mapping):
                continue
            inner_id = value.get("citation_id")
            if inner_id not in (None, key):
                conflicts.add(key)
                if isinstance(inner_id, str):
                    conflicts.add(inner_id)
            lookup[key] = value
        return lookup, conflicts
    if isinstance(current_citations, Sequence) and not isinstance(current_citations, (str, bytes)):
        for citation in current_citations:
            if not isinstance(citation, Mapping):
                continue
            citation_id = citation.get("citation_id")
            if not isinstance(citation_id, str):
                continue
            if citation_id in lookup:
                conflicts.add(citation_id)
                continue
            lookup[citation_id] = citation
    return lookup, conflicts


def _current_range_hash(citation: Mapping[str, Any] | None) -> str | None:
    if citation is None:
        return None
    for candidate in _candidate_ranges(citation):
        content_hash = _range_hash(candidate)
        if content_hash is not None:
            return content_hash
    content_hash = citation.get("range_content_sha256") or citation.get("content_sha256")
    return str(content_hash) if _is_sha256(content_hash) else None


def _current_range_identity(citation: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if citation is None:
        return None
    for candidate in _candidate_ranges(citation):
        identity = _range_identity(candidate)
        if identity is not None:
            repo_id = citation.get("repo_id")
            if _is_non_empty_string(repo_id):
                identity = dict(identity)
                identity["repo_id"] = str(repo_id)
            return identity
    return None


def _range_identity_matches(recorded: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    for key in ("file_path", "start_byte", "end_byte", "content_sha256"):
        if recorded.get(key) != current.get(key):
            return False
    for key in (
        "repo_id",
        "start_line",
        "end_line",
        "source_file_path",
        "source_start_line",
        "source_end_line",
    ):
        if key in recorded or key in current:
            if recorded.get(key) != current.get(key):
                return False
    return True


def _stored_range_identity_is_valid(identity: Mapping[str, Any] | None) -> bool:
    if not isinstance(identity, Mapping):
        return False
    if not _is_non_empty_string(identity.get("file_path")):
        return False
    if not _is_int_not_bool(identity.get("start_byte")) or not _is_int_not_bool(identity.get("end_byte")):
        return False
    if identity["start_byte"] < 0 or identity["end_byte"] <= identity["start_byte"]:
        return False
    if not _is_sha256(identity.get("content_sha256")):
        return False
    start_line = identity.get("start_line")
    end_line = identity.get("end_line")
    if (start_line is None) != (end_line is None):
        return False
    if start_line is not None:
        if not _is_int_not_bool(start_line) or not _is_int_not_bool(end_line):
            return False
        if start_line < 1 or end_line < start_line:
            return False
    source_start_line = identity.get("source_start_line")
    source_end_line = identity.get("source_end_line")
    if (source_start_line is None) != (source_end_line is None):
        return False
    if source_start_line is not None:
        if not _is_non_empty_string(identity.get("source_file_path")):
            return False
        if not _is_int_not_bool(source_start_line) or not _is_int_not_bool(source_end_line):
            return False
        if source_start_line < 1 or source_end_line < source_start_line:
            return False
    repo_id = identity.get("repo_id")
    return repo_id is None or _is_non_empty_string(repo_id)


def check_memory_recall(
    memory_record: Mapping[str, Any],
    *,
    current_citations: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    current_snapshot_hash: str | None,
    current_freshness_status: str | None,
) -> dict[str, Any]:
    """Revalidate a memory record before reuse.

    Any missing, stale, changed or unverifiable evidence makes the record
    unusable as a source-backed claim. The memory text may still be shown as
    historical memory if the caller labels it that way, but not as source
    truth.
    """

    evidence = memory_record.get("evidence") if isinstance(memory_record, Mapping) else None
    snapshot = evidence.get("snapshot") if isinstance(evidence, Mapping) else None
    recorded_snapshot_hash = snapshot.get("hash") if isinstance(snapshot, Mapping) else None
    recorded_snapshot_stem = snapshot.get("stem") if isinstance(snapshot, Mapping) else None
    recorded_freshness_status = snapshot.get("freshness_status") if isinstance(snapshot, Mapping) else None
    citations = evidence.get("citations") if isinstance(evidence, Mapping) else None
    citation_list = [
        citation
        for citation in (
            citations
            if isinstance(citations, Sequence) and not isinstance(citations, (str, bytes))
            else []
        )
        if isinstance(citation, Mapping)
    ]

    issues: list[dict[str, Any]] = []
    if not isinstance(memory_record, Mapping):
        issues.append({"code": "memory_record_invalid", "severity": "blocking"})
    else:
        if memory_record.get("kind") != KIND:
            issues.append({"code": "memory_record_kind_invalid", "severity": "blocking"})
        if memory_record.get("version") != VERSION:
            issues.append({"code": "memory_record_version_invalid", "severity": "blocking"})
        if not _is_non_empty_string(memory_record.get("claim_text")):
            issues.append({"code": "claim_text_invalid", "severity": "blocking"})

    recorded_conflicts = _duplicate_citation_ids(citation_list)
    for citation_id in sorted(recorded_conflicts):
        issues.append({
            "code": "recorded_citation_id_conflict",
            "citation_id": citation_id,
            "severity": "blocking",
        })

    snapshot_status = "verified"
    if not _is_sha256(recorded_snapshot_hash) or not _is_non_empty_string(recorded_snapshot_stem):
        snapshot_status = "invalid_record"
        issues.append({"code": "snapshot_record_invalid", "severity": "blocking"})
    elif current_snapshot_hash is None:
        snapshot_status = "unverified"
        issues.append({"code": "snapshot_hash_missing", "severity": "blocking"})
    elif current_snapshot_hash != recorded_snapshot_hash:
        snapshot_status = "changed"
        issues.append({"code": "snapshot_hash_changed", "severity": "blocking"})

    effective_freshness = current_freshness_status
    freshness_basis = "current" if current_freshness_status is not None else "missing_current"
    freshness_status = (
        "fresh" if effective_freshness in USABLE_FRESHNESS_STATUSES else "stale_or_unverified"
    )
    if effective_freshness not in USABLE_FRESHNESS_STATUSES:
        issues.append({
            "code": (
                "freshness_not_fresh"
                if effective_freshness is not None
                else "freshness_status_missing"
            ),
            "severity": "blocking",
        })

    lookup, current_conflicts = _citation_lookup(current_citations)
    for citation_id in sorted(current_conflicts):
        issues.append({
            "code": "citation_id_conflict",
            "citation_id": citation_id,
            "severity": "blocking",
        })

    citation_checks: list[dict[str, Any]] = []
    for citation in citation_list:
        citation_id = citation.get("citation_id")
        recorded_hash = citation.get("range_content_sha256") or _range_hash(
            citation.get("source_range")
            if isinstance(citation.get("source_range"), Mapping)
            else None
        )
        check: dict[str, Any] = {
            "citation_id": citation_id,
            "status": "verified",
            "recorded_range_content_sha256": recorded_hash,
            "current_range_content_sha256": None,
        }
        recorded_identity = (
            citation.get("source_range")
            if isinstance(citation.get("source_range"), Mapping)
            else None
        )
        if citation_id in recorded_conflicts or citation_id in current_conflicts:
            check["status"] = "conflict"
        elif not _citation_id_is_valid(citation_id) or not _is_sha256(recorded_hash):
            check["status"] = "invalid_record"
            issues.append({
                "code": "citation_record_invalid",
                "citation_id": citation_id,
                "severity": "blocking",
            })
        elif not _stored_range_identity_is_valid(recorded_identity):
            check["status"] = "invalid_record"
            issues.append({
                "code": "citation_range_identity_missing",
                "citation_id": citation_id,
                "severity": "blocking",
            })
        else:
            current = lookup.get(citation_id)
            current_hash = _current_range_hash(current)
            current_identity = _current_range_identity(current)
            check["current_range_content_sha256"] = current_hash
            check["current_source_range"] = current_identity
            if current is None:
                check["status"] = "missing"
                issues.append({
                    "code": "citation_missing",
                    "citation_id": citation_id,
                    "severity": "blocking",
                })
            elif current.get("citation_id") not in (None, citation_id):
                check["status"] = "conflict"
                issues.append({
                    "code": "citation_id_conflict",
                    "citation_id": citation_id,
                    "severity": "blocking",
                })
            elif current_identity is None:
                check["status"] = "unverified"
                issues.append({
                    "code": "citation_range_missing",
                    "citation_id": citation_id,
                    "severity": "blocking",
                })
            elif current_hash is None:
                check["status"] = "unverified"
                issues.append({
                    "code": "citation_hash_missing",
                    "citation_id": citation_id,
                    "severity": "blocking",
                })
            elif current_hash != recorded_hash:
                check["status"] = "changed"
                issues.append({
                    "code": "citation_hash_changed",
                    "citation_id": citation_id,
                    "severity": "blocking",
                })
            elif not _range_identity_matches(recorded_identity, current_identity):
                check["status"] = "changed"
                issues.append({
                    "code": "citation_range_identity_changed",
                    "citation_id": citation_id,
                    "severity": "blocking",
                })
        citation_checks.append(check)

    if not citation_checks:
        issues.append({"code": "citations_missing_from_record", "severity": "blocking"})

    usable = not issues
    return {
        "kind": RECALL_CHECK_KIND,
        "version": VERSION,
        "status": "usable" if usable else "unusable",
        "usable_as_source_backed_memory": usable,
        "claim_text": (
            memory_record.get("claim_text") if isinstance(memory_record, Mapping) else None
        ),
        "snapshot_check": {
            "status": snapshot_status,
            "stem": recorded_snapshot_stem,
            "recorded_hash": recorded_snapshot_hash,
            "current_hash": current_snapshot_hash,
        },
        "freshness_check": {
            "status": freshness_status,
            "basis": freshness_basis,
            "recorded_freshness_status": recorded_freshness_status,
            "current_freshness_status": current_freshness_status,
            "usable_freshness_statuses": list(USABLE_FRESHNESS_STATUSES),
        },
        "citation_checks": citation_checks,
        "issue_count": len(issues),
        "issues": issues,
        "presentation_policy": (
            "may_present_with_verified_citations"
            if usable
            else "do_not_present_as_source_truth"
        ),
        "memory_is_source_truth": False,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
