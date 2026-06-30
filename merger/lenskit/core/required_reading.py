"""Required Reading Protocol resolver.

Formalises the REQUIRED_READING_BY_TASK matrix from the Agent Reading Pack as a
deterministic, machine-readable protocol.  The Agent Reading Pack remains the
navigation layer; canonical_md remains the sole content truth.
"""
from __future__ import annotations


_DOES_NOT_ESTABLISH = (
    "all_relevant_context_used",
    "answer_safe_without_citations",
    "claims_true",
    "forensic_ready",
    "repo_understood",
)

_PROFILES: dict[str, dict] = {
    "basic_repo_question": {
        "required": ("agent_reading_pack", "canonical_md"),
        "recommended": ("citation_map_jsonl",),
        "insufficient": ("sidecar-only claims without canonical verification",),
        "citation_required": False,
        "answer_checklist_required": True,
        "does_not_establish": _DOES_NOT_ESTABLISH,
    },
    "pr_review": {
        "required": (
            "agent_reading_pack",
            "canonical_md",
            "citation_map_jsonl",
            "post_emit_health",
        ),
        "recommended": ("bundle_surface_validation", "claim_evidence_map_json"),
        "insufficient": (
            "only reading canonical_md linearly",
            "treating health pass as review completeness",
        ),
        "citation_required": True,
        "answer_checklist_required": True,
        "does_not_establish": _DOES_NOT_ESTABLISH,
    },
    "roadmap_status_claim": {
        "required": ("agent_reading_pack", "canonical_md", "claim_evidence_map_json"),
        "recommended": ("citation_map_jsonl",),
        "insufficient": (
            "roadmap status without Claim Evidence Map",
            "roadmap status without canonical check",
        ),
        "citation_required": True,
        "answer_checklist_required": True,
        "does_not_establish": _DOES_NOT_ESTABLISH,
    },
    "artifact_surface_review": {
        "required": (
            "bundle_manifest",
            "bundle_surface_validation",
            "canonical_md",
            "post_emit_health",
        ),
        "recommended": ("output_health",),
        "insufficient": (
            "output_health alone",
            "treating health pass as claim truth",
        ),
        "citation_required": True,
        "answer_checklist_required": True,
        "does_not_establish": _DOES_NOT_ESTABLISH,
    },
    "retrieval_quality_review": {
        "required": (
            "canonical_md",
            "chunk_index_jsonl",
            "retrieval_eval_json",
            "sqlite_index",
        ),
        "recommended": ("docs/retrieval/*",),
        "insufficient": ("impressionistic retrieval claims without metrics",),
        "citation_required": True,
        "answer_checklist_required": True,
        "does_not_establish": _DOES_NOT_ESTABLISH,
    },
    "security_export_review": {
        "required": (
            "agent_reading_pack",
            "canonical_md",
            "export_safety_report",
            "post_emit_health",
        ),
        "recommended": (
            "agent_entry_manifest",
            "bundle_surface_validation",
            "output_health",
        ),
        "insufficient": (
            "export decision without export_safety_report",
            "redaction profile claim without post_emit_health",
            "treating export_safety_report as secret absence",
        ),
        "citation_required": True,
        "answer_checklist_required": True,
        "does_not_establish": _DOES_NOT_ESTABLISH,
    },
}


def default_required_reading_protocol() -> dict:
    """Return the canonical Required Reading Protocol dict.

    Deterministic: no timestamps, no I/O, no external state.
    Directly mirrors the REQUIRED_READING_BY_TASK matrix in agent_reading_pack.py.
    """
    task_profiles = {}
    for name, profile in _PROFILES.items():
        task_profiles[name] = {
            "required": sorted(profile["required"]),
            "recommended": sorted(profile["recommended"]),
            "insufficient": sorted(profile["insufficient"]),
            "citation_required": profile["citation_required"],
            "answer_checklist_required": profile["answer_checklist_required"],
            "does_not_establish": sorted(profile["does_not_establish"]),
        }
    return {
        "kind": "lenskit.required_reading_protocol",
        "version": "1.0",
        "default_profile": "basic_repo_question",
        "task_profiles": task_profiles,
        "does_not_establish": sorted(_DOES_NOT_ESTABLISH),
    }


def resolve_required_reading(
    protocol: dict,
    available_roles: set[str],
    task_profile: str,
) -> dict:
    """Resolve required reading status for a given task profile and available roles.

    Returns a deterministic dict with sorted lists and one of four status values:
      pass           — all required and all recommended roles present
      warn           — all required present, at least one recommended missing
      fail           — at least one required role missing
      not_applicable — task_profile not found in protocol
    """
    profiles = protocol.get("task_profiles", {})
    if task_profile not in profiles:
        return {
            "task_profile": task_profile,
            "required": [],
            "recommended": [],
            "insufficient": [],
            "available_required": [],
            "missing_required": [],
            "available_recommended": [],
            "missing_recommended": [],
            "status": "not_applicable",
            "citation_required": False,
            "answer_checklist_required": False,
            "does_not_establish": [],
        }

    p = profiles[task_profile]
    required = sorted(str(x) for x in p.get("required", ()))
    recommended = sorted(str(x) for x in p.get("recommended", ()))
    insufficient = sorted(str(x) for x in p.get("insufficient", ()))
    available = {str(x) for x in available_roles}

    req_set = set(required)
    rec_set = set(recommended)

    available_required = sorted(req_set & available)
    missing_required = sorted(req_set - available)
    available_recommended = sorted(rec_set & available)
    missing_recommended = sorted(rec_set - available)

    if missing_required:
        status = "fail"
    elif missing_recommended:
        status = "warn"
    else:
        status = "pass"

    return {
        "task_profile": task_profile,
        "required": required,
        "recommended": recommended,
        "insufficient": insufficient,
        "available_required": available_required,
        "missing_required": missing_required,
        "available_recommended": available_recommended,
        "missing_recommended": missing_recommended,
        "status": status,
        "citation_required": bool(p.get("citation_required", False)),
        "answer_checklist_required": bool(p.get("answer_checklist_required", False)),
        "does_not_establish": sorted(str(x) for x in p.get("does_not_establish", ())),
    }
