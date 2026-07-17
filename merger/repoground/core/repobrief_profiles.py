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

# Export semantics are part of the snapshot profile contract. Keeping them
# beside the artifact rules prevents the export gate and export report from
# drifting into separate, incomplete profile vocabularies.
PROFILE_EXPORT_SEMANTICS = {
    "local-private": {
        "agent_facing": False,
        "public_facing": False,
        "redaction_required": False,
        "post_emit_health_required": False,
        "agent_export_gate_required": False,
        "exportable": True,
    },
    "agent-portable": {
        "agent_facing": True,
        "public_facing": False,
        "redaction_required": True,
        "post_emit_health_required": True,
        "agent_export_gate_required": True,
        "exportable": True,
    },
    "full-max": {
        "agent_facing": True,
        "public_facing": False,
        "redaction_required": True,
        "post_emit_health_required": True,
        "agent_export_gate_required": True,
        "exportable": True,
    },
    "pr-review": {
        "agent_facing": True,
        "public_facing": False,
        "redaction_required": True,
        "post_emit_health_required": True,
        "agent_export_gate_required": True,
        "exportable": True,
    },
    "security-export-review": {
        "agent_facing": False,
        "public_facing": False,
        "redaction_required": True,
        "post_emit_health_required": True,
        "agent_export_gate_required": True,
        "exportable": True,
    },
    "public-share": {
        "agent_facing": False,
        "public_facing": True,
        "redaction_required": True,
        "post_emit_health_required": True,
        "agent_export_gate_required": True,
        "exportable": True,
    },
    "ci-artifact": {
        "agent_facing": True,
        "public_facing": False,
        "redaction_required": True,
        "post_emit_health_required": True,
        "agent_export_gate_required": True,
        "exportable": True,
    },
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
    "snapshot_plan_json",
    "pr_delta_cards_jsonl",
    "relation_cards_jsonl",
    "retrieval_eval_json",
    "python_symbol_index_json",
    "python_call_graph_json",
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
    "snapshot_plan_json": REQ_RECOMMENDED,
    "pr_delta_cards_jsonl": REQ_NA,
    "relation_cards_jsonl": REQ_OPTIONAL,
    "retrieval_eval_json": REQ_OPTIONAL,
    "python_symbol_index_json": REQ_OPTIONAL,
    "python_call_graph_json": REQ_OPTIONAL,
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
        "python_symbol_index_json": REQ_RECOMMENDED,
        "python_call_graph_json": REQ_RECOMMENDED,
    },
    "full-max": {
        **BASE_RULES,
        "sqlite_index": REQ_REQUIRED,
        "export_safety_report": REQ_REQUIRED,
        "pr_delta_cards_jsonl": REQ_OPTIONAL,
        "relation_cards_jsonl": REQ_RECOMMENDED,
        "retrieval_eval_json": REQ_RECOMMENDED,
        "python_symbol_index_json": REQ_RECOMMENDED,
        "python_call_graph_json": REQ_RECOMMENDED,
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
        "citation_map_jsonl": REQ_OPTIONAL,
        "chunk_index_jsonl": REQ_OPTIONAL,
        "sqlite_index": REQ_EXCLUDED,
        "export_safety_report": REQ_REQUIRED,
        "retrieval_eval_json": REQ_NA,
        "python_symbol_index_json": REQ_EXCLUDED,
        "python_call_graph_json": REQ_EXCLUDED,
    },
    "ci-artifact": {
        **BASE_RULES,
        "citation_map_jsonl": REQ_RECOMMENDED,
        "export_safety_report": REQ_RECOMMENDED,
        "retrieval_eval_json": REQ_RECOMMENDED,
        "python_symbol_index_json": REQ_RECOMMENDED,
        "python_call_graph_json": REQ_RECOMMENDED,
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
        raise ValueError(f"unknown RepoGround profile: {profile}") from exc
    missing = [role for role in ARTIFACT_ORDER if role not in rules]
    invalid = sorted({value for value in rules.values() if value not in VALID_REQUIREMENTS})
    if missing or invalid:
        raise ValueError(f"invalid RepoGround profile policy: missing={missing!r} invalid={invalid!r}")
    return rules


def profile_level(profile: str) -> str:
    try:
        return PROFILE_LEVELS[profile]
    except KeyError as exc:
        raise ValueError(f"unknown RepoGround profile: {profile}") from exc


def profile_export_semantics(profile: str) -> dict[str, bool]:
    _rules(profile)
    try:
        semantics = PROFILE_EXPORT_SEMANTICS[profile]
    except KeyError as exc:
        raise ValueError(f"missing RepoGround export semantics: {profile}") from exc
    return {key: bool(value) for key, value in semantics.items()}


def profile_policy(profile: str) -> dict[str, Any]:
    rules = _rules(profile)
    return {
        "profile": profile,
        "generator_level": profile_level(profile),
        "artifact_rules": {role: rules[role] for role in ARTIFACT_ORDER},
        "valid_requirements": list(VALID_REQUIREMENTS),
        "export_semantics": profile_export_semantics(profile),
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


PROFILE_DEFAULT_OUTPUT_MODES = {
    "public-share": "archive",
}

OUTPUT_MODE_ARTIFACT_ROLES = {
    "archive": frozenset(),
    "retrieval": frozenset({"sqlite_index"}),
    "dual": frozenset({"sqlite_index"}),
}


def profile_default_output_mode(profile: str) -> str:
    _rules(profile)
    return PROFILE_DEFAULT_OUTPUT_MODES.get(profile, "dual")


def profile_output_mode_conflicts(profile: str, output_mode: str) -> tuple[str, ...]:
    if output_mode not in OUTPUT_MODE_ARTIFACT_ROLES:
        raise ValueError(f"unknown RepoGround output mode: {output_mode}")
    excluded = set(profile_excluded_roles(profile))
    produced = set(OUTPUT_MODE_ARTIFACT_ROLES[output_mode])
    return tuple(sorted(excluded & produced))


def profile_output_mode_plan(profile: str, requested_output_mode: str | None = None) -> dict[str, Any]:
    selected_output_mode = requested_output_mode or profile_default_output_mode(profile)
    conflicts = profile_output_mode_conflicts(profile, selected_output_mode)
    return {
        "profile": profile,
        "requested_output_mode": requested_output_mode,
        "selected_output_mode": selected_output_mode,
        "defaulted": requested_output_mode is None,
        "conflicts": list(conflicts),
        "excluded_roles": list(profile_excluded_roles(profile)),
        "conflict_candidate_roles": sorted(OUTPUT_MODE_ARTIFACT_ROLES[selected_output_mode]),
    }
