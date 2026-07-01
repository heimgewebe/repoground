from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


_DOES_NOT_ESTABLISH = [
    "exact_token_count",
    "model_context_fit",
    "answer_correctness",
    "repo_understood",
    "claims_true",
    "review_completeness",
    "runtime_behavior",
    "forensic_ready",
]


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _estimate_tokens(byte_count: int, bytes_per_token: float) -> int:
    if byte_count <= 0:
        return 0
    return int(math.ceil(byte_count / bytes_per_token))


def build_token_budget_report(
    bundle_manifest: dict[str, Any],
    *,
    source_path: str | None = None,
    context_budget_tokens: int = 128_000,
    bytes_per_token: float = 4.0,
) -> dict[str, Any]:
    """Build a diagnostic token-budget estimate from a bundle manifest.

    The estimate is byte-based. It intentionally avoids tokenizer/model claims.
    """
    if context_budget_tokens < 1:
        raise ValueError("context_budget_tokens must be at least 1")
    if bytes_per_token <= 0:
        raise ValueError("bytes_per_token must be greater than 0")

    manifest = _require_mapping(bundle_manifest, "bundle_manifest")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("bundle_manifest.artifacts must be a list")

    errors: list[str] = []
    warnings: list[str] = []
    artifact_reports: list[dict[str, Any]] = []
    by_role: dict[str, dict[str, int]] = {}

    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            errors.append(f"artifact_{index}_not_object")
            continue
        role = artifact.get("role")
        path = artifact.get("path")
        byte_count = artifact.get("bytes")
        if not isinstance(role, str) or not role:
            errors.append(f"artifact_{index}_missing_role")
            role = "unknown"
        if not isinstance(path, str) or not path:
            errors.append(f"artifact_{index}_missing_path")
            path = ""
        if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
            errors.append(f"artifact_{index}_invalid_bytes")
            byte_count = 0

        estimated_tokens = _estimate_tokens(byte_count, bytes_per_token)
        share = round(estimated_tokens / context_budget_tokens, 6)
        role_bucket = by_role.setdefault(role, {"artifact_count": 0, "bytes": 0, "estimated_tokens": 0})
        role_bucket["artifact_count"] += 1
        role_bucket["bytes"] += byte_count
        role_bucket["estimated_tokens"] += estimated_tokens
        artifact_reports.append({
            "role": role,
            "path": path,
            "bytes": byte_count,
            "estimated_tokens": estimated_tokens,
            "context_budget_share": share,
        })

    total_bytes = sum(item["bytes"] for item in artifact_reports)
    total_tokens = sum(item["estimated_tokens"] for item in artifact_reports)
    over_budget = total_tokens > context_budget_tokens
    if over_budget:
        warnings.append("estimated_tokens_exceed_context_budget")

    sorted_artifacts = sorted(
        artifact_reports,
        key=lambda item: (-item["estimated_tokens"], item["role"], item["path"]),
    )
    largest = sorted_artifacts[:10]
    role_rows = [
        {"role": role, **values}
        for role, values in sorted(by_role.items(), key=lambda item: (-item[1]["estimated_tokens"], item[0]))
    ]

    status = "fail" if errors else ("warn" if warnings else "pass")
    return {
        "kind": "lenskit.token_budget_report",
        "version": "1.0",
        "source_manifest": source_path,
        "run_id": manifest.get("run_id"),
        "estimator": {
            "method": "bytes_divided_by_constant",
            "bytes_per_token": bytes_per_token,
            "exact_tokenizer": False,
        },
        "context_budget_tokens": context_budget_tokens,
        "status": status,
        "totals": {
            "artifact_count": len(artifact_reports),
            "bytes": total_bytes,
            "estimated_tokens": total_tokens,
            "budget_remaining_tokens": max(context_budget_tokens - total_tokens, 0),
            "budget_overflow_tokens": max(total_tokens - context_budget_tokens, 0),
            "estimated_budget_share": round(total_tokens / context_budget_tokens, 6),
        },
        "by_role": role_rows,
        "largest_artifacts": largest,
        "warnings": warnings,
        "errors": errors,
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }


def build_token_budget_report_from_bundle_manifest(
    bundle_manifest_path: Path,
    *,
    context_budget_tokens: int = 128_000,
    bytes_per_token: float = 4.0,
) -> dict[str, Any]:
    path = Path(bundle_manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return build_token_budget_report(
        manifest,
        source_path=str(path),
        context_budget_tokens=context_budget_tokens,
        bytes_per_token=bytes_per_token,
    )
