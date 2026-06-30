from typing import Dict, Any, Optional
import copy

def _build_candidate_surface(range_coverage: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Build a wrapper-safe diagnostic surface for candidate ids.

    This intentionally lives outside the strict context-bundle object. Candidate
    ids are navigation hints from range diagnostics, not proof that an answer is
    correct or that the retrieval set is complete.
    """
    if not isinstance(range_coverage, dict):
        return None

    entries = []
    for hit in range_coverage.get("per_hit", []):
        if not isinstance(hit, dict):
            continue
        candidates = hit.get("citation_id_candidates") or []
        if not candidates:
            continue
        entries.append({
            "chunk_id": hit.get("chunk_id"),
            "path": hit.get("path"),
            "range": hit.get("range"),
            "range_status": hit.get("status"),
            "range_ref_kind": hit.get("range_ref_kind"),
            "citation_id_candidates": copy.deepcopy(candidates),
        })

    if not entries:
        return None

    semantics = range_coverage.get("diagnostic_semantics", {})
    return {
        "kind": "lenskit.query_candidate_citation_surface",
        "version": "1.0",
        "source": "range_coverage",
        "hits": entries,
        "does_not_establish": list(semantics.get("does_not_establish", [
            "truth",
            "answer_correctness",
            "retrieval_completeness",
            "citation_sufficiency",
        ])),
    }


def project_output(result: Dict[str, Any], output_profile: Optional[str] = None) -> Dict[str, Any]:
    """
    Applies the output profile projection to the query result.

    Response Contracts (enforced here and documented in docs/architecture/api_query_contracts.md):
    - Case 1 (No Profile): Returns the raw result object (contains 'results' list, not 'hits').
    - Case 2 (Profile specified, e.g. 'agent_minimal'): Returns the canonical Context-Bundle
      structure directly at the top level (contains 'hits' array).
    - Case 3 (Profile + Diagnostics/Guardrails): Returns a wrapper {"context_bundle": ..., ...}
      to ensure the strict Context-Bundle schema is not violated.
      Wrapper is created if at least one applies:
        - query_trace is present
        - federation_conflicts is non-empty
                - cross_repo_links is non-empty
        - warnings is non-empty
      Note: Downstream API handlers (like /api/query) may append additional
      top-level fields to this wrapper (e.g., agent_query_session).

    Args:
        result: The raw evaluation result from `execute_query`.
        output_profile: The desired projection form (e.g. "agent_minimal", "ui_navigation").

    Returns:
        The projected response dict conforming to the contract.
    """
    res = copy.deepcopy(result)

    if output_profile and "context_bundle" in res:
        bundle = res["context_bundle"]
        if output_profile == "agent_minimal":
            # Agent minimal strips explain blocks from individual hits and returns only essentials
            for hit in bundle.get("hits", []):
                hit.pop("explain", None)
                hit.pop("graph_context", None)
                if "surrounding_context" in hit and hit["surrounding_context"] is None:
                    hit.pop("surrounding_context", None)
        elif output_profile == "lookup_minimal":
            for hit in bundle.get("hits", []):
                hit.pop("explain", None)
                hit.pop("graph_context", None)
                hit.pop("surrounding_context", None)
        elif output_profile == "review_context":
            for hit in bundle.get("hits", []):
                hit.pop("graph_context", None)
                if "surrounding_context" in hit and hit["surrounding_context"] is None:
                    hit.pop("surrounding_context", None)
        elif output_profile == "ui_navigation":
            # Include download links or identifiers for ui
            pass # Structure already ui-ready based on chunk_id/file

        # The bundle schema forbids additional top-level properties.
        # Wrapper is created if at least one applies:
        # - query_trace is present
        # - federation_conflicts is non-empty
        # - cross_repo_links is non-empty
        # - warnings is non-empty
        wrapper = {"context_bundle": bundle}
        needs_wrapper = False


        if "federation_trace" in res:
            wrapper["federation_trace"] = res["federation_trace"]
            needs_wrapper = True
        if "query_trace" in res:
            wrapper["query_trace"] = res["query_trace"]
            needs_wrapper = True

        if res.get("federation_conflicts"):
            wrapper["federation_conflicts"] = res["federation_conflicts"]
            needs_wrapper = True

        if res.get("cross_repo_links"):
            wrapper["cross_repo_links"] = res["cross_repo_links"]
            needs_wrapper = True

        if res.get("warnings"):
            wrapper["warnings"] = res["warnings"]
            needs_wrapper = True

        candidate_surface = _build_candidate_surface(res.get("range_coverage"))
        if candidate_surface:
            wrapper["citation_candidates"] = candidate_surface
            needs_wrapper = True

        if needs_wrapper:
            return wrapper

        return bundle

    return res
