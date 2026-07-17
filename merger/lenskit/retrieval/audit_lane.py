"""Deterministic planning for bounded, evidence-oriented audit lanes.

The planner turns changed repository paths and an optional review question into a
small, ordered set of specialist audit lanes. It does not execute agents, inspect
repository contents, produce findings, or claim review completeness.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Sequence

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_MAX_LANES = 8
_MAX_CHANGED_PATHS = 5_000
_MAX_PATH_CHARS = 4_096
_MAX_PATH_CHARS_TOTAL = 2 * 1024 * 1024
_MAX_REVIEW_QUERY_CHARS = 8_192
_PATH_SIGNAL_WEIGHT = 3
_QUERY_SIGNAL_WEIGHT = 1
_PATH_JOINER = "\x1f"
_PHRASE_ALIAS_PATTERNS = (
    (re.compile(r"\bfalse[ _\-‐‑‒–—]+positives?\b"), "falsepositive"),
    (re.compile(r"\bn[ ]*\+[ ]*1\b"), "nplusone"),
)
_TOKEN_ALIASES = {
    "abfragen": "query",
    "absturz": "failure",
    "abstürze": "failure",
    "berechtigung": "permission",
    "berechtigungen": "permission",
    "caches": "cache",
    "deployments": "deploy",
    "errors": "error",
    "failures": "failure",
    "fehler": "error",
    "geheimnis": "secret",
    "geheimnisse": "secret",
    "indices": "index",
    "leistung": "performance",
    "migrationen": "migration",
    "migrations": "migration",
    "permissions": "permission",
    "queries": "query",
    "races": "race",
    "releases": "release",
    "secrets": "secret",
    "skalierung": "scale",
    "tests": "test",
    "tokens": "token",
    "zugänglichkeit": "accessibility",
    "zwischenspeicher": "cache",
}


@dataclass(frozen=True)
class AuditLaneDefinition:
    lane_id: str
    title: str
    path_signals: tuple[str, ...]
    query_signals: tuple[str, ...]
    required_evidence: tuple[str, ...]
    suggested_checks: tuple[str, ...]


_LANES: tuple[AuditLaneDefinition, ...] = (
    AuditLaneDefinition(
        lane_id="concurrency_toctou",
        title="Concurrency and TOCTOU",
        path_signals=("lock", "lease", "atomic", "publish", "generation", "transaction"),
        query_signals=("race", "toctou", "concurrent", "atomic", "lock", "lease"),
        required_evidence=("implementation", "negative_tests", "state_transition"),
        suggested_checks=("interleaving_review", "failure_window_review", "rollback_review"),
    ),
    AuditLaneDefinition(
        lane_id="storage_integrity",
        title="Storage and migration integrity",
        path_signals=("migration", "schema", "database", "sqlite", "store", "registry"),
        query_signals=("migration", "database", "integrity", "schema", "corruption"),
        required_evidence=("schema_or_contract", "implementation", "migration_tests"),
        suggested_checks=("transaction_boundary_review", "backward_compatibility_review"),
    ),
    AuditLaneDefinition(
        lane_id="cache_publication",
        title="Cache and publication coherence",
        path_signals=("cache", "bundle", "manifest", "generation", "pointer", "publish"),
        query_signals=("cache", "stale", "publication", "coherence", "generation"),
        required_evidence=("producer", "consumer", "invalidation_tests"),
        suggested_checks=("staleness_review", "partial_write_review", "reader_visibility_review"),
    ),
    AuditLaneDefinition(
        lane_id="auth_boundaries",
        title="Authentication and authority boundaries",
        path_signals=("auth", "permission", "token", "secret", "session", "policy"),
        query_signals=("auth", "permission", "privilege", "token", "secret", "authority"),
        required_evidence=("policy_or_contract", "enforcement", "negative_tests"),
        suggested_checks=("bypass_review", "default_deny_review", "credential_scope_review"),
    ),
    AuditLaneDefinition(
        lane_id="deploy_rollback",
        title="Deployment and rollback contracts",
        path_signals=("deploy", "release", "rollback", "workflow", "systemd", "kubernetes"),
        query_signals=("deploy", "release", "rollback", "live", "reconcile"),
        required_evidence=("deployment_path", "rollback_path", "operational_tests"),
        suggested_checks=("failure_recovery_review", "source_identity_review", "readback_review"),
    ),
    AuditLaneDefinition(
        lane_id="ui_accessibility",
        title="UI, touch and accessibility",
        path_signals=("ui", "webui", "component", "css", "svelte", "accessibility", "touch"),
        query_signals=("ui", "ux", "touch", "focus", "keyboard", "accessibility", "responsive"),
        required_evidence=("implementation", "interaction_tests", "viewport_or_a11y_evidence"),
        suggested_checks=("focus_review", "touch_target_review", "layering_review"),
    ),
    AuditLaneDefinition(
        lane_id="performance_scale",
        title="Performance and scale",
        path_signals=("index", "stream", "scan", "query", "graph", "cache", "batch"),
        query_signals=("performance", "scale", "memory", "latency", "stream", "nplusone"),
        required_evidence=("hot_path", "boundedness", "measurement_or_regression_test"),
        suggested_checks=("full_scan_review", "allocation_review", "complexity_review"),
    ),
    AuditLaneDefinition(
        lane_id="test_failure_semantics",
        title="Tests and failure semantics",
        path_signals=("test", "validator", "error", "exception", "result", "status"),
        query_signals=("test", "failure", "error", "exception", "fallback", "falsepositive"),
        required_evidence=("implementation", "negative_tests", "error_contract"),
        suggested_checks=(
            "fail_open_review",
            "error_propagation_review",
            "assertion_quality_review",
        ),
    ),
)

_DOES_NOT_ESTABLISH = (
    "The plan does not establish that any defect exists.",
    "A selected lane does not establish relevance, correctness, severity, or completeness.",
    "An unselected lane does not establish that its risk is absent.",
    "Suggested checks are planning hints, not executed evidence.",
    "The plan does not authorize agent execution, repository writes, issue creation, or merges.",
)


def _tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    for pattern, replacement in _PHRASE_ALIAS_PATTERNS:
        normalized = pattern.sub(replacement, normalized)
    tokens = set(_TOKEN_RE.findall(normalized))
    tokens.update(_TOKEN_ALIASES[token] for token in tuple(tokens) if token in _TOKEN_ALIASES)
    return tokens


def _normalize_paths(changed_paths: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    total_chars = 0
    for index, raw in enumerate(changed_paths, start=1):
        if index > _MAX_CHANGED_PATHS:
            raise ValueError(f"changed_paths must contain at most {_MAX_CHANGED_PATHS} paths")
        if not isinstance(raw, str):
            raise ValueError("changed_paths must contain strings")
        if not raw or any(character in raw for character in ("\x00", "\n", "\r", "\\")):
            raise ValueError("changed_paths must contain non-empty POSIX repository paths")
        if len(raw) > _MAX_PATH_CHARS:
            raise ValueError(f"changed path exceeds {_MAX_PATH_CHARS} characters")
        total_chars += len(raw)
        if total_chars > _MAX_PATH_CHARS_TOTAL:
            raise ValueError("changed_paths exceed the aggregate character budget")

        path = PurePosixPath(raw)
        text = path.as_posix()
        if (
            path.is_absolute()
            or text in {"", "."}
            or ".." in path.parts
            or raw != text
        ):
            raise ValueError("changed_paths must be canonical relative POSIX repository paths")
        if text in seen:
            raise ValueError(f"changed_paths must not contain duplicates: {text}")
        seen.add(text)
        normalized.append(text)
    return normalized


def _validate_inputs(
    changed_paths: Iterable[str], review_query: str, max_lanes: int
) -> list[str]:
    if isinstance(changed_paths, (str, bytes)):
        raise ValueError("changed_paths must be an iterable of repository paths")
    try:
        iter(changed_paths)
    except TypeError as exc:
        raise ValueError("changed_paths must be an iterable of repository paths") from exc
    if not isinstance(review_query, str):
        raise ValueError("review_query must be a string")
    if "\x00" in review_query or len(review_query) > _MAX_REVIEW_QUERY_CHARS:
        raise ValueError(f"review_query must not exceed {_MAX_REVIEW_QUERY_CHARS} characters")
    if isinstance(max_lanes, bool) or not isinstance(max_lanes, int):
        raise ValueError("max_lanes must be an integer")
    if not 1 <= max_lanes <= _MAX_LANES:
        raise ValueError(f"max_lanes must be between 1 and {_MAX_LANES}")
    return _normalize_paths(changed_paths)


def _matching_signals(tokens: set[str], signals: Sequence[str]) -> list[str]:
    return [signal for signal in signals if signal in tokens]


def _rank_lanes(
    paths: Sequence[str], review_query: str
) -> tuple[list[tuple[int, int, AuditLaneDefinition, list[str], list[str]]], int, int]:
    query_tokens = _tokens(review_query)
    path_tokens = _tokens(_PATH_JOINER.join(paths))

    ranked: list[tuple[int, int, AuditLaneDefinition, list[str], list[str]]] = []
    for order, lane in enumerate(_LANES):
        path_matches = _matching_signals(path_tokens, lane.path_signals)
        query_matches = _matching_signals(query_tokens, lane.query_signals)
        score = (_PATH_SIGNAL_WEIGHT * len(path_matches)) + (
            _QUERY_SIGNAL_WEIGHT * len(query_matches)
        )
        if score:
            ranked.append((score, order, lane, path_matches, query_matches))
    return sorted(ranked, key=lambda item: (-item[0], item[1])), len(path_tokens), len(query_tokens)


def _render_lane(
    score: int,
    lane: AuditLaneDefinition,
    path_matches: Sequence[str],
    query_matches: Sequence[str],
) -> dict[str, Any]:
    return {
        "id": lane.lane_id,
        "title": lane.title,
        "score": score,
        "reasons": {
            "path_signals": list(path_matches),
            "query_signals": list(query_matches),
        },
        "required_evidence": list(lane.required_evidence),
        "suggested_checks": list(lane.suggested_checks),
    }


def _render_lanes(
    ranked: Sequence[tuple[int, int, AuditLaneDefinition, list[str], list[str]]],
    max_lanes: int,
) -> list[dict[str, Any]]:
    selected = [
        _render_lane(score, lane, path_matches, query_matches)
        for score, _order, lane, path_matches, query_matches in ranked[:max_lanes]
    ]
    if selected:
        return selected
    return [
        {
            "id": "general_change_integrity",
            "title": "General change integrity",
            "score": 0,
            "reasons": {"path_signals": [], "query_signals": []},
            "required_evidence": ["implementation", "tests", "error_paths"],
            "suggested_checks": ["contract_review", "regression_review", "failure_path_review"],
        }
    ]


def plan_audit_lanes(
    changed_paths: Iterable[str],
    *,
    review_query: str = "",
    max_lanes: int = 6,
) -> dict[str, Any]:
    """Return a deterministic, bounded audit-lane plan.

    Path matches carry weight three because they are tied to the concrete change
    surface. Query matches carry weight one because natural-language requests are
    untrusted routing hints. Ties preserve the fixed lane catalog order. If nothing
    matches, a single general integrity lane is emitted.
    """

    paths = _validate_inputs(changed_paths, review_query, max_lanes)
    ranked, path_token_count, query_token_count = _rank_lanes(paths, review_query)
    lane_plans = _render_lanes(ranked, max_lanes)
    return {
        "version": "audit_lane_plan.v1",
        "authority": "navigation_index",
        "risk_class": "diagnostic",
        "inputs": {
            "changed_paths": paths,
            "review_query": review_query,
            "max_lanes": max_lanes,
        },
        "routing": {
            "method": "weighted_signal_match",
            "path_signal_weight": _PATH_SIGNAL_WEIGHT,
            "query_signal_weight": _QUERY_SIGNAL_WEIGHT,
            "tie_break": "catalog_order",
            "selected_count": len(lane_plans),
            "candidate_lane_count": len(ranked),
            "path_token_count": path_token_count,
            "query_token_count": query_token_count,
            "fallback_used": not ranked,
        },
        "lanes": lane_plans,
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }
