"""Common bounded evidence contract for optional non-Python structure adapters.

The contract is deliberately navigation-only.  It does not claim parser
completeness, runtime reachability, dynamic dispatch resolution, generated-code
expansion, or repository truth.  Adapters may under-approximate aggressively as
long as every omission/degradation is visible.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping

KIND = "repoground.language_structure"
VERSION = "1.0"
CONTRACT_ID = "language-structure"
CONTRACT_VERSION = "v1"
AUTHORITY = "navigation_index"
CANONICALITY = "derived"
RISK_CLASS = "navigation"

DOES_NOT_ESTABLISH = (
    "repository_truth",
    "complete_symbol_index",
    "complete_call_graph",
    "complete_dependency_graph",
    "runtime_behavior",
    "dynamic_dispatch_resolution",
    "macro_expansion",
    "generated_code_coverage",
    "python_ast_equivalence",
    "test_sufficiency",
    "default_promotion",
)

_COORDINATE_BASIS = "source_lines_1_based_unicode_characters"
_COMMIT_RE = re.compile(r"^[a-f0-9]{40}(?:[a-f0-9]{24})?$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _json_bytes(value: Any) -> int:
    return len(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    )


def _json_characters(value: Any) -> int:
    return len(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )


def _positive_limit(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _validate_binding(
    *,
    repository_commit: str,
    bundle_manifest: str,
    canonical_dump_index_sha256: str,
) -> None:
    if (
        not isinstance(repository_commit, str)
        or _COMMIT_RE.fullmatch(repository_commit) is None
    ):
        raise ValueError(
            "repository_commit must be a lowercase 40- or 64-character Git identity"
        )
    if (
        not isinstance(bundle_manifest, str)
        or not bundle_manifest
        or Path(bundle_manifest).name != bundle_manifest
    ):
        raise ValueError("bundle_manifest must be a non-empty manifest filename")
    if (
        not isinstance(canonical_dump_index_sha256, str)
        or _SHA256_RE.fullmatch(canonical_dump_index_sha256) is None
    ):
        raise ValueError("canonical_dump_index_sha256 must be a lowercase SHA-256")


def _record_id(identity: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def source_range(
    *, line: int, start_character: int, end_character: int
) -> dict[str, Any]:
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        raise ValueError("line must be a positive 1-based integer")
    if (
        isinstance(start_character, bool)
        or not isinstance(start_character, int)
        or start_character < 0
    ):
        raise ValueError("start_character must be a non-negative integer")
    if (
        isinstance(end_character, bool)
        or not isinstance(end_character, int)
        or end_character <= start_character
    ):
        raise ValueError("end_character must be greater than start_character")
    return {
        "start_line": line,
        "end_line": line,
        "start_character": start_character,
        "end_character": end_character,
        "coordinate_basis": _COORDINATE_BASIS,
    }


def make_record(
    *,
    language: str,
    adapter_id: str,
    adapter_version: str,
    record_type: str,
    relation: str,
    symbol: str,
    source_path: str,
    source_range_value: Mapping[str, Any],
    repository_commit: str,
    bundle_manifest: str,
    canonical_dump_index_sha256: str,
    evidence_level: str,
    confidence: float,
    basis: str,
    target_symbol: str | None = None,
    symbol_kind: str | None = None,
    source_artifact: Mapping[str, Any] | None = None,
    uncertainty: Iterable[str] = (),
) -> dict[str, Any]:
    """Create one deterministic language-specific navigation record."""
    _validate_binding(
        repository_commit=repository_commit,
        bundle_manifest=bundle_manifest,
        canonical_dump_index_sha256=canonical_dump_index_sha256,
    )
    if evidence_level not in {"S0", "S1"}:
        raise ValueError("evidence_level must be S0 or S1")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
        or not 0.0 <= float(confidence) <= 1.0
    ):
        raise ValueError("confidence must be a finite number from 0 to 1")
    identity = {
        "language": language,
        "adapter_id": adapter_id,
        "adapter_version": adapter_version,
        "record_type": record_type,
        "relation": relation,
        "symbol": symbol,
        "target_symbol": target_symbol,
        "source_path": source_path,
        "source_range": dict(source_range_value),
        "repository_commit": repository_commit,
    }
    return {
        "id": _record_id(identity),
        "language": language,
        "adapter": {"id": adapter_id, "version": adapter_version},
        "record_type": record_type,
        "symbol_kind": symbol_kind,
        "relation": relation,
        "symbol": symbol,
        "target_symbol": target_symbol,
        "source": {"path": source_path, "range": dict(source_range_value)},
        "evidence": {
            "level": evidence_level,
            "confidence": round(float(confidence), 6),
            "basis": basis,
        },
        "provenance": {
            "repository_commit": repository_commit,
            "bundle_manifest": bundle_manifest,
            # The manifest digest is necessarily assigned by a consumer after the
            # final manifest has been written; embedding it here would be circular.
            "bundle_manifest_sha256": None,
            "canonical_dump_index_sha256": canonical_dump_index_sha256,
            "source_artifact": deepcopy(dict(source_artifact))
            if source_artifact is not None
            else None,
        },
        "uncertainty": sorted({str(item) for item in uncertainty if str(item)}),
    }


def build_language_structure_document(
    repo_root: str | Path,
    *,
    repository_commit: str,
    bundle_manifest: str,
    canonical_dump_index_sha256: str,
    run_id: str,
    rust_scip_artifact: Mapping[str, Any] | None = None,
    max_files: int = 5000,
    max_file_bytes: int = 524_288,
    max_records: int = 50_000,
) -> dict[str, Any]:
    """Build one deterministic Rust/Bash structure sidecar from bound local input."""
    from merger.repoground.core.bash_structure_adapter import scan_bash_repository
    from merger.repoground.core.rust_structure_adapter import scan_rust_repository

    _validate_binding(
        repository_commit=repository_commit,
        bundle_manifest=bundle_manifest,
        canonical_dump_index_sha256=canonical_dump_index_sha256,
    )
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id must be a non-empty string")
    max_files = _positive_limit(max_files, field="max_files")
    max_file_bytes = _positive_limit(max_file_bytes, field="max_file_bytes")
    max_records = _positive_limit(max_records, field="max_records")
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise ValueError("repo_root must be an existing directory")
    common = {
        "repository_commit": repository_commit,
        "bundle_manifest": bundle_manifest,
        "canonical_dump_index_sha256": canonical_dump_index_sha256,
        "max_files": max_files,
        "max_file_bytes": max_file_bytes,
        "max_records": max_records,
    }
    bash = scan_bash_repository(root, **common)
    rust = scan_rust_repository(root, scip_artifact=rust_scip_artifact, **common)
    records = sorted(
        [*bash["records"], *rust["records"]],
        key=lambda item: (
            str(item.get("language")),
            str(item.get("source", {}).get("path")),
            int(item.get("source", {}).get("range", {}).get("start_line", 0)),
            str(item.get("relation")),
            str(item.get("symbol")),
            str(item.get("target_symbol") or ""),
        ),
    )
    truncation: dict[str, Any] | None = None
    if len(records) > max_records:
        truncation = {
            "reason": "global_record_limit",
            "observed": len(records),
            "limit": max_records,
        }
        records = records[:max_records]
    summaries = {
        "bash": deepcopy(bash["summary"]),
        "rust": deepcopy(rust["summary"]),
    }
    language_truncations: list[dict[str, Any]] = []
    for language, summary in summaries.items():
        retained_records = [
            record for record in records if record.get("language") == language
        ]
        observed_record_count = int(summary.get("record_count", 0))
        retained_record_count = len(retained_records)
        summary["record_count"] = retained_record_count
        if language == "rust":
            summary["scip_record_count"] = sum(
                1
                for record in retained_records
                if record.get("adapter")
                == {"id": "rust-scip-structure", "version": "1.0"}
            )
        if observed_record_count > retained_record_count:
            summary["status"] = "degraded"
            language_truncations.append(
                {
                    "language": language,
                    "reason": "global_record_limit",
                    "detail": {
                        "observed_record_count": observed_record_count,
                        "retained_record_count": retained_record_count,
                        "omitted_record_count": (
                            observed_record_count - retained_record_count
                        ),
                        "limit": max_records,
                    },
                }
            )
    degradations = sorted(
        [*bash["degradations"], *rust["degradations"]],
        key=lambda item: (
            str(item.get("language")),
            str(item.get("path") or ""),
            int(item.get("line") or 0),
            str(item.get("reason")),
        ),
    )
    if truncation is not None:
        degradations.extend(language_truncations)
        degradations.append(
            {
                "language": "mixed",
                "reason": "global_record_limit",
                "detail": truncation,
            }
        )
    status = "available"
    if degradations or bash["status"] != "available" or rust["status"] != "available":
        status = "degraded"
    return {
        "kind": KIND,
        "version": VERSION,
        "authority": AUTHORITY,
        "canonicality": CANONICALITY,
        "risk_class": RISK_CLASS,
        "run_id": run_id,
        "status": status,
        "source": {
            "repository_root_name": root.name,
            "repository_commit": repository_commit,
            "bundle_manifest": bundle_manifest,
            "canonical_dump_index_sha256": canonical_dump_index_sha256,
            "network_used": False,
            "secrets_read": False,
            "workspace_state_used_beyond_bound_source": False,
        },
        "languages": summaries,
        "records": records,
        "record_count": len(records),
        "degradations": degradations,
        "truncation": truncation,
        "promotion": {
            "default_promoted": False,
            "status": "keep_optional",
            "reason": "revision_bound_agent_benefit_not_established_by_structure_extraction",
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _normalized_terms(terms: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            text for raw in terms for text in [str(raw).strip().casefold()] if text
        )
    )


def _matching_terms(value: Any, terms: tuple[str, ...]) -> frozenset[str]:
    if value is None:
        return frozenset()
    text = str(value).casefold()
    return frozenset(term for term in terms if term in text)


def _record_relevance_score(
    record: Mapping[str, Any], paths: set[str], terms: tuple[str, ...]
) -> tuple[int, ...]:
    source = record.get("source")
    source_path = source.get("path") if isinstance(source, Mapping) else ""
    adapter = record.get("adapter")
    adapter_id = adapter.get("id") if isinstance(adapter, Mapping) else ""
    entity_terms = _matching_terms(record.get("symbol"), terms) | _matching_terms(
        record.get("target_symbol"), terms
    )
    path_terms = _matching_terms(source_path, terms)
    relation_terms = _matching_terms(record.get("relation"), terms)
    broad_metadata_terms = _matching_terms(
        record.get("record_type"), terms
    ) | _matching_terms(record.get("symbol_kind"), terms)
    generic_metadata_terms = _matching_terms(
        record.get("language"), terms
    ) | _matching_terms(adapter_id, terms)
    specific_terms = entity_terms | path_terms | relation_terms
    all_terms = specific_terms | broad_metadata_terms | generic_metadata_terms
    return (
        int(bool(paths) and isinstance(source_path, str) and source_path in paths),
        len(specific_terms),
        len(entity_terms),
        len(path_terms),
        len(relation_terms),
        len(broad_metadata_terms),
        len(generic_metadata_terms),
        len(all_terms),
    )


def _relevant_record(
    record: Mapping[str, Any], paths: set[str], terms: tuple[str, ...]
) -> bool:
    if not paths and not terms:
        return True
    return any(_record_relevance_score(record, paths, terms))


def _record_tiebreaker(record: Mapping[str, Any]) -> tuple[Any, ...]:
    source = record.get("source")
    source_path = source.get("path") if isinstance(source, Mapping) else ""
    range_value = source.get("range") if isinstance(source, Mapping) else None
    adapter = record.get("adapter")
    adapter_id = adapter.get("id") if isinstance(adapter, Mapping) else ""
    return (
        str(record.get("language") or ""),
        str(source_path or ""),
        int(range_value.get("start_line", 0))
        if isinstance(range_value, Mapping)
        else 0,
        int(range_value.get("start_character", 0))
        if isinstance(range_value, Mapping)
        else 0,
        str(record.get("relation") or ""),
        str(record.get("record_type") or ""),
        str(record.get("symbol") or ""),
        str(record.get("target_symbol") or ""),
        str(adapter_id or ""),
        str(record.get("id") or ""),
    )


def _rank_relevant_records(
    records: Iterable[Any], paths: set[str], terms: tuple[str, ...]
) -> list[dict[str, Any]]:
    by_score: dict[tuple[int, ...], list[dict[str, Any]]] = {}
    for record in records:
        if not isinstance(record, Mapping) or not _relevant_record(
            record, paths, terms
        ):
            continue
        score = _record_relevance_score(record, paths, terms)
        by_score.setdefault(score, []).append(deepcopy(dict(record)))
    ranked: list[dict[str, Any]] = []
    for score in sorted(by_score, reverse=True):
        tied = sorted(by_score[score], key=_record_tiebreaker)
        ranked.extend(_interleave_by_language(tied))
    return ranked


def _relevant_degradation(
    item: Mapping[str, Any], paths: set[str], terms: tuple[str, ...]
) -> bool:
    path = item.get("path")
    if paths and isinstance(path, str) and path in paths:
        return True
    if terms:
        haystack = " ".join(
            str(value)
            for value in (
                item.get("language"),
                item.get("reason"),
                item.get("path"),
                item.get("detail"),
            )
            if value is not None
        ).casefold()
        if any(term in haystack for term in terms):
            return True
    return not paths and not terms


def select_language_structure_evidence(
    document: Mapping[str, Any],
    *,
    paths: Iterable[str] = (),
    terms: Iterable[str] = (),
    max_items: int = 25,
    bundle_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Select bounded records while preserving language uncertainty and provenance."""
    if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 0:
        raise ValueError("max_items must be a non-negative integer")
    path_set = {str(path) for path in paths if str(path)}
    normalized_terms = _normalized_terms(terms)
    raw_records = document.get("records")
    records = _rank_relevant_records(
        raw_records if isinstance(raw_records, list) else [],
        path_set,
        normalized_terms,
    )
    selected = records[:max_items]
    for record in selected:
        provenance = record.get("provenance")
        if isinstance(provenance, dict) and bundle_manifest_sha256:
            provenance["bundle_manifest_sha256"] = bundle_manifest_sha256
    raw_degradations = document.get("degradations")
    degradations = (
        [
            deepcopy(item)
            for item in raw_degradations
            if isinstance(raw_degradations, list)
            and isinstance(item, Mapping)
            and _relevant_degradation(item, path_set, normalized_terms)
        ]
        if isinstance(raw_degradations, list)
        else []
    )
    selected_degradations = _interleave_by_language(degradations)[:max_items]
    return {
        "status": document.get("status", "unknown"),
        "records": selected,
        "degradations": selected_degradations,
        "truncated": len(records) > len(selected),
        "degradation_truncated": len(degradations) > len(selected_degradations),
        "available_record_count": len(records),
        "selected_record_count": len(selected),
        "available_degradation_count": len(degradations),
        "selected_degradation_count": len(selected_degradations),
        "filters": {
            "paths": sorted(path_set),
            "terms": list(normalized_terms),
            "match_semantics": "exact_path_or_term_substring_by_explicit_field",
            "ranking": [
                "exact_path_filter",
                "symbol_or_target_term",
                "source_path_term",
                "relation_term",
                "record_type_or_symbol_kind_term",
                "language_or_adapter_term",
                "total_explicit_term_coverage",
                "deterministic_language_fair_ties",
            ],
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _interleave_by_language(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Round-robin deterministic language buckets so one language cannot starve another."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        buckets.setdefault(str(item.get("language") or "unknown"), []).append(item)
    positions = {language: 0 for language in buckets}
    ordered: list[dict[str, Any]] = []
    while True:
        progressed = False
        for language in sorted(buckets):
            position = positions[language]
            bucket = buckets[language]
            if position >= len(bucket):
                continue
            ordered.append(bucket[position])
            positions[language] += 1
            progressed = True
        if not progressed:
            return ordered


def _compose_candidates(
    selection: Mapping[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    records = _interleave_by_language(
        [item for item in selection.get("records", []) if isinstance(item, dict)]
    )
    degradations = _interleave_by_language(
        [item for item in selection.get("degradations", []) if isinstance(item, dict)]
    )
    # Navigation records are the primary payload. Each lane is independently
    # language-interleaved, and omitted degradations remain visible in budget
    # accounting when the shared item/byte ceiling is exhausted.
    return [
        *(("records", item) for item in records),
        *(("degradations", item) for item in degradations),
    ]


def compose_language_structure_evidence(
    document: Mapping[str, Any],
    *,
    paths: Iterable[str] = (),
    terms: Iterable[str] = (),
    max_bytes: int,
    max_items: int = 50,
    bundle_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Fit records and omission reasons under one exact JSON byte budget.

    The budget applies to the returned ``evidence`` object only. Selection is
    deterministic and never shortens a record, range, uncertainty list or
    provenance field to make it fit; whole items are omitted instead.
    """
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer")
    selection = select_language_structure_evidence(
        document,
        paths=paths,
        terms=terms,
        max_items=max_items,
        bundle_manifest_sha256=bundle_manifest_sha256,
    )
    evidence: dict[str, Any] = {"records": [], "degradations": []}
    omissions: list[dict[str, Any]] = []
    accepted_items = 0
    used = 0
    for lane, item in _compose_candidates(selection):
        if accepted_items >= max_items:
            omissions.append(
                {
                    "lane": lane,
                    "reason": "max_items_limit",
                    "id": item.get("id"),
                    "language": item.get("language"),
                }
            )
            continue
        candidate = {
            "records": list(evidence["records"]),
            "degradations": list(evidence["degradations"]),
        }
        candidate[lane].append(item)
        candidate_bytes = _json_bytes(candidate)
        if candidate_bytes > max_bytes:
            omissions.append(
                {
                    "lane": lane,
                    "reason": "hard_byte_budget_exceeded",
                    "id": item.get("id"),
                    "language": item.get("language"),
                    "required_bytes": candidate_bytes - used,
                    "remaining_bytes": max(0, max_bytes - used),
                }
            )
            continue
        evidence = candidate
        used = candidate_bytes
        accepted_items += 1
    source_record_omissions = max(
        0,
        int(selection["available_record_count"]) - len(selection["records"]),
    )
    source_degradation_omissions = max(
        0,
        int(selection["available_degradation_count"]) - len(selection["degradations"]),
    )
    for lane, count in (
        ("records", source_record_omissions),
        ("degradations", source_degradation_omissions),
    ):
        if count:
            omissions.append(
                {
                    "lane": lane,
                    "reason": "source_selection_limit",
                    "count": count,
                }
            )
    omitted = {
        "records": int(selection["available_record_count"]) - len(evidence["records"]),
        "degradations": int(selection["available_degradation_count"])
        - len(evidence["degradations"]),
    }
    used_characters = _json_characters(evidence) if accepted_items else 0
    return {
        "status": selection["status"],
        "evidence": evidence,
        "budget": {
            "hard_limit_bytes": max_bytes,
            "used_bytes": used,
            "used_unicode_characters": used_characters,
            "remaining_bytes": max(0, max_bytes - used),
            "omitted": omitted,
            "omissions": omissions,
            "whole_item_omission_only": True,
            "unit": "utf8_bytes",
            "accounting": (
                "canonical_json_utf8_bytes_of_non_empty_evidence_object; "
                "empty selection costs zero because no structured evidence is emitted"
            ),
        },
        "selection": {
            "available_record_count": selection["available_record_count"],
            "selected_record_count": len(evidence["records"]),
            "available_degradation_count": selection["available_degradation_count"],
            "selected_degradation_count": len(evidence["degradations"]),
            "source_truncated": selection["truncated"]
            or selection["degradation_truncated"],
            "filters": selection["filters"],
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _language_record_range_ref(record: Mapping[str, Any]) -> str:
    source = record.get("source")
    path = source.get("path") if isinstance(source, Mapping) else ""
    range_value = source.get("range") if isinstance(source, Mapping) else None
    start = range_value.get("start_line") if isinstance(range_value, Mapping) else None
    end = range_value.get("end_line") if isinstance(range_value, Mapping) else None
    if (
        isinstance(path, str)
        and path
        and isinstance(start, int)
        and isinstance(end, int)
    ):
        return f"file:{path}#L{start}-L{end}"
    return f"language-structure:{record.get('id', 'unknown')}"


def _language_definition_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    source = record.get("source")
    path = source.get("path") if isinstance(source, Mapping) else None
    range_value = source.get("range") if isinstance(source, Mapping) else {}
    return {
        "id": record.get("id"),
        "kind": record.get("symbol_kind") or "symbol",
        "name": record.get("symbol"),
        "qualified_name": record.get("symbol"),
        "path": path,
        "start_line": range_value.get("start_line"),
        "end_line": range_value.get("end_line"),
        "range_ref": _language_record_range_ref(record),
        "language": record.get("language"),
        "adapter": deepcopy(record.get("adapter")),
        "evidence": deepcopy(record.get("evidence")),
        "provenance": deepcopy(record.get("provenance")),
        "uncertainty": deepcopy(record.get("uncertainty")),
    }


def _language_relation_projection(
    record: Mapping[str, Any], *, run_id: str, digest: str
) -> dict[str, Any]:
    source = record.get("source")
    return {
        "relation_kind": "language_structure",
        "direction": "outgoing",
        "path": source.get("path") if isinstance(source, Mapping) else None,
        "range_ref": _language_record_range_ref(record),
        "source_range": deepcopy(source.get("range"))
        if isinstance(source, Mapping)
        else None,
        "language": record.get("language"),
        "relation_type": record.get("relation"),
        "symbol": record.get("symbol"),
        "target_symbol": record.get("target_symbol"),
        "symbol_kind": record.get("symbol_kind"),
        "adapter": deepcopy(record.get("adapter")),
        "evidence_level": (
            record.get("evidence", {}).get("level")
            if isinstance(record.get("evidence"), Mapping)
            else None
        ),
        "confidence": (
            record.get("evidence", {}).get("confidence")
            if isinstance(record.get("evidence"), Mapping)
            else None
        ),
        "evidence": deepcopy(record.get("evidence")),
        "provenance": deepcopy(record.get("provenance")),
        "uncertainty": deepcopy(record.get("uncertainty")),
        "freshness": {
            "source": "language_structure_json",
            "status": "coherent",
            "run_id": run_id,
            "canonical_dump_index_sha256": digest,
        },
    }


def _language_source_range_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    source = record.get("source")
    return {
        "path": source.get("path") if isinstance(source, Mapping) else None,
        "range": deepcopy(source.get("range")) if isinstance(source, Mapping) else None,
        "range_ref": _language_record_range_ref(record),
        "language": record.get("language"),
        "relation": record.get("relation"),
        "symbol": record.get("symbol"),
        "target_symbol": record.get("target_symbol"),
        "adapter": deepcopy(record.get("adapter")),
        "evidence": deepcopy(record.get("evidence")),
        "provenance": deepcopy(record.get("provenance")),
        "uncertainty": deepcopy(record.get("uncertainty")),
    }


def _language_gap(item: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source": "language_structure_json",
        "status": "degraded",
        "reason": str(item.get("reason") or "language_structure_degraded"),
    }
    for key in ("language", "path", "line", "detail", "expected", "observed", "limit"):
        if key in item:
            result[key] = deepcopy(item[key])
    return result


def _merge_language_relations(
    existing: list[dict[str, Any]],
    language: list[dict[str, Any]],
    *,
    max_items: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Keep one relevant language relation visible without erasing prior lanes."""
    if not language:
        return existing[:max_items], len(existing) > max_items
    if not existing:
        return language[:max_items], len(language) > max_items
    merged: list[dict[str, Any]] = []
    left = list(language)
    right = list(existing)
    while len(merged) < max_items and (left or right):
        if left:
            merged.append(left.pop(0))
            if len(merged) >= max_items:
                break
        if right:
            merged.append(right.pop(0))
    return merged, bool(left or right)


def merge_language_structure_into_impact_context(
    context: Mapping[str, Any],
    document: Mapping[str, Any],
    *,
    paths: Iterable[str] = (),
    target_symbol: str | None = None,
    max_items: int = 25,
    bundle_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Add optional language evidence only when it matches core bundle identity."""
    result = deepcopy(dict(context))
    if result.get("status") in {"blocked", "invalid"}:
        return result
    provenance = result.get("provenance")
    run_id = provenance.get("run_id") if isinstance(provenance, Mapping) else None
    digest = (
        provenance.get("canonical_dump_index_sha256")
        if isinstance(provenance, Mapping)
        else None
    )
    source = document.get("source")
    language_digest = (
        source.get("canonical_dump_index_sha256")
        if isinstance(source, Mapping)
        else None
    )
    coherent = (
        isinstance(run_id, str)
        and bool(run_id)
        and isinstance(digest, str)
        and bool(digest)
        and document.get("run_id") == run_id
        and language_digest == digest
    )
    if not coherent:
        gaps = result.setdefault("gaps", [])
        gaps.append(
            {
                "source": "language_structure_json",
                "status": "stale_or_mismatched",
                "reason": "language_structure_bundle_identity_mismatch",
                "expected": {"run_id": run_id, "canonical_dump_index_sha256": digest},
                "observed": {
                    "run_id": document.get("run_id"),
                    "canonical_dump_index_sha256": language_digest,
                },
            }
        )
        result.setdefault("composition", {})["language_structure"] = {
            "status": "rejected",
            "reason": "bundle_identity_mismatch",
        }
        if result.get("status") == "available":
            result["status"] = "partial"
        return result

    terms = (
        [target_symbol]
        if isinstance(target_symbol, str) and target_symbol.strip()
        else []
    )
    selected = select_language_structure_evidence(
        document,
        paths=paths,
        terms=terms,
        max_items=max_items,
        bundle_manifest_sha256=bundle_manifest_sha256,
    )
    records = selected["records"]
    definitions = [
        _language_definition_projection(record)
        for record in records
        if record.get("relation") == "definition"
    ]
    if target_symbol:
        definitions.sort(
            key=lambda item: (
                item.get("name") != target_symbol,
                str(item.get("path") or ""),
                int(item.get("start_line") or 0),
            )
        )
    existing_symbols = [
        item for item in result.get("target_symbols", []) if isinstance(item, dict)
    ]
    combined_symbols = existing_symbols + definitions
    result["target_symbols"] = combined_symbols[:max_items]

    language_relations = [
        _language_relation_projection(record, run_id=run_id, digest=digest)
        for record in records
        if record.get("relation") != "definition"
    ]
    existing_relations = [
        item for item in result.get("relations", []) if isinstance(item, dict)
    ]
    merged_relations, relation_truncated = _merge_language_relations(
        existing_relations,
        language_relations,
        max_items=max_items,
    )
    result["relations"] = merged_relations

    source_ranges = [
        item for item in result.get("source_ranges", []) if isinstance(item, dict)
    ]
    source_ranges.extend(
        _language_source_range_projection(record) for record in records
    )
    result["source_ranges"] = source_ranges[:max_items]

    gaps = result.setdefault("gaps", [])
    gaps.extend(_language_gap(item) for item in selected["degradations"])
    if selected["truncated"] or selected["degradation_truncated"]:
        gaps.append(
            {
                "source": "language_structure_json",
                "status": "degraded",
                "reason": "language_structure_selection_truncated",
                "available_record_count": selected["available_record_count"],
                "selected_record_count": selected["selected_record_count"],
                "available_degradation_count": selected["available_degradation_count"],
                "selected_degradation_count": selected["selected_degradation_count"],
            }
        )
    result.setdefault("truncation", {})["language_structure"] = bool(
        selected["truncated"] or selected["degradation_truncated"]
    )
    result.setdefault("truncation", {})["relations"] = bool(
        result.get("truncation", {}).get("relations") or relation_truncated
    )
    result.setdefault("composition", {})["language_structure"] = {
        "status": "used"
        if records or selected["degradations"]
        else "no_relevant_evidence",
        "selected_record_count": selected["selected_record_count"],
        "selected_degradation_count": selected["selected_degradation_count"],
        "filters": selected["filters"],
        "authority": AUTHORITY,
        "canonicality": CANONICALITY,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    statuses = result.setdefault("source_statuses", [])
    if isinstance(statuses, list) and not any(
        isinstance(item, Mapping) and item.get("source") == "language_structure_json"
        for item in statuses
    ):
        statuses.append(
            {
                "source": "language_structure_json",
                "status": "available",
                "run_id": run_id,
                "canonical_dump_index_sha256": digest,
            }
        )
    resolved_by_language = bool(definitions) or bool(records)
    if result.get("status") == "missing_target" and resolved_by_language:
        result["status"] = "partial" if result.get("gaps") else "available"
    elif result.get("status") == "available" and selected["degradations"]:
        result["status"] = "partial"
    return result


__all__ = [
    "AUTHORITY",
    "CANONICALITY",
    "CONTRACT_ID",
    "CONTRACT_VERSION",
    "DOES_NOT_ESTABLISH",
    "KIND",
    "RISK_CLASS",
    "VERSION",
    "build_language_structure_document",
    "compose_language_structure_evidence",
    "make_record",
    "merge_language_structure_into_impact_context",
    "select_language_structure_evidence",
    "source_range",
]
