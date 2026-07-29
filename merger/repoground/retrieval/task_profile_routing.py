"""Revision-bound retrieval routing evidence and per-profile decisions.

This module is deliberately diagnostic. It evaluates committed evidence but does
not mutate routing configuration or authorize a default promotion.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

KIND = "repoground.retrieval_task_profile_routing_evidence"
VERSION = "1.0"
EVALUATOR_VERSION = "1.0"
TASK_PROFILES = (
    "basic_repo_question",
    "review",
    "change_impact",
    "find_relevant_tests",
    "ground_claim",
)
METRIC_KEYS = (
    "recall_at_k",
    "mrr",
    "expected_target_recall",
    "citation_health",
    "range_health",
    "miss_taxonomy",
    "context_bytes",
    "tool_calls",
)
DECISIONS = {"promote", "keep_opt_in", "blocked"}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_evidence(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("routing evidence must be a JSON object")
    return value


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _is_commit(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


def _validate_binding(binding: object, label: str, errors: list[str]) -> None:
    if not isinstance(binding, Mapping):
        errors.append(f"{label} must be an object")
        return
    status = binding.get("status")
    if status not in {"available", "digest_bound", "unavailable"}:
        errors.append(f"{label}.status must be available, digest_bound or unavailable")
        return
    if status in {"available", "digest_bound"}:
        location_key = "path" if status == "available" else "locator"
        if not isinstance(binding.get(location_key), str) or not binding.get(location_key):
            errors.append(f"{label}.{location_key} is required when {status}")
        if not _is_sha256(binding.get("sha256")):
            errors.append(f"{label}.sha256 must be a lowercase SHA-256")
    elif not isinstance(binding.get("reason"), str) or not binding.get("reason"):
        errors.append(f"{label}.reason is required when unavailable")


def validate_evidence(evidence: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if evidence.get("kind") != KIND:
        errors.append(f"kind must be {KIND}")
    if evidence.get("version") != VERSION:
        errors.append(f"version must be {VERSION}")
    if evidence.get("evaluator_version") != EVALUATOR_VERSION:
        errors.append(f"evaluator_version must be {EVALUATOR_VERSION}")
    if evidence.get("global_default_promoted") is not False:
        errors.append("global_default_promoted must remain false")
    if not isinstance(evidence.get("task_id"), str) or not evidence.get("task_id"):
        errors.append("task_id is required")
    if not _is_commit(evidence.get("source_commit")):
        errors.append("source_commit must be a 40-character commit")
    if not isinstance(evidence.get("does_not_establish"), list) or not evidence.get("does_not_establish"):
        errors.append("does_not_establish must be non-empty")

    goldset = evidence.get("goldset")
    _validate_binding(goldset, "goldset", errors)
    if isinstance(goldset, Mapping):
        repositories = goldset.get("repositories")
        profiles = goldset.get("task_profiles")
        if not isinstance(repositories, list) or len(set(repositories)) < 2:
            errors.append("goldset must bind at least two repositories")
        if sorted(profiles or []) != sorted(TASK_PROFILES):
            errors.append("goldset task_profiles must cover the five canonical profiles")
        coverage = goldset.get("measurement_coverage")
        if not isinstance(coverage, Mapping):
            errors.append("goldset.measurement_coverage must be an object")
        elif sorted(coverage) != sorted(METRIC_KEYS):
            errors.append("goldset.measurement_coverage must cover all canonical metrics")

    raw_profiles = evidence.get("profiles")
    if not isinstance(raw_profiles, list):
        return errors + ["profiles must be an array"]
    profile_names = [item.get("task_profile") for item in raw_profiles if isinstance(item, Mapping)]
    if sorted(profile_names) != sorted(TASK_PROFILES):
        errors.append("profiles must contain each canonical task profile exactly once")

    for profile in raw_profiles:
        if not isinstance(profile, Mapping):
            errors.append("profile entries must be objects")
            continue
        name = profile.get("task_profile", "<unknown>")
        available_routes = profile.get("available_routes")
        if (
            not isinstance(available_routes, list)
            or not available_routes
            or any(not isinstance(route, str) or not route for route in available_routes)
            or len(set(available_routes)) != len(available_routes)
        ):
            errors.append(f"{name}.available_routes must contain unique non-empty strings")
            available_routes = []
        current_default = profile.get("current_default")
        if current_default not in available_routes:
            errors.append(f"{name}.current_default must be an available route")
        candidate_route = profile.get("candidate_route")
        if candidate_route is not None and candidate_route not in available_routes:
            errors.append(f"{name}.candidate_route must be null or an available route")
        candidate_measurement_id = profile.get("candidate_measurement_id")
        if candidate_route is not None and (
            not isinstance(candidate_measurement_id, str) or not candidate_measurement_id
        ):
            errors.append(f"{name}.candidate_measurement_id is required for a candidate route")
        if not isinstance(profile.get("fallback"), str) or profile.get("fallback") not in available_routes:
            errors.append(f"{name}.fallback must be an available route")
        if not isinstance(profile.get("non_claims"), list) or not profile.get("non_claims"):
            errors.append(f"{name}.non_claims must be non-empty")
        measurements = profile.get("measurements")
        if not isinstance(measurements, list) or not measurements:
            errors.append(f"{name}.measurements must be non-empty")
            continue
        for index, measurement in enumerate(measurements):
            label = f"{name}.measurements[{index}]"
            if not isinstance(measurement, Mapping):
                errors.append(f"{label} must be an object")
                continue
            if not isinstance(measurement.get("id"), str) or not measurement.get("id"):
                errors.append(f"{label}.id is required")
            if measurement.get("status") not in {"measured", "partial", "not_measured"}:
                errors.append(f"{label}.status is invalid")
            if measurement.get("route") not in available_routes:
                errors.append(f"{label}.route must be an available route")
            if not isinstance(measurement.get("repository"), str) or not measurement.get("repository"):
                errors.append(f"{label}.repository is required")
            if not isinstance(measurement.get("comparison_group"), str) or not measurement.get("comparison_group"):
                errors.append(f"{label}.comparison_group is required")
            if (
                not isinstance(measurement.get("limitations"), list)
                or not measurement.get("limitations")
                or any(not isinstance(item, str) or not item for item in measurement.get("limitations", []))
            ):
                errors.append(f"{label}.limitations must be non-empty strings")
            if not _is_commit(measurement.get("repository_commit")):
                errors.append(f"{label}.repository_commit must be a 40-character commit")
            for binding_name in ("dataset", "bundle_manifest", "index", "source_artifact"):
                _validate_binding(measurement.get(binding_name), f"{label}.{binding_name}", errors)
            evaluator = measurement.get("evaluator")
            if not isinstance(evaluator, Mapping):
                errors.append(f"{label}.evaluator must be an object")
            else:
                if not isinstance(evaluator.get("version"), str) or not evaluator.get("version"):
                    errors.append(f"{label}.evaluator.version is required")
                if not isinstance(evaluator.get("path"), str) or not evaluator.get("path"):
                    errors.append(f"{label}.evaluator.path is required")
                if not _is_sha256(evaluator.get("sha256")):
                    errors.append(f"{label}.evaluator.sha256 must be a SHA-256")
            metrics = measurement.get("metrics")
            if not isinstance(metrics, Mapping):
                errors.append(f"{label}.metrics must be an object")
                continue
            missing = sorted(set(METRIC_KEYS) - set(metrics))
            extra = sorted(set(metrics) - set(METRIC_KEYS))
            if missing:
                errors.append(f"{label}.metrics missing: {', '.join(missing)}")
            if extra:
                errors.append(f"{label}.metrics contains unknown keys: {', '.join(extra)}")
            for key in (
                "recall_at_k",
                "mrr",
                "expected_target_recall",
                "citation_health",
                "range_health",
            ):
                value = metrics.get(key)
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not 0 <= value <= 1
                ):
                    errors.append(f"{label}.metrics.{key} must be null or a number from 0 to 1")
            for key in ("context_bytes", "tool_calls"):
                value = metrics.get(key)
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, int) or value < 0
                ):
                    errors.append(f"{label}.metrics.{key} must be null or a non-negative integer")
            miss_taxonomy = metrics.get("miss_taxonomy")
            if miss_taxonomy is not None and (
                not isinstance(miss_taxonomy, Mapping)
                or any(
                    not isinstance(key, str)
                    or not key
                    or isinstance(value, bool)
                    or not isinstance(value, int)
                    or value < 0
                    for key, value in miss_taxonomy.items()
                )
            ):
                errors.append(
                    f"{label}.metrics.miss_taxonomy must be null or non-negative integer counts"
                )
            if measurement.get("status") == "measured" and any(
                metrics.get(key) is None for key in METRIC_KEYS
            ):
                errors.append(f"{label} is measured but has null metrics")

        candidate_matches = [
            measurement
            for measurement in measurements
            if isinstance(measurement, Mapping)
            and measurement.get("id") == candidate_measurement_id
        ]
        if candidate_route is not None:
            if len(candidate_matches) != 1:
                errors.append(f"{name}.candidate_measurement_id must identify exactly one measurement")
            elif candidate_matches[0].get("route") != candidate_route:
                errors.append(f"{name}.candidate_measurement_id must use candidate_route")
    measurement_by_id: dict[str, Mapping[str, Any]] = {}
    for profile in raw_profiles:
        if not isinstance(profile, Mapping):
            continue
        for measurement in profile.get("measurements") or []:
            if isinstance(measurement, Mapping) and isinstance(measurement.get("id"), str):
                existing = measurement_by_id.get(measurement["id"])
                if existing is not None and existing != measurement:
                    errors.append(f"measurement id {measurement['id']} has conflicting definitions")
                measurement_by_id[measurement["id"]] = measurement

    if isinstance(goldset, Mapping) and isinstance(goldset.get("measurement_coverage"), Mapping):
        for metric_key in METRIC_KEYS:
            references = goldset["measurement_coverage"].get(metric_key)
            if not isinstance(references, list) or not references:
                errors.append(f"goldset.measurement_coverage.{metric_key} must be non-empty")
                continue
            for measurement_id in references:
                measurement = measurement_by_id.get(measurement_id)
                if measurement is None:
                    errors.append(
                        f"goldset.measurement_coverage.{metric_key} references unknown measurement {measurement_id}"
                    )
                    continue
                metrics = measurement.get("metrics")
                if not isinstance(metrics, Mapping) or metrics.get(metric_key) is None:
                    errors.append(
                        f"goldset.measurement_coverage.{metric_key} references an unmeasured value in {measurement_id}"
                    )
    return errors


def _numeric(metrics: Mapping[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _core_quality_passes(metrics: Mapping[str, Any], thresholds: Mapping[str, Any]) -> bool:
    checks = (
        ("recall_at_k", "minimum_recall_at_k"),
        ("mrr", "minimum_mrr"),
        ("expected_target_recall", "minimum_expected_target_recall"),
        ("citation_health", "minimum_citation_health"),
        ("range_health", "minimum_range_health"),
    )
    observed = 0
    for metric_key, threshold_key in checks:
        value = _numeric(metrics, metric_key)
        threshold = _numeric(thresholds, threshold_key)
        if value is None or threshold is None:
            continue
        observed += 1
        if value < threshold:
            return False
    return observed >= 2


def evaluate_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    errors = validate_evidence(evidence)
    if errors:
        raise ValueError("invalid routing evidence: " + "; ".join(errors))

    decisions: list[dict[str, Any]] = []
    for profile in evidence["profiles"]:
        thresholds = profile.get("thresholds") or {}
        candidate_route = profile.get("candidate_route")
        candidate_measurement_id = profile.get("candidate_measurement_id")
        candidates = [
            measurement
            for measurement in profile["measurements"]
            if measurement.get("id") == candidate_measurement_id
        ]
        reasons: list[str] = []
        decision = "blocked"
        missing_metrics: list[str] = []
        if not candidate_route:
            reasons.append("candidate_route_missing")
        elif not candidates:
            reasons.append("candidate_measurement_missing")
        else:
            candidate = candidates[0]
            metrics = candidate["metrics"]
            missing_metrics = [key for key in METRIC_KEYS if metrics.get(key) is None]
            if candidate["status"] == "not_measured":
                reasons.append("candidate_not_measured")
            elif not _core_quality_passes(metrics, thresholds):
                reasons.append("profile_quality_gate_not_met")
            elif missing_metrics:
                decision = "keep_opt_in"
                reasons.extend(("partial_metric_lineage", "explicit_profile_promotion_not_authorized"))
            elif profile.get("promotion_authority") != "explicit_profile_decision":
                decision = "keep_opt_in"
                reasons.append("explicit_profile_promotion_not_authorized")
            else:
                decision = "promote"
                reasons.append("complete_profile_gate_passed")
        decisions.append(
            {
                "task_profile": profile["task_profile"],
                "candidate_route": candidate_route,
                "decision": decision,
                "reasons": reasons,
                "missing_metrics": missing_metrics,
                "current_default": profile.get("current_default"),
                "fallback": profile["fallback"],
                "does_not_establish": list(profile["non_claims"]),
            }
        )

    return {
        "kind": "repoground.retrieval_task_profile_routing_decision",
        "version": VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "task_id": evidence.get("task_id"),
        "source_commit": evidence.get("source_commit"),
        "profile_decisions": decisions,
        "global_default_promoted": False,
        "global_decision": "no_global_promotion_by_aggregation",
        "does_not_establish": [
            "routing mutation authority",
            "answer correctness",
            "review completeness",
            "global retrieval completeness",
            "merge readiness",
        ],
    }
