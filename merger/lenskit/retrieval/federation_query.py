import datetime
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .query_core import execute_query
from ..core.federation import FEDERATION_KIND, FEDERATION_VERSION
from ..core.federation import load_federation_index_data
from ..core.federation import validate_federation_data
from ..core.path_security import resolve_secure_path

logger = logging.getLogger(__name__)


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
    # The caller resolves and confines this path before discovery.
    if bundle_path.is_file() and bundle_path.name.endswith(".index.sqlite"):  # lgtm[py/path-injection]
        return bundle_path

    if not bundle_path.is_dir():  # lgtm[py/path-injection]
        return None

    # Search for canonical chunk index
    chunk_indices = list(bundle_path.glob("*.chunk_index.index.sqlite"))  # lgtm[py/path-injection]
    if len(chunk_indices) == 1:
        # Also ensure there isn't another generic index lying around competing for canonical truth
        generic_indices = list(bundle_path.glob("*.index.sqlite"))  # lgtm[py/path-injection]
        # We expect exactly 1 generic index too (the same one we just found). If there are more, it's ambiguous.
        if len(generic_indices) > 1:
            return None
        return chunk_indices[0]
    elif len(chunk_indices) > 1:
        return None

    # Search for generic index as fallback
    generic_indices = list(bundle_path.glob("*.index.sqlite"))  # lgtm[py/path-injection]
    if len(generic_indices) == 1:
        return generic_indices[0]
    elif len(generic_indices) > 1:
        return None

    return None

def _resolve_existing_local_path(raw_path: str, base_path: Path) -> Path:
    """Resolve an explicit local-operator path without creating or refreshing anything."""
    if "://" in raw_path or "\x00" in raw_path:
        raise ValueError("inline --bundle paths must be local filesystem paths")
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = base_path / candidate
    resolved = candidate.resolve(strict=True)  # lgtm[py/path-injection]
    if not resolved.is_dir() and not (
        resolved.is_file() and resolved.name.endswith(".index.sqlite")
    ):
        raise ValueError(
            "inline --bundle path must be an existing bundle directory or .index.sqlite file"
        )
    return resolved


def _resolve_persisted_bundle_path(
    raw_path: str,
    base_path: Path,
    *,
    allow_external: bool,
) -> Path:
    """Resolve one persisted bundle path under the API boundary or explicit CLI authority."""
    if "://" in raw_path or "\x00" in raw_path:
        raise ValueError("bundle path must be a local filesystem path")
    if allow_external:
        return _resolve_existing_local_path(raw_path, base_path)

    candidate = Path(raw_path)
    if candidate.is_absolute():
        base_resolved = base_path.resolve(strict=True)
        resolved = candidate.resolve(strict=True)  # lgtm[py/path-injection]
        try:
            resolved.relative_to(base_resolved)
        except ValueError as exc:
            raise ValueError("bundle path escapes the federation directory") from exc
        return resolved
    return resolve_secure_path(base_path, raw_path)



def _build_transient_federation_index(
    bundle_specs: List[Dict[str, str]],
    federation_id: str = "inline-bundle-set",
    base_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Builds a schema-valid, read-only federation index object from bundle specs."""
    resolved_base = (base_path or Path.cwd()).resolve(strict=True)
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    bundles: List[Dict[str, str]] = []
    for spec in bundle_specs:
        item = {
            "repo_id": spec["repo_id"],
            "bundle_path": _resolve_existing_local_path(spec["bundle_path"], resolved_base).as_posix(),
        }
        if spec.get("last_fingerprint"):
            item["last_fingerprint"] = spec["last_fingerprint"]
        bundles.append(item)
    bundles.sort(key=lambda x: x["repo_id"])
    fed_data = {
        "kind": FEDERATION_KIND,
        "version": FEDERATION_VERSION,
        "federation_id": federation_id,
        "created_at": now,
        "updated_at": now,
        "bundles": bundles,
    }
    validate_federation_data(fed_data)
    return fed_data


def _freshness_status(expected_fingerprint: Optional[str], observed_fingerprint: Optional[str], bundle_status: str) -> str:
    if bundle_status == "stale":
        return "stale"
    if not expected_fingerprint:
        return "unverified"
    if observed_fingerprint is None:
        return "unverified"
    if observed_fingerprint == expected_fingerprint:
        return "current"
    return "stale"


def _execute_federated_query_data(
    fed_data: Dict[str, Any],
    federation_base_path: Path,
    query_text: str,
    k: int = 10,
    filters: Optional[Dict[str, Optional[str]]] = None,
    embedding_policy: Optional[Dict[str, Any]] = None,
    explain: bool = False,
    trace: bool = False,
    build_context: bool = False,
    allow_external_bundle_paths: bool = True,
) -> Dict[str, Any]:
    """Executes federated query aggregation over a validated federation object."""
    validate_federation_data(fed_data)

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

            try:
                bundle_path = _resolve_persisted_bundle_path(
                    bundle_path_str,
                    federation_base_path,
                    allow_external=allow_external_bundle_paths,
                )
            except (ValueError, OSError, RuntimeError):
                bundle_status[repo_id] = "bundle_path_rejected"
                continue

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
                    db_uri = f"{db_path.resolve().as_uri()}?mode=ro&immutable=1"
                    with sqlite3.connect(db_uri, uri=True) as conn:  # lgtm[py/path-injection]
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
                build_context=build_context,
                read_only=True,
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

                    # Tag results with bundle origin, availability and freshness provenance.
                    status = bundle_status.get(repo_id, "ok")
                    freshness = _freshness_status(expected_fingerprint, db_fingerprint, status)
                    hit["federation_bundle"] = repo_id
                    hit["federation_bundle_status"] = status
                    hit["federation_freshness_status"] = freshness
                    hit["federation_origin"] = {
                        "repo_id": repo_id,
                        "bundle_path": bundle_path_str,
                        "availability_status": status,
                        "freshness_status": freshness,
                        "expected_fingerprint": expected_fingerprint,
                        "observed_fingerprint": db_fingerprint,
                    }
                    all_results.append(hit)

            if repo_id not in bundle_status:
                bundle_status[repo_id] = "ok"
            queried_bundles_effective += 1
            if trace and "query_trace" in res:
                bundle_traces[repo_id] = res["query_trace"]

        except Exception as exc:
            logger.warning(
                "Federated bundle query failed for %s: %s",
                repo_id,
                type(exc).__name__,
                exc_info=True,
            )
            bundle_status[repo_id] = "query_error"
            bundle_errors[repo_id] = "bundle query failed"
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

def execute_federated_query(
    federation_index_path: Path,
    query_text: str,
    k: int = 10,
    filters: Optional[Dict[str, Optional[str]]] = None,
    embedding_policy: Optional[Dict[str, Any]] = None,
    explain: bool = False,
    trace: bool = False,
    build_context: bool = False,
    *,
    allow_external_bundle_paths: bool = True,
) -> Dict[str, Any]:
    """
    Executes a minimal federated query aggregation across local bundles referenced by a federation index.

    The federation index is a read-only registry input. This function does not create snapshots,
    refresh bundles, mutate Git, run shells or assert global repository truth.
    """
    resolved_federation_index = federation_index_path.resolve(strict=True)  # lgtm[py/path-injection]
    fed_data = load_federation_index_data(resolved_federation_index)

    return _execute_federated_query_data(
        fed_data=fed_data,
        federation_base_path=resolved_federation_index.parent,
        query_text=query_text,
        k=k,
        filters=filters,
        embedding_policy=embedding_policy,
        explain=explain,
        trace=trace,
        build_context=build_context,
        allow_external_bundle_paths=allow_external_bundle_paths,
    )


def execute_federated_query_from_bundles(
    bundle_specs: List[Dict[str, str]],
    query_text: str,
    k: int = 10,
    filters: Optional[Dict[str, Optional[str]]] = None,
    embedding_policy: Optional[Dict[str, Any]] = None,
    explain: bool = False,
    trace: bool = False,
    build_context: bool = False,
    federation_id: str = "inline-bundle-set",
    base_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Executes the same read-only federation query over an explicit list of bundle roots.

    `bundle_specs` items require `repo_id` and `bundle_path`, and may include
    `last_fingerprint`. Relative bundle paths resolve against `base_path` (or CWD).
    No federation_index.json is written.
    """
    resolved_base = (base_path or Path.cwd()).resolve(strict=True)
    fed_data = _build_transient_federation_index(
        bundle_specs,
        federation_id=federation_id,
        base_path=resolved_base,
    )
    return _execute_federated_query_data(
        fed_data=fed_data,
        federation_base_path=resolved_base,
        query_text=query_text,
        k=k,
        filters=filters,
        embedding_policy=embedding_policy,
        explain=explain,
        trace=trace,
        build_context=build_context,
        allow_external_bundle_paths=True,
    )
