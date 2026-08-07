"""Task-profile gated activation for optional hybrid semantic retrieval.

The activation contract composes existing T013 routing evidence with an exact
model/config/index/manifest/repository binding. It never promotes a route by
aggregation: a profile must be explicitly promoted, or a ``keep_opt_in`` route
must be requested with an explicit operator opt-in. Blocked profiles remain on
the deterministic lexical fallback.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .task_profile_routing import evaluate_evidence, load_evidence

REQUIRED_MODEL_BINDING_KEYS = (
    "model_name",
    "model_revision",
    "model_artifact_sha256",
    "tokenizer_sha256",
)

DOES_NOT_ESTABLISH = [
    "semantic_truth",
    "retrieval_completeness",
    "repository_understanding",
    "answer_correctness",
    "test_sufficiency",
    "merge_readiness",
]


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def canonical_json_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_file_binding(
    path: str | Path,
    declared_sha256: str,
    *,
    field: str,
    errors: list[str],
) -> None:
    candidate = Path(path)
    if not candidate.is_file():
        errors.append(f"{field}_path must reference a readable regular file")
        return
    try:
        observed_sha256 = file_sha256(candidate)
    except OSError:
        errors.append(f"{field}_path must reference a readable regular file")
        return
    if _is_sha256(declared_sha256) and observed_sha256 != declared_sha256:
        errors.append(f"{field}_sha256 must match {field}_path contents")


def validate_model_binding(
    model_binding: Mapping[str, Any],
    embedding_policy: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    for key in REQUIRED_MODEL_BINDING_KEYS:
        value = model_binding.get(key)
        if key.endswith("sha256"):
            if not _is_sha256(value):
                errors.append(f"model_binding.{key} must be a lowercase SHA-256")
        elif not isinstance(value, str) or not value:
            errors.append(f"model_binding.{key} must be a non-empty string")
    if model_binding.get("model_name") != embedding_policy.get("model_name"):
        errors.append("model_binding.model_name must match embedding_policy.model_name")
    provider = embedding_policy.get("provider")
    if provider != "local":
        errors.append(
            "profile-gated hybrid activation currently requires provider=local"
        )
    return errors


def resolve_profile_activation(
    routing_evidence: Mapping[str, Any] | str | Path,
    *,
    task_profile: str,
    explicit_opt_in: bool,
) -> dict[str, Any]:
    evidence = (
        load_evidence(routing_evidence)
        if isinstance(routing_evidence, (str, Path))
        else dict(routing_evidence)
    )
    decision_report = evaluate_evidence(evidence)
    decisions = {
        item["task_profile"]: item for item in decision_report["profile_decisions"]
    }
    profile = decisions.get(task_profile)
    if profile is None:
        raise ValueError(f"unknown task profile: {task_profile}")
    decision = profile["decision"]
    if decision == "promote":
        activated = True
        activation_mode = "profile_promoted"
    elif decision == "keep_opt_in" and explicit_opt_in:
        activated = True
        activation_mode = "explicit_profile_opt_in"
    else:
        activated = False
        activation_mode = (
            "opt_in_required" if decision == "keep_opt_in" else "profile_gate_blocked"
        )
    return {
        "kind": "repoground.hybrid_retrieval_profile_activation",
        "version": "1.0",
        "task_id": evidence.get("task_id"),
        "source_commit": evidence.get("source_commit"),
        "task_profile": task_profile,
        "profile_decision": decision,
        "profile_reasons": list(profile.get("reasons") or []),
        "candidate_route": profile.get("candidate_route"),
        "current_default": profile.get("current_default"),
        "fallback": profile.get("fallback"),
        "explicit_opt_in": explicit_opt_in,
        "activated": activated,
        "activation_mode": activation_mode,
        "global_default_promoted": False,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def build_hybrid_route_binding(
    *,
    activation: Mapping[str, Any],
    embedding_policy: Mapping[str, Any],
    model_binding: Mapping[str, Any],
    index_path: str | Path,
    index_sha256: str,
    bundle_manifest_path: str | Path,
    bundle_manifest_sha256: str,
    repository_commit: str,
    routing_evidence_path: str | Path,
) -> dict[str, Any]:
    errors = validate_model_binding(model_binding, embedding_policy)
    if not _is_sha256(index_sha256):
        errors.append("index_sha256 must be a lowercase SHA-256")
    if not _is_sha256(bundle_manifest_sha256):
        errors.append("bundle_manifest_sha256 must be a lowercase SHA-256")
    _verify_file_binding(
        index_path,
        index_sha256,
        field="index",
        errors=errors,
    )
    _verify_file_binding(
        bundle_manifest_path,
        bundle_manifest_sha256,
        field="bundle_manifest",
        errors=errors,
    )
    if not (
        isinstance(repository_commit, str)
        and len(repository_commit) == 40
        and all(character in "0123456789abcdef" for character in repository_commit)
    ):
        errors.append(
            "repository_commit must be a 40-character lowercase hexadecimal commit"
        )
    evidence_path = Path(routing_evidence_path).resolve()
    binding = {
        "kind": "repoground.hybrid_retrieval_binding",
        "version": "1.0",
        "status": "bound" if not errors else "invalid",
        "activation": dict(activation),
        "model": dict(model_binding),
        "embedding_policy": {
            "value": dict(embedding_policy),
            "sha256": canonical_json_sha256(embedding_policy),
        },
        "index": {
            "path": str(Path(index_path)),
            "sha256": index_sha256,
        },
        "bundle_manifest": {
            "path": str(Path(bundle_manifest_path).resolve()),
            "sha256": bundle_manifest_sha256,
        },
        "repository_commit": repository_commit,
        "routing_evidence": {
            "path": str(evidence_path),
            "sha256": file_sha256(evidence_path),
            "task_id": activation.get("task_id"),
            "source_commit": activation.get("source_commit"),
        },
        "fallback": "deterministic_lexical",
        "errors": errors,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    return binding


def execute_profile_gated_query(
    *,
    index_path: str | Path,
    query_text: str,
    k: int,
    routing_evidence: Mapping[str, Any] | str | Path,
    task_profile: str,
    explicit_opt_in: bool,
    embedding_policy: Mapping[str, Any],
    model_binding: Mapping[str, Any],
    index_sha256: str,
    bundle_manifest_path: str | Path,
    bundle_manifest_sha256: str,
    repository_commit: str,
    filters: Mapping[str, str | None] | None = None,
    read_only: bool = True,
    validated_read_only_source_path: str | Path | None = None,
) -> dict[str, Any]:
    """Execute the existing lexical+semantic path only after the profile gate.

    A blocked or non-opted-in profile executes the deterministic lexical
    fallback with the same index and query. An activated route passes the exact
    bound embedding policy into ``execute_query``.
    """
    from .query_core import execute_query

    evidence_path = (
        Path(routing_evidence) if isinstance(routing_evidence, (str, Path)) else None
    )
    if evidence_path is None:
        raise ValueError(
            "routing_evidence must be a committed evidence file for runtime activation"
        )
    activation = resolve_profile_activation(
        evidence_path,
        task_profile=task_profile,
        explicit_opt_in=explicit_opt_in,
    )
    binding = build_hybrid_route_binding(
        activation=activation,
        embedding_policy=embedding_policy,
        model_binding=model_binding,
        index_path=index_path,
        index_sha256=index_sha256,
        bundle_manifest_path=bundle_manifest_path,
        bundle_manifest_sha256=bundle_manifest_sha256,
        repository_commit=repository_commit,
        routing_evidence_path=evidence_path,
    )
    if activation["activated"] and binding["status"] != "bound":
        raise ValueError(
            "activated hybrid retrieval requires a complete exact binding: "
            + "; ".join(binding["errors"])
        )
    effective_policy = dict(embedding_policy) if activation["activated"] else None
    result = execute_query(
        Path(index_path),
        query_text,
        k=k,
        filters=dict(filters or {}),
        embedding_policy=effective_policy,
        read_only=read_only,
        _validated_read_only_source_path=(
            Path(validated_read_only_source_path)
            if validated_read_only_source_path is not None
            else None
        ),
    )
    result["hybrid_retrieval"] = {
        "activation": activation,
        "binding": binding,
        "executed_route": (
            "profile_gated_hybrid_semantic"
            if activation["activated"]
            else "deterministic_lexical_fallback"
        ),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    return result
