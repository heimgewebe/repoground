"""Commit- and digest-gated context projection for system relation evidence."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from merger.repoground.core.system_relation_overlay import (
    MAX_EVIDENCE_RECORDS,
    SystemRelationOverlayError,
    normalize_system_relation_evidence,
)

KIND = "repoground.system_relation_context"
VERSION = "1.0"
PRODUCER_RESULT_KIND = "repoground.system_relation_producer_result"
PRODUCER_RESULT_VERSION = "1.0"
ABSENCE_SEMANTICS = (
    "Missing projected records mean only that coherent supplied evidence did not "
    "establish a supported relation for these target paths."
)
DOES_NOT_ESTABLISH = (
    "repository_truth",
    "relation_completeness",
    "runtime_behavior",
    "runtime_correctness",
    "config_runtime_effect",
    "schema_conformance",
    "workflow_execution",
    "merge_readiness",
)


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _expected_commit(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    commit = value.strip()
    if len(commit) not in {40, 64}:
        return None
    if any(character not in "0123456789abcdef" for character in commit):
        return None
    return commit


def _base(status: str) -> dict[str, Any]:
    return {
        "kind": KIND,
        "version": VERSION,
        "status": status,
        "source": None,
        "records": [],
        "record_count": 0,
        "relevant_record_count": 0,
        "omitted_relevant_count": 0,
        "reason": None,
        "absence_semantics": ABSENCE_SEMANTICS,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _blocked(
    reason: str,
    *,
    expected_commit: str | None = None,
    observed_commit: Any = None,
    expected_digest: Any = None,
    observed_digest: Any = None,
) -> dict[str, Any]:
    result = _base("blocked")
    result["reason"] = reason
    result["binding"] = {
        "expected_repository_commit": expected_commit,
        "observed_repository_commit": (
            observed_commit if isinstance(observed_commit, str) else None
        ),
        "expected_evidence_sha256": (
            expected_digest if isinstance(expected_digest, str) else None
        ),
        "observed_evidence_sha256": (
            observed_digest if isinstance(observed_digest, str) else None
        ),
    }
    return result


def _target_path_set(value: Iterable[str]) -> set[str]:
    return {
        path
        for path in value
        if isinstance(path, str) and path and not path.startswith("/")
    }


def _record_relevant(record: Mapping[str, Any], target_paths: set[str]) -> bool:
    source = record.get("source")
    subject = record.get("subject")
    target = record.get("target")
    source_path = source.get("path") if isinstance(source, Mapping) else None
    subject_identity = (
        subject.get("identity") if isinstance(subject, Mapping) else None
    )
    target_identity = target.get("identity") if isinstance(target, Mapping) else None
    return bool(
        source_path in target_paths
        or subject_identity in target_paths
        or target_identity in target_paths
    )


def _missing(expected_commit: str) -> dict[str, Any]:
    result = _base("missing")
    result["reason"] = "system_relation_evidence_missing"
    result["binding"] = {
        "expected_repository_commit": expected_commit,
        "observed_repository_commit": None,
        "expected_evidence_sha256": None,
        "observed_evidence_sha256": None,
    }
    return result


def _producer_binding(
    producer_result: Any,
    *,
    expected_commit: str,
) -> tuple[dict[str, Any] | None, Any, Mapping[str, Any] | None]:
    if not isinstance(producer_result, Mapping):
        return _blocked(
            "producer_result_not_object", expected_commit=expected_commit
        ), None, None
    if producer_result.get("kind") != PRODUCER_RESULT_KIND:
        return _blocked(
            "producer_result_kind_incompatible", expected_commit=expected_commit
        ), None, None
    if producer_result.get("version") != PRODUCER_RESULT_VERSION:
        return _blocked(
            "producer_result_version_incompatible", expected_commit=expected_commit
        ), None, None

    repository = producer_result.get("repository")
    observed_commit = (
        repository.get("commit") if isinstance(repository, Mapping) else None
    )
    if observed_commit != expected_commit:
        return _blocked(
            "repository_commit_mismatch",
            expected_commit=expected_commit,
            observed_commit=observed_commit,
        ), observed_commit, None

    revision_binding = producer_result.get("revision_binding")
    binding_valid = (
        isinstance(revision_binding, Mapping)
        and revision_binding.get("mode") == "git_commit_object"
        and revision_binding.get("repository_commit") == expected_commit
        and revision_binding.get("verified") is True
    )
    if not binding_valid:
        return _blocked(
            "revision_binding_incompatible",
            expected_commit=expected_commit,
            observed_commit=observed_commit,
        ), observed_commit, None
    return None, observed_commit, revision_binding


def _validated_overlay(
    producer_result: Mapping[str, Any],
    *,
    expected_commit: str,
    observed_commit: Any,
) -> tuple[
    dict[str, Any] | None,
    str | None,
    str | None,
    dict[str, Any] | None,
]:
    evidence = producer_result.get("evidence")
    expected_digest = producer_result.get("evidence_sha256")
    if not isinstance(evidence, Mapping):
        return _blocked(
            "evidence_not_object",
            expected_commit=expected_commit,
            observed_commit=observed_commit,
            expected_digest=expected_digest,
        ), None, None, None
    raw_records = evidence.get("records")
    if not isinstance(raw_records, list):
        return _blocked(
            "evidence_records_not_list",
            expected_commit=expected_commit,
            observed_commit=observed_commit,
            expected_digest=expected_digest,
        ), None, None, None
    if len(raw_records) > MAX_EVIDENCE_RECORDS:
        return _blocked(
            "evidence_record_limit_exceeded",
            expected_commit=expected_commit,
            observed_commit=observed_commit,
            expected_digest=expected_digest,
        ), None, None, None
    if not isinstance(expected_digest, str) or len(expected_digest) != 64:
        return _blocked(
            "evidence_digest_invalid",
            expected_commit=expected_commit,
            observed_commit=observed_commit,
            expected_digest=expected_digest,
        ), None, None, None

    observed_digest = _canonical_sha256(evidence)
    if observed_digest != expected_digest:
        return _blocked(
            "evidence_digest_mismatch",
            expected_commit=expected_commit,
            observed_commit=observed_commit,
            expected_digest=expected_digest,
            observed_digest=observed_digest,
        ), expected_digest, observed_digest, None

    supplied_overlay = producer_result.get("overlay")
    if not isinstance(supplied_overlay, Mapping):
        return _blocked(
            "overlay_not_object",
            expected_commit=expected_commit,
            observed_commit=observed_commit,
            expected_digest=expected_digest,
            observed_digest=observed_digest,
        ), expected_digest, observed_digest, None
    try:
        normalized = normalize_system_relation_evidence(
            evidence,
            evidence_sha256=expected_digest,
            repository_commit=expected_commit,
        )
    except SystemRelationOverlayError:
        return _blocked(
            "evidence_contract_invalid",
            expected_commit=expected_commit,
            observed_commit=observed_commit,
            expected_digest=expected_digest,
            observed_digest=observed_digest,
        ), expected_digest, observed_digest, None
    if dict(supplied_overlay) != normalized:
        return _blocked(
            "overlay_revalidation_mismatch",
            expected_commit=expected_commit,
            observed_commit=observed_commit,
            expected_digest=expected_digest,
            observed_digest=observed_digest,
        ), expected_digest, observed_digest, None
    return None, expected_digest, observed_digest, normalized


def project_system_relation_context(
    producer_result: Any,
    *,
    repository_commit: Any,
    target_paths: Iterable[str],
    max_items: int = 25,
) -> dict[str, Any]:
    """Project relevant relations only after commit and digest coherence checks."""
    expected_commit = _expected_commit(repository_commit)
    if expected_commit is None:
        return _blocked("expected_repository_commit_invalid")
    if producer_result is None:
        return _missing(expected_commit)

    binding_error, observed_commit, revision_binding = _producer_binding(
        producer_result,
        expected_commit=expected_commit,
    )
    if binding_error is not None:
        return binding_error
    assert isinstance(producer_result, Mapping)
    assert revision_binding is not None

    overlay_error, expected_digest, observed_digest, normalized = _validated_overlay(
        producer_result,
        expected_commit=expected_commit,
        observed_commit=observed_commit,
    )
    if overlay_error is not None:
        return overlay_error
    assert expected_digest is not None
    assert observed_digest is not None
    assert normalized is not None

    paths = _target_path_set(target_paths)
    relevant = [
        dict(record)
        for record in normalized["records"]
        if _record_relevant(record, paths)
    ]
    limit = max(1, min(200, int(max_items)))
    selected = relevant[:limit]
    result = _base("available")
    result.update(
        {
            "source": {
                "repository_commit": expected_commit,
                "evidence_sha256": expected_digest,
                "producer": dict(normalized["source"]["producer"]),
                "revision_binding": dict(revision_binding),
            },
            "records": selected,
            "record_count": len(normalized["records"]),
            "relevant_record_count": len(relevant),
            "omitted_relevant_count": max(0, len(relevant) - len(selected)),
            "binding": {
                "expected_repository_commit": expected_commit,
                "observed_repository_commit": observed_commit,
                "expected_evidence_sha256": expected_digest,
                "observed_evidence_sha256": observed_digest,
            },
        }
    )
    return result


__all__ = [
    "DOES_NOT_ESTABLISH",
    "KIND",
    "VERSION",
    "project_system_relation_context",
]
