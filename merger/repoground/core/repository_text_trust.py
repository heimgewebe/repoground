"""Fail-closed trust metadata for agent-visible repository text.

Classification is based only on caller-supplied provenance such as a repository
path or a bundle artifact role. The text itself is deliberately ignored: a
README, comment, fixture, or generated artifact cannot promote itself into an
instruction or authorization source by containing instruction-like wording.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any, Mapping

VERSION = "repoground.repository_text_trust/v1"
HANDOFF_VERSION = "repoground.agent_handoff/v1"

TRUST_CLASSES = (
    "operator_or_system_instruction",
    "maintainer_repository_rule",
    "raw_repository_content",
    "generated_artifact",
    "inferred_rule",
)

CONTROL_ACTIONS = (
    "execute_tools",
    "write_files",
    "use_network",
    "read_secrets",
    "merge_changes",
    "deploy_changes",
)

RESERVED_AUTHORITY_CLASSES = frozenset(
    {
        "control_plane_instruction",
        "operator_instruction",
        "system_instruction",
        "operator_or_system_instruction",
        "repository_rule",
        "inferred_rule",
    }
)

INSTRUCTION_HANDLING = {
    "operator_or_system_instruction": "external_control_plane_only",
    "maintainer_repository_rule": "repository_semantics_only",
    "raw_repository_content": "treat_as_untrusted_content",
    "generated_artifact": "treat_as_derived_content",
    "inferred_rule": "advisory_inference_only",
}

MAINTAINER_RULE_FILENAMES = frozenset(
    {
        "AGENTS.md",
        "CONTRIBUTING.md",
        "CODEOWNERS",
        "SECURITY.md",
    }
)

GENERATED_ARTIFACT_ROLES = frozenset(
    {
        "agent_entry_manifest",
        "agent_reading_pack",
        "bundle_manifest",
        "bundle_surface_validation",
        "citation_map_jsonl",
        "claim_evidence_map_json",
        "context_quality",
        "output_health",
        "post_emit_health",
        "python_symbol_index_json",
        "relation_cards_jsonl",
        "retrieval_eval",
        "snapshot_plan_json",
    }
)

BASE_NONCLAIMS = (
    "permission_to_execute_tools",
    "permission_to_write_files",
    "permission_to_use_network",
    "permission_to_read_secrets",
    "permission_to_merge_changes",
    "permission_to_deploy_changes",
    "runtime_correctness",
    "test_sufficiency",
    "review_completeness",
)

DESCRIPTOR_FIELDS = frozenset(
    {
        "version",
        "trust_class",
        "source_origin",
        "authority",
        "citation",
        "applicability",
        "derivation",
        "instruction_handling",
        "content_is_data",
        "control_boundary",
        "does_not_establish",
    }
)
ORIGIN_FIELDS = frozenset({"kind", "locator", "path", "artifact_role"})
AUTHORITY_FIELDS = frozenset({"class", "canonicality", "content_can_self_elevate"})
CITATION_FIELDS = frozenset(
    {
        "kind",
        "path",
        "artifact_role",
        "sha256",
        "citation_id",
        "range_ref",
        "source_range",
    }
)
APPLICABILITY_FIELDS = frozenset({"reason", "scope"})
DERIVATION_FIELDS = frozenset({"type", "canonical_repository_rule"})
CONTROL_BOUNDARY_FIELDS = frozenset(
    {
        "repository_content_grants_control_authority",
        "granted_actions",
        "external_authorization_required_for",
        "authorization_source",
    }
)


def _clean_optional_text(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must not be empty")
    if "\x00" in cleaned:
        raise ValueError(f"{field} must not contain NUL")
    return cleaned


def _require_exact_fields(
    value: Mapping[str, Any],
    expected_fields: frozenset[str],
    *,
    field: str,
) -> None:
    actual_fields = frozenset(value)
    if actual_fields != expected_fields:
        missing = sorted(expected_fields - actual_fields)
        unexpected = sorted(str(key) for key in actual_fields - expected_fields)
        raise ValueError(
            f"{field} fields are invalid: missing={missing}, unexpected={unexpected}"
        )


def _normalized_repo_path(path: Any) -> str | None:
    value = _clean_optional_text(path, field="path")
    if value is None:
        return None
    normalized = value.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError("path must be a repository-relative path")
    return pure.as_posix()


def _is_maintainer_rule_path(path: str | None) -> bool:
    if path is None:
        return False
    pure = PurePosixPath(path)
    if pure.name in MAINTAINER_RULE_FILENAMES:
        return True
    lowered = path.casefold()
    if lowered.startswith(("adr/", "docs/adr/", "docs/adrs/", "docs/decisions/")):
        return True
    if "/contracts/" in f"/{lowered}" or lowered.startswith("contracts/"):
        return True
    return pure.name.casefold().startswith("adr-")


def _citation_payload(
    citation: Mapping[str, Any] | None,
    *,
    path: str | None,
    artifact_role: str | None,
    source_sha256: str | None,
) -> dict[str, Any]:
    raw = dict(citation or {})
    result = {
        "kind": (
            "repository_range"
            if path
            else "artifact_reference"
            if artifact_role
            else "external_control_plane_reference"
        ),
        "path": path,
        "artifact_role": artifact_role,
        "sha256": source_sha256,
        "citation_id": raw.get("citation_id"),
        "range_ref": raw.get("range_ref"),
        "source_range": deepcopy(raw.get("source_range")),
    }
    if path is None and not any(
        isinstance(result[key], str) and result[key]
        for key in ("citation_id", "range_ref", "sha256")
    ):
        locator = raw.get("locator")
        result["range_ref"] = locator if isinstance(locator, str) and locator else None
    return result


def _trust_class(
    *,
    path: str | None,
    source_kind: str,
    artifact_role: str | None,
    inferred: bool,
) -> str:
    if inferred or source_kind == "inferred_rule":
        return "inferred_rule"
    if source_kind == "operator_or_system_instruction":
        if path is not None or artifact_role is not None:
            raise ValueError(
                "repository paths and artifacts cannot be classified as "
                "operator_or_system_instruction"
            )
        return "operator_or_system_instruction"
    if source_kind == "generated_artifact":
        return "generated_artifact"
    if _is_maintainer_rule_path(path):
        return "maintainer_repository_rule"
    if artifact_role in GENERATED_ARTIFACT_ROLES and artifact_role != "canonical_md":
        return "generated_artifact"
    return "raw_repository_content"


def _authority_defaults(trust_class: str) -> tuple[str, str]:
    return {
        "operator_or_system_instruction": ("control_plane_instruction", "external"),
        "maintainer_repository_rule": ("repository_rule", "maintainer_authored"),
        "raw_repository_content": ("repository_content", "content_source"),
        "generated_artifact": ("derived_projection", "derived"),
        "inferred_rule": ("inferred_rule", "derived"),
    }[trust_class]


def classify_repository_text(
    *,
    path: str | None,
    source_kind: str = "repository_path",
    artifact_role: str | None = None,
    citation: Mapping[str, Any] | None = None,
    applicability_reason: str,
    derivation_type: str = "direct",
    inferred: bool = False,
    source_sha256: str | None = None,
    declared_authority: str | None = None,
    canonicality: str | None = None,
) -> dict[str, Any]:
    """Return validated trust metadata without inspecting the source text."""
    if source_kind not in {
        "operator_or_system_instruction",
        "repository_path",
        "generated_artifact",
        "inferred_rule",
    }:
        raise ValueError("source_kind is not supported")
    normalized_path = _normalized_repo_path(path)
    normalized_role = _clean_optional_text(artifact_role, field="artifact_role")
    normalized_sha = _clean_optional_text(source_sha256, field="source_sha256")
    if normalized_sha is not None and (
        len(normalized_sha) != 64
        or any(character not in "0123456789abcdef" for character in normalized_sha)
    ):
        raise ValueError("source_sha256 must be a lowercase SHA-256 hex digest")
    reason = _clean_optional_text(applicability_reason, field="applicability_reason")
    if reason is None:
        raise ValueError("applicability_reason is required")
    derivation = _clean_optional_text(derivation_type, field="derivation_type")
    if derivation is None:
        raise ValueError("derivation_type is required")
    if derivation not in {
        "direct",
        "source_projection",
        "manifest_projection",
        "static_analysis",
        "inference",
    }:
        raise ValueError("derivation_type is not supported")

    trust_class = _trust_class(
        path=normalized_path,
        source_kind=source_kind,
        artifact_role=normalized_role,
        inferred=inferred,
    )
    default_authority, default_canonicality = _authority_defaults(trust_class)
    authority_class = (
        _clean_optional_text(declared_authority, field="declared_authority")
        or default_authority
    )
    authority_canonicality = (
        _clean_optional_text(canonicality, field="canonicality") or default_canonicality
    )
    if trust_class == "operator_or_system_instruction":
        authority_class = "control_plane_instruction"
        authority_canonicality = "external"
    elif trust_class == "maintainer_repository_rule":
        authority_class = "repository_rule"
        authority_canonicality = "maintainer_authored"
    elif trust_class == "inferred_rule":
        authority_class = "inferred_rule"
        authority_canonicality = "derived"
    elif authority_class in RESERVED_AUTHORITY_CLASSES:
        raise ValueError(
            "repository content cannot declare a reserved control or rule authority"
        )

    locator = normalized_path or normalized_role or source_kind
    descriptor = {
        "version": VERSION,
        "trust_class": trust_class,
        "source_origin": {
            "kind": source_kind,
            "locator": locator,
            "path": normalized_path,
            "artifact_role": normalized_role,
        },
        "authority": {
            "class": authority_class,
            "canonicality": authority_canonicality,
            "content_can_self_elevate": False,
        },
        "citation": _citation_payload(
            citation,
            path=normalized_path,
            artifact_role=normalized_role,
            source_sha256=normalized_sha,
        ),
        "applicability": {
            "reason": reason,
            "scope": normalized_path or normalized_role or "external_control_plane",
        },
        "derivation": {
            "type": "inference" if trust_class == "inferred_rule" else derivation,
            "canonical_repository_rule": False,
        },
        "instruction_handling": INSTRUCTION_HANDLING[trust_class],
        "content_is_data": trust_class != "operator_or_system_instruction",
        "control_boundary": {
            "repository_content_grants_control_authority": False,
            "granted_actions": [],
            "external_authorization_required_for": list(CONTROL_ACTIONS),
            "authorization_source": "grabowski_or_operator_policy",
        },
        "does_not_establish": list(
            BASE_NONCLAIMS
            + (
                ("canonical_repository_rule", "repository_truth")
                if trust_class == "inferred_rule"
                else ("repository_truth",)
            )
        ),
    }
    validate_trust_descriptor(descriptor)
    return descriptor


def _required_mapping(
    value: Any,
    *,
    field: str,
    expected_fields: frozenset[str],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} is required")
    _require_exact_fields(value, expected_fields, field=field)
    return value


def _validated_origin_path(value: Any) -> str | None:
    if value is None:
        return None
    normalized = _normalized_repo_path(value)
    if normalized != value:
        raise ValueError("source_origin.path must be normalized")
    return normalized


def _validated_artifact_role(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = _clean_optional_text(value, field="artifact_role")
    if cleaned != value:
        raise ValueError("source_origin.artifact_role must be normalized")
    return cleaned


def _validate_origin_class_consistency(
    trust_class: str,
    *,
    origin_kind: Any,
    origin_path: str | None,
    artifact_role: str | None,
) -> None:
    allowed_kinds = {
        "operator_or_system_instruction": {"operator_or_system_instruction"},
        "maintainer_repository_rule": {"repository_path"},
        "raw_repository_content": {"repository_path"},
        "generated_artifact": {"generated_artifact", "repository_path"},
        "inferred_rule": {"inferred_rule", "repository_path"},
    }[trust_class]
    if origin_kind not in allowed_kinds:
        raise ValueError(f"{trust_class} origin is invalid")
    if trust_class == "operator_or_system_instruction" and (
        origin_path is not None or artifact_role is not None
    ):
        raise ValueError(
            "repository content cannot be an operator or system instruction"
        )
    if trust_class in {"maintainer_repository_rule", "raw_repository_content"} and (
        origin_path is None
    ):
        raise ValueError("repository text trust requires a repository path origin")
    if trust_class == "maintainer_repository_rule" and not _is_maintainer_rule_path(
        origin_path
    ):
        raise ValueError("maintainer repository rule path is not recognized")


def _validate_origin(
    descriptor: Mapping[str, Any],
    trust_class: str,
) -> tuple[str | None, str | None]:
    origin = _required_mapping(
        descriptor.get("source_origin"),
        field="source_origin",
        expected_fields=ORIGIN_FIELDS,
    )
    origin_kind = origin.get("kind")
    if origin_kind not in {
        "operator_or_system_instruction",
        "repository_path",
        "generated_artifact",
        "inferred_rule",
    }:
        raise ValueError("source_origin.kind is invalid")
    origin_path = _validated_origin_path(origin.get("path"))
    artifact_role = _validated_artifact_role(origin.get("artifact_role"))
    expected_locator = origin_path or artifact_role or origin_kind
    if origin.get("locator") != expected_locator:
        raise ValueError("source_origin.locator does not match source provenance")
    _validate_origin_class_consistency(
        trust_class,
        origin_kind=origin_kind,
        origin_path=origin_path,
        artifact_role=artifact_role,
    )
    return origin_path, artifact_role


def _required_normalized_text(value: Any, *, field: str) -> str:
    cleaned = _clean_optional_text(value, field=field)
    if cleaned is None or cleaned != value:
        raise ValueError(f"{field} is required and must be normalized")
    return cleaned


def _validate_authority(
    descriptor: Mapping[str, Any],
    trust_class: str,
) -> None:
    authority = _required_mapping(
        descriptor.get("authority"),
        field="authority",
        expected_fields=AUTHORITY_FIELDS,
    )
    if authority.get("content_can_self_elevate") is not False:
        raise ValueError("content must not self-elevate authority")
    authority_class = _required_normalized_text(
        authority.get("class"),
        field="authority.class",
    )
    canonicality = _required_normalized_text(
        authority.get("canonicality"),
        field="authority.canonicality",
    )
    fixed_authority = {
        "operator_or_system_instruction": ("control_plane_instruction", "external"),
        "maintainer_repository_rule": ("repository_rule", "maintainer_authored"),
        "inferred_rule": ("inferred_rule", "derived"),
    }.get(trust_class)
    if (
        fixed_authority is not None
        and (authority_class, canonicality) != fixed_authority
    ):
        raise ValueError(f"{trust_class} authority is invalid")
    if trust_class in {"raw_repository_content", "generated_artifact"} and (
        authority_class in RESERVED_AUTHORITY_CLASSES or canonicality == "external"
    ):
        raise ValueError("repository content cannot carry reserved authority")


def _expected_citation_kind(
    origin_path: str | None,
    artifact_role: str | None,
) -> str:
    if origin_path is not None:
        return "repository_range"
    if artifact_role is not None:
        return "artifact_reference"
    return "external_control_plane_reference"


def _validate_optional_sha256(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("citation.sha256 must be a lowercase SHA-256 hex digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError("citation.sha256 must be a lowercase SHA-256 hex digest")


def _validate_optional_citation_text(value: Any, *, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"citation.{field} must be a normalized string or null")


def _validate_citation_locators(citation: Mapping[str, Any]) -> None:
    _validate_optional_sha256(citation.get("sha256"))
    for field in ("citation_id", "range_ref"):
        _validate_optional_citation_text(citation.get(field), field=field)
    source_range = citation.get("source_range")
    if source_range is not None and not isinstance(source_range, Mapping):
        raise ValueError("citation.source_range must be an object or null")
    exact_citation_present = any(
        isinstance(citation.get(field), str) and bool(citation.get(field))
        for field in ("citation_id", "range_ref", "sha256")
    ) or (isinstance(source_range, Mapping) and bool(source_range))
    if not exact_citation_present:
        raise ValueError("an exact citation locator is required")


def _validate_citation(
    descriptor: Mapping[str, Any],
    *,
    origin_path: str | None,
    artifact_role: str | None,
) -> None:
    citation = _required_mapping(
        descriptor.get("citation"),
        field="citation",
        expected_fields=CITATION_FIELDS,
    )
    if citation.get("path") != origin_path:
        raise ValueError("citation.path must match source_origin.path")
    if citation.get("artifact_role") != artifact_role:
        raise ValueError(
            "citation.artifact_role must match source_origin.artifact_role"
        )
    expected_kind = _expected_citation_kind(origin_path, artifact_role)
    if citation.get("kind") != expected_kind:
        raise ValueError("citation.kind does not match source provenance")
    _validate_citation_locators(citation)


def _validate_applicability(descriptor: Mapping[str, Any]) -> None:
    applicability = _required_mapping(
        descriptor.get("applicability"),
        field="applicability",
        expected_fields=APPLICABILITY_FIELDS,
    )
    for field in ("reason", "scope"):
        _required_normalized_text(
            applicability.get(field),
            field=f"applicability.{field}",
        )


def _validate_derivation(
    descriptor: Mapping[str, Any],
    trust_class: str,
) -> None:
    derivation = _required_mapping(
        descriptor.get("derivation"),
        field="derivation",
        expected_fields=DERIVATION_FIELDS,
    )
    derivation_type = derivation.get("type")
    if derivation_type not in {
        "direct",
        "source_projection",
        "manifest_projection",
        "static_analysis",
        "inference",
    }:
        raise ValueError("derivation.type is invalid")
    if derivation.get("canonical_repository_rule") is not False:
        raise ValueError(
            "derived context must not claim canonical repository-rule status"
        )
    if trust_class == "inferred_rule" and derivation_type != "inference":
        raise ValueError("inferred rules must remain non-canonical")


def _validate_instruction_semantics(
    descriptor: Mapping[str, Any],
    trust_class: str,
) -> None:
    if descriptor.get("instruction_handling") != INSTRUCTION_HANDLING[trust_class]:
        raise ValueError("instruction_handling does not match trust_class")
    expected_content_is_data = trust_class != "operator_or_system_instruction"
    if descriptor.get("content_is_data") is not expected_content_is_data:
        raise ValueError("content_is_data does not match trust_class")


def _validate_control_boundary(descriptor: Mapping[str, Any]) -> None:
    boundary = _required_mapping(
        descriptor.get("control_boundary"),
        field="control_boundary",
        expected_fields=CONTROL_BOUNDARY_FIELDS,
    )
    if boundary.get("repository_content_grants_control_authority") is not False:
        raise ValueError("repository content must not grant control authority")
    if boundary.get("granted_actions") != []:
        raise ValueError("trust descriptors must not grant actions")
    required_actions = tuple(boundary.get("external_authorization_required_for", ()))
    if required_actions != CONTROL_ACTIONS:
        raise ValueError("all control actions must require external authorization")
    if boundary.get("authorization_source") != "grabowski_or_operator_policy":
        raise ValueError("control authorization source is invalid")


def _validate_nonclaims(
    descriptor: Mapping[str, Any],
    trust_class: str,
) -> None:
    nonclaims = descriptor.get("does_not_establish")
    if not isinstance(nonclaims, list):
        raise ValueError("trust non-claims must be a list of non-empty strings")
    if not all(isinstance(item, str) and item for item in nonclaims):
        raise ValueError("trust non-claims must be a list of non-empty strings")
    if len(nonclaims) != len(set(nonclaims)):
        raise ValueError("trust non-claims must be unique")
    if not set(BASE_NONCLAIMS).issubset(nonclaims):
        raise ValueError("required trust non-claims are missing")
    if "repository_truth" not in nonclaims:
        raise ValueError("repository truth non-claim is required")
    if trust_class == "inferred_rule" and "canonical_repository_rule" not in nonclaims:
        raise ValueError("inferred rule canonicality non-claim is required")


def validate_trust_descriptor(descriptor: Mapping[str, Any]) -> None:
    """Enforce the authority boundary independently of JSON Schema validation."""
    if not isinstance(descriptor, Mapping):
        raise ValueError("trust descriptor must be an object")
    _require_exact_fields(descriptor, DESCRIPTOR_FIELDS, field="trust descriptor")
    if descriptor.get("version") != VERSION:
        raise ValueError("trust descriptor version is invalid")
    trust_class = descriptor.get("trust_class")
    if trust_class not in TRUST_CLASSES:
        raise ValueError("trust_class is invalid")
    origin_path, artifact_role = _validate_origin(descriptor, trust_class)
    _validate_authority(descriptor, trust_class)
    _validate_citation(
        descriptor,
        origin_path=origin_path,
        artifact_role=artifact_role,
    )
    _validate_applicability(descriptor)
    _validate_derivation(descriptor, trust_class)
    _validate_instruction_semantics(descriptor, trust_class)
    _validate_control_boundary(descriptor)
    _validate_nonclaims(descriptor, trust_class)


def trust_model_summary() -> dict[str, Any]:
    return {
        "version": VERSION,
        "trust_classes": list(TRUST_CLASSES),
        "classification_basis": "provenance_only_content_never_self_elevates",
        "control_actions": list(CONTROL_ACTIONS),
        "authorization_source": "grabowski_or_operator_policy",
    }


def _required_handoff_text(
    context_plan: Mapping[str, Any],
    field: str,
) -> str:
    value = _clean_optional_text(context_plan.get(field), field=field)
    if value is None:
        raise ValueError(f"{field} is required")
    return value


def _copy_handoff_context(context_plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    selected = context_plan.get("selected_context")
    if not isinstance(selected, list):
        raise ValueError("context plan selected_context must be a list")
    copied_context: list[dict[str, Any]] = []
    for item in selected:
        if not isinstance(item, Mapping):
            raise ValueError("selected context item must be an object")
        trust = item.get("trust")
        if not isinstance(trust, Mapping):
            raise ValueError("selected context item is missing trust metadata")
        validate_trust_descriptor(trust)
        copied_context.append(deepcopy(dict(item)))
    return copied_context


def _handoff_freshness(context_plan: Mapping[str, Any]) -> Mapping[str, Any] | None:
    signals = context_plan.get("signals")
    if not isinstance(signals, Mapping):
        raise ValueError("context plan signals are required")
    availability = signals.get("availability")
    if not isinstance(availability, Mapping):
        raise ValueError("context plan availability signal is required")
    if "freshness" not in availability:
        raise ValueError("context plan freshness signal is required")
    freshness = availability.get("freshness")
    if freshness is not None and not isinstance(freshness, Mapping):
        raise ValueError("context plan freshness must be an object or null")
    return freshness


def _validated_handoff_status(context_plan: Mapping[str, Any]) -> str:
    status = context_plan.get("status")
    if status not in {"pass", "warn", "fail", "invalid"}:
        raise ValueError("context plan status is invalid")
    return status


def build_agent_handoff(context_plan: Mapping[str, Any]) -> dict[str, Any]:
    """Copy trust and freshness metadata into a bounded agent handoff."""
    status = _validated_handoff_status(context_plan)
    task = _required_handoff_text(context_plan, "task")
    task_profile = _required_handoff_text(context_plan, "task_profile")
    bundle_manifest = _required_handoff_text(context_plan, "bundle_manifest")
    bundle_run_id = _clean_optional_text(
        context_plan.get("bundle_run_id"),
        field="bundle_run_id",
    )
    copied_context = _copy_handoff_context(context_plan)
    freshness = _handoff_freshness(context_plan)
    return {
        "kind": "repoground.agent_handoff",
        "version": HANDOFF_VERSION,
        "status": status,
        "task": task,
        "task_profile": task_profile,
        "bundle_manifest": bundle_manifest,
        "bundle_run_id": bundle_run_id,
        "freshness": deepcopy(freshness),
        "context": copied_context,
        "trust_model": trust_model_summary(),
        "control_boundary": {
            "repository_content_grants_control_authority": False,
            "external_authorization_required_for": list(CONTROL_ACTIONS),
            "authorization_source": "grabowski_or_operator_policy",
        },
        "does_not_establish": [
            "permission_to_execute_tools",
            "permission_to_write_files",
            "permission_to_use_network",
            "permission_to_read_secrets",
            "permission_to_merge_changes",
            "permission_to_deploy_changes",
            "freshness_beyond_the_source_context_plan",
            "answer_correctness",
        ],
    }
