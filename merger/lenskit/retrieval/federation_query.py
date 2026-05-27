import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from .query_core import execute_query
from ..core.federation import validate_federation

def _build_cross_repo_links(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Builds minimal, schema-valid cross_repo_links for heuristic co-occurrence between repos.

    Strategy: When results from at least two distinct bundles/repos appear in the final
    returned results, one "co_occurrence" link is built per unique sorted
    (source_repo, target_repo) pair. evidence_refs reference only chunk IDs that are
    present in the supplied results list (payload-local: always verifiable by the client).

    confidence is always "inferred" — no identity, dependency, or semantic equality
    claims are made. co_occurrence means only: both repos returned results for the
    same query.

    Ranking and result ordering are not modified.
    """
    repo_chunks: Dict[str, List[str]] = {}
    for hit in results:
        repo_id = hit.get("federation_bundle", "")
        chunk_id = hit.get("chunk_id", "")
        if repo_id and chunk_id:
            if repo_id not in repo_chunks:
                repo_chunks[repo_id] = []
            repo_chunks[repo_id].append(chunk_id)

    repos = sorted(repo_chunks.keys())
    if len(repos) < 2:
        return []

    links: List[Dict[str, Any]] = []
    for i in range(len(repos)):
        for j in range(i + 1, len(repos)):
            repo_a = repos[i]
            repo_b = repos[j]
            # Bounded evidence: up to 5 chunk_ids from each of the two repos (max 10 total)
            evidence: List[str] = repo_chunks[repo_a][:5] + repo_chunks[repo_b][:5]
            links.append({
                "source_repo": repo_a,
                "target_repo": repo_b,
                "link_type": "co_occurrence",
                "confidence": "inferred",
                "evidence_refs": evidence,
            })

    return links


def _find_bundle_index(bundle_path: Path) -> Optional[Path]:
    """
    Deterministically resolves the SQLite index for a given bundle path.
    1. If the path is a direct file ending in .index.sqlite, return it.
    2. If a directory, prioritize exactly one *.chunk_index.index.sqlite.
    3. If none found, look for exactly one generic *.index.sqlite.
    4. If ambiguous (multiple matches at the same level), return None safely.
    """
    if bundle_path.is_file() and bundle_path.name.endswith(".index.sqlite"):
        return bundle_path

    if not bundle_path.is_dir():
        return None

    # Search for canonical chunk index
    chunk_indices = list(bundle_path.glob("*.chunk_index.index.sqlite"))
    if len(chunk_indices) == 1:
        # Also ensure there isn't another generic index lying around competing for canonical truth
        generic_indices = list(bundle_path.glob("*.index.sqlite"))
        # We expect exactly 1 generic index too (the same one we just found). If there are more, it's ambiguous.
        if len(generic_indices) > 1:
            return None
        return chunk_indices[0]
    elif len(chunk_indices) > 1:
        return None

    # Search for generic index as fallback
    generic_indices = list(bundle_path.glob("*.index.sqlite"))
    if len(generic_indices) == 1:
        return generic_indices[0]
    elif len(generic_indices) > 1:
        return None

    return None

def execute_federated_query(
    federation_index_path: Path,
    query_text: str,
    k: int = 10,
    filters: Optional[Dict[str, Optional[str]]] = None,
    embedding_policy: Optional[Dict[str, Any]] = None,
    explain: bool = False,
    trace: bool = False,
    build_context: bool = False
) -> Dict[str, Any]:
    """
    Executes a minimal federated query aggregation across local bundles referenced by a federation index.
    This is not a full federated ranking system, but a fan-out mechanism that collects results and sorts them globally.
    """
    if not federation_index_path.exists():
        raise FileNotFoundError(f"Federation index not found at: {federation_index_path.resolve().as_posix()}")

    # Diagnose-Gate: Validate structural integrity before accessing keys to avoid KeyErrors mid-flight.
    # This is a deliberate safety check for the minimal fan-out, not intended as a highly optimized performance model.
    validate_federation(federation_index_path)

    with federation_index_path.open("r", encoding="utf-8") as f:
        fed_data = json.load(f)

    bundles = fed_data.get("bundles", [])

    all_results = []
    bundle_traces = {}
    bundle_status = {}
    bundle_errors = {}
    bundle_latency_ms = {}

    queried_bundles_total = len(bundles)
    queried_bundles_effective = 0

    # repo-Filter wird auf Federation-Ebene angewendet und nicht an execute_query
    # weitergereicht, um doppelte Ausführung und Fehler zu vermeiden, falls lokale Repos
    # andere IDs verwenden. Andere Filter werden normal durchgereicht.
    local_filters = None
    if filters:
        local_filters = {k: v for k, v in filters.items() if k != "repo"}

    for b in bundles:
        repo_id = b["repo_id"]
        bundle_path_str = b["bundle_path"]
        # Per-bundle processing latency, including validation and early exits;
        # not a pure DB query benchmark.
        bundle_start = time.perf_counter()

        try:
            if filters and filters.get("repo") and filters["repo"] != repo_id:
                bundle_status[repo_id] = "filtered_out"
                continue

            if "://" in bundle_path_str:
                bundle_status[repo_id] = "bundle_path_unsupported"
                continue

            bundle_path = Path(bundle_path_str)
            if not bundle_path.is_absolute():
                bundle_path = federation_index_path.parent / bundle_path

            db_path = _find_bundle_index(bundle_path)
            if not db_path:
                bundle_status[repo_id] = "index_missing"
                continue

            import sqlite3
            # Check for staleness using fingerprint (last_fingerprint from federation index vs DB)
            # Note: staleness detection is strictly best-effort and must never fail the federated query.
            expected_fingerprint = b.get("last_fingerprint")
            db_fingerprint = None
            if expected_fingerprint:
                try:
                    with sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True) as conn:
                        cursor = conn.execute("SELECT value FROM index_meta WHERE key='canonical_dump_index_sha256'")
                        row = cursor.fetchone()
                        if row:
                            db_fingerprint = row[0]
                except sqlite3.Error:
                    # Broad catch to ensure handle leaks or generic db errors don't crash the fan-out
                    pass

                if db_fingerprint and db_fingerprint != expected_fingerprint:
                    bundle_status[repo_id] = "stale"
                    # We can still execute the query, but we mark it as stale in the trace

            res = execute_query(
                index_path=db_path,
                query_text=query_text,
                k=k,  # Fetch up to k from each bundle to ensure global top-k is accurate
                filters=local_filters,
                embedding_policy=embedding_policy,
                explain=explain,
                trace=trace,
                build_context=build_context
            )

            # Score normalisation and integration per bundle
            # Note: `execute_query` already calculates a semantically stable `final_score`
            # (which is between 0 and 1.0, combining bm25_norm and potential graph/semantic boosts).
            # BM25 raw scores are negative in SQLite, but `final_score` is properly inverted and normalized.
            # We rely on this `final_score` for global federated ranking to preserve absolute magnitude
            # (a weak match in Repo A shouldn't beat a strong match in Repo B just because it was the best locally).
            bundle_hits = res.get("results", [])
            if bundle_hits:
                for hit in bundle_hits:
                    # Require provenance: either range_ref or derived_range_ref must be present and truthy
                    if not hit.get("range_ref") and not hit.get("derived_range_ref"):
                        continue

                    # Tag results with bundle origin (Provenance)
                    hit["federation_bundle"] = repo_id
                    all_results.append(hit)

            if repo_id not in bundle_status:
                bundle_status[repo_id] = "ok"
            queried_bundles_effective += 1
            if trace and "query_trace" in res:
                bundle_traces[repo_id] = res["query_trace"]

        except Exception as e:
            bundle_status[repo_id] = "query_error"
            bundle_errors[repo_id] = str(e)
        finally:
            bundle_latency_ms[repo_id] = (time.perf_counter() - bundle_start) * 1000.0

    # Conflict Detection Heuristic (Minimal)
    # Group results by filename (`Path.name`) as a primitive heuristic.
    # Note: This is an initial path-based collision heuristic, not a full symbol or identity resolution engine.
    # If the same filename appears in multiple distinct paths or repos, it is surfaced as a 'path' conflict.
    # True 'identity' resolution would require a dedicated symbol index layer.
    conflicts = []
    symbol_map = {}
    for hit in all_results:
        p = hit.get("path", "")
        if p:
            sym = Path(p).name
            if sym not in symbol_map:
                symbol_map[sym] = []
            symbol_map[sym].append(hit)

    conflict_idx = 1
    for sym, hits in symbol_map.items():
        if len(hits) > 1:
            # Check if they are actually from different paths or repos
            unique_origins = set((h.get("federation_bundle", ""), h.get("path", "")) for h in hits)
            if len(unique_origins) > 1:
                conflict_id = f"conflict_{conflict_idx}"
                conflict_idx += 1
                involved = [h.get("chunk_id", "") for h in hits]

                conflicts.append({
                    "conflict_id": conflict_id,
                    "type": "path",
                    "description": f"Multiple hits found with the same filename '{sym}' across different paths or repos.",
                    "resolution": "unresolved",
                    "involved_results": involved
                })

                # Tag hits with conflict without altering or dropping results
                for h in hits:
                    if "conflict_refs" not in h:
                        h["conflict_refs"] = []
                    h["conflict_refs"].append(conflict_id)

    # Global sort: final_score descending
    # Tie-breakers: federation_bundle asc, path asc, chunk_id asc to ensure deterministic tie ordering
    all_results.sort(key=lambda x: (
        -x.get("final_score", 0),
        x.get("federation_bundle", ""),
        x.get("path", ""),
        x.get("chunk_id", "")
    ))

    # Cross-Repo Context (mark secondary context)
    # If multiple bundles yield hits, the first bundle's hits (based on score) are primary
    # hits from other bundles are marked as secondary context.
    if all_results:
        primary_bundle = all_results[0].get("federation_bundle", "")
        for hit in all_results:
            if hit.get("federation_bundle", "") == primary_bundle:
                hit["cross_repo_context_role"] = "primary_evidence"
            else:
                hit["cross_repo_context_role"] = "secondary_context"

    total_candidates_found = len(all_results)
    top_k = all_results[:k]

    out = {
        "query": query_text,
        "k": k,
        "count": len(top_k),  # Refers to the returned top-k results after global slice
        "total_candidates_found": total_candidates_found, # Total hits across all bundles before slicing
        "results": top_k,
        "federation_id": fed_data.get("federation_id", "<unknown>")
    }


    # Minimal projection: This currently produces only a bare-bones context_bundle
    # structure (`query` and `hits`) as a transport layer. This is not a fully resolved
    # semantic bundle and does not include extended context blocks.
    if build_context:
        out["context_bundle"] = {
            "query": query_text,
            "hits": top_k
        }
        del out["results"]

    if conflicts:
        out["federation_conflicts"] = conflicts

    cross_repo_links = _build_cross_repo_links(top_k)
    if cross_repo_links:
        out["cross_repo_links"] = cross_repo_links

    if trace:
        out["federation_trace"] = {
            "queried_bundles_total": queried_bundles_total,
            "queried_bundles_effective": queried_bundles_effective,
            "bundle_status": bundle_status,
            "bundle_errors": bundle_errors,
            "bundle_traces": bundle_traces,
            "bundle_latency_ms": bundle_latency_ms,
        }

    return out
