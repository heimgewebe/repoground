from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

REQ_REQUIRED = "required"
REQ_RECOMMENDED = "recommended"
REQ_OPTIONAL = "optional"
REQ_NA = "not_applicable"
REQ_EXCLUDED = "profile_excluded"

AVAIL_AVAILABLE = "available"
AVAIL_MISSING = "missing"
AVAIL_MISSING_REQUIRED = "missing_required"
AVAIL_NA = "not_applicable"
AVAIL_EXCLUDED = "profile_excluded"
AVAIL_EXCLUDED_PRESENT = "profile_excluded_present"

VALID_REQUIREMENTS = (REQ_REQUIRED, REQ_RECOMMENDED, REQ_OPTIONAL, REQ_NA, REQ_EXCLUDED)

PROFILE_LEVELS = {
    "local-private": "dev",
    "agent-portable": "max",
    "full-max": "max",
    "pr-review": "dev",
    "security-export-review": "max",
    "public-share": "summary",
    "ci-artifact": "dev",
}

ARTIFACT_ORDER = (
    "canonical_md",
    "bundle_manifest",
    "agent_reading_pack",
    "citation_map_jsonl",
    "chunk_index_jsonl",
    "sqlite_index",
    "output_health",
    "post_emit_health",
    "bundle_surface_validation",
    "export_safety_report",
    "pr_delta_cards_jsonl",
    "relation_cards_jsonl",
    "retrieval_eval_json",
)

BASE_RULES = {
    "canonical_md": REQ_REQUIRED,
    "bundle_manifest": REQ_REQUIRED,
    "agent_reading_pack": REQ_REQUIRED,
    "citation_map_jsonl": REQ_REQUIRED,
    "chunk_index_jsonl": REQ_REQUIRED,
    "sqlite_index": REQ_OPTIONAL,
    "output_health": REQ_REQUIRED,
    "post_emit_health": REQ_REQUIRED,
    "bundle_surface_validation": REQ_REQUIRED,
    "export_safety_report": REQ_OPTIONAL,
    "pr_delta_cards_jsonl": REQ_NA,
    "relation_cards_jsonl": REQ_OPTIONAL,
    "retrieval_eval_json": REQ_OPTIONAL,
}

PROFILE_ARTIFACT_RULES = {
    "local-private": {
        **BASE_RULES,
        "citation_map_jsonl": REQ_OPTIONAL,
        "chunk_index_jsonl": REQ_RECOMMENDED,
        "bundle_surface_validation": REQ_RECOMMENDED,
    },
    "agent-portable": {
        **BASE_RULES,
        "sqlite_index": REQ_RECOMMENDED,
        "export_safety_report": REQ_REQUIRED,
        "retrieval_eval_json": REQ_RECOMMENDED,
    },
    "full-max": {
        **BASE_RULES,
        "sqlite_index": REQ_REQUIRED,
        "export_safety_report": REQ_REQUIRED,
        "pr_delta_cards_jsonl": REQ_OPTIONAL,
        "relation_cards_jsonl": REQ_RECOMMENDED,
        "retrieval_eval_json": REQ_RECOMMENDED,
    },
    "pr-review": {
        **BASE_RULES,
        "export_safety_report": REQ_RECOMMENDED,
        "pr_delta_cards_jsonl": REQ_REQUIRED,
        "relation_cards_jsonl": REQ_RECOMMENDED,
    },
    "security-export-review": {
        **BASE_RULES,
        "export_safety_report": REQ_REQUIRED,
        "pr_delta_cards_jsonl": REQ_OPTIONAL,
    },
    "public-share": {
        **BASE_RULES,
        "sqlite_index": REQ_EXCLUDED,
        "export_safety_report": REQ_REQUIRED,
    },
    "ci-artifact": {
        **BASE_RULES,
        "citation_map_jsonl": REQ_RECOMMENDED,
        "export_safety_report": REQ_RECOMMENDED,
        "retrieval_eval_json": REQ_RECOMMENDED,
    },
}


@dataclass(frozen=True)
class ProfileArtifactStatus:
    role: str
    requirement: str
    availability: str


def profile_names() -> tuple[str, ...]:
    return tuple(PROFILE_ARTIFACT_RULES)


def _rules(profile: str) -> Mapping[str, str]:
    try:
        rules = PROFILE_ARTIFACT_RULES[profile]
    except KeyError as exc:
        raise ValueError(f"unknown RepoBrief profile: {profile}") from exc
    missing = [role for role in ARTIFACT_ORDER if role not in rules]
    invalid = sorted({value for value in rules.values() if value not in VALID_REQUIREMENTS})
    if missing or invalid:
        raise ValueError(f"invalid RepoBrief profile policy: missing={missing!r} invalid={invalid!r}")
    return rules


def profile_level(profile: str) -> str:
    try:
        return PROFILE_LEVELS[profile]
    except KeyError as exc:
        raise ValueError(f"unknown RepoBrief profile: {profile}") from exc


def profile_policy(profile: str) -> dict[str, Any]:
    rules = _rules(profile)
    return {
        "profile": profile,
        "generator_level": profile_level(profile),
        "artifact_rules": {role: rules[role] for role in ARTIFACT_ORDER},
        "valid_requirements": list(VALID_REQUIREMENTS),
    }


def availability_for(requirement: str, present: bool) -> str:
    if requirement == REQ_NA:
        return AVAIL_NA
    if requirement == REQ_EXCLUDED:
        return AVAIL_EXCLUDED_PRESENT if present else AVAIL_EXCLUDED
    if present:
        return AVAIL_AVAILABLE
    if requirement == REQ_REQUIRED:
        return AVAIL_MISSING_REQUIRED
    return AVAIL_MISSING


def evaluate_profile(profile: str, present_roles: Iterable[str]) -> dict[str, Any]:
    rules = _rules(profile)
    present = set(present_roles)
    artifact_statuses = [
        ProfileArtifactStatus(
            role=role,
            requirement=rules[role],
            availability=availability_for(rules[role], role in present),
        )
        for role in ARTIFACT_ORDER
    ]
    missing_required = [s.role for s in artifact_statuses if s.availability == AVAIL_MISSING_REQUIRED]
    missing_recommended = [
        s.role
        for s in artifact_statuses
        if s.requirement == REQ_RECOMMENDED and s.availability == AVAIL_MISSING
    ]
    excluded_present = [
        s.role for s in artifact_statuses if s.availability == AVAIL_EXCLUDED_PRESENT
    ]
    status = "fail" if missing_required or excluded_present else "warn" if missing_recommended else "pass"
    return {
        "profile": profile,
        "status": status,
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
        "profile_excluded_present": excluded_present,
        "artifacts": [s.__dict__ for s in artifact_statuses],
    }


def present_roles_from_manifest(bundle_manifest: Mapping[str, Any]) -> set[str]:
    roles = {"bundle_manifest"}
    artifacts = bundle_manifest.get("artifacts", [])
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if isinstance(artifact, dict) and isinstance(artifact.get("role"), str):
                roles.add(artifact["role"])
    links = bundle_manifest.get("links", {})
    if isinstance(links, dict):
        if links.get("post_emit_health_path"):
            roles.add("post_emit_health")
        if links.get("bundle_surface_validation_path") or links.get("surface_validation_path"):
            roles.add("bundle_surface_validation")
    return roles


def profile_excluded_roles(profile: str) -> tuple[str, ...]:
    rules = _rules(profile)
    return tuple(role for role in ARTIFACT_ORDER if rules[role] == REQ_EXCLUDED)
