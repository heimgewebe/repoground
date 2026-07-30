"""Symbol-index load and search over registered bundle artifacts.

Extracted from bundle_access as a T011 residual slice so symbol search is
not entangled with range/query orchestration or call-graph navigation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from merger.repoground.core import artifact_source_access as _artifact_source_access
from merger.repoground.core.bounded_artifact_read import (
    LoadedArtifactSource as _LoadedArtifactSource,
)
from merger.repoground.core.bundle_roles import (
    DOES_NOT_ESTABLISH as _DOES_NOT_ESTABLISH,
    read_only_mutation_boundary as _read_only_mutation_boundary,
)
from merger.repoground.core.manifest_snapshot import resolve_manifest_path
from merger.repoground.core.response_projection import project_read_result

logger = logging.getLogger(__name__)

_read_registered_artifact_source = (
    _artifact_source_access._read_registered_artifact_source
)


def _bundle_access():
    from merger.repoground.core import bundle_access as _ba

    return _ba


def _availability_model_for_manifest(manifest_path: Path) -> dict[str, Any]:
    return _bundle_access()._availability_model_for_manifest(manifest_path)


def _invalid_read_result(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _bundle_access()._invalid_read_result(*args, **kwargs)

SYMBOL_INDEX_ROLE = "python_symbol_index_json"
SYMBOL_SEARCH_KIND = "repobrief.symbol_search"
MAX_SYMBOL_SEARCH_K = 200

_SYMBOL_SOURCE_ERRORS = {
    "missing": (
        "missing",
        "python_symbol_index_json_missing",
        "python_symbol_index_json artifact is not present in the bundle manifest",
    ),
    "file_missing": (
        "missing",
        "python_symbol_index_json_file_missing",
        "python_symbol_index_json artifact file does not exist",
    ),
    "role_ambiguous": (
        "invalid",
        "python_symbol_index_json_role_ambiguous",
        "bundle manifest contains multiple python_symbol_index_json artifacts",
    ),
    "path_invalid": (
        "invalid",
        "python_symbol_index_json_path_invalid",
        "python_symbol_index_json artifact path escapes the bundle root",
    ),
    "manifest_too_large": (
        "invalid",
        "bundle_manifest_too_large",
        "bundle manifest exceeds the bounded read limit",
    ),
    "manifest_invalid": (
        "invalid",
        "bundle_manifest_invalid",
        "bundle manifest identity, run_id, or artifacts are invalid",
    ),
    "integrity_unavailable": (
        "invalid",
        "python_symbol_index_json_integrity_unavailable",
        (
            "python_symbol_index_json requires valid bytes and sha256 metadata "
            "in the bundle manifest"
        ),
    ),
    "too_large": (
        "invalid",
        "python_symbol_index_json_too_large",
        "python_symbol_index_json exceeds the bounded read limit",
    ),
    "bytes_mismatch": (
        "invalid",
        "python_symbol_index_json_bytes_mismatch",
        "python_symbol_index_json byte count does not match the bundle manifest",
    ),
    "sha256_mismatch": (
        "invalid",
        "python_symbol_index_json_sha256_mismatch",
        "python_symbol_index_json content hash does not match the bundle manifest",
    ),
    "source_changed": (
        "invalid",
        "python_symbol_index_source_changed_during_load",
        (
            "python_symbol_index_json source changed while navigation state "
            "was loading"
        ),
    ),
    "unreadable": (
        "invalid",
        "python_symbol_index_json_unreadable",
        "python_symbol_index_json could not be read",
    ),
}


def _registered_source_error(
    failure: str | None,
    detail: str | None,
    errors: dict[str, tuple[str, str, str]],
) -> dict[str, Any] | None:
    if failure is None:
        return None
    status, error_code, error = errors.get(failure, errors["unreadable"])
    return {
        "status": status,
        "error_code": error_code,
        "error": detail or error,
    }


def _symbol_source_range(symbol: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": symbol.get("path"),
        "start_line": symbol.get("start_line"),
        "end_line": symbol.get("end_line"),
        "range_ref": symbol.get("range_ref"),
        "coordinate_basis": "source_lines",
    }


def _symbol_record(symbol: dict[str, Any]) -> dict[str, Any]:
    decorators = symbol.get("decorators")
    return {
        "id": symbol.get("id"),
        "kind": symbol.get("kind"),
        "name": symbol.get("name"),
        "qualified_name": symbol.get("qualified_name"),
        "module": symbol.get("module"),
        "path": symbol.get("path"),
        "start_line": symbol.get("start_line"),
        "end_line": symbol.get("end_line"),
        "range_ref": symbol.get("range_ref"),
        "source_range": _symbol_source_range(symbol),
        "decorators": list(decorators) if isinstance(decorators, list) else [],
    }


def _load_symbol_index_source(
    manifest_path: Path,
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
    _LoadedArtifactSource | None,
    dict[str, Any] | None,
]:
    source, artifact, failure, detail = _read_registered_artifact_source(
        manifest_path, SYMBOL_INDEX_ROLE
    )
    source_error = _registered_source_error(
        failure,
        detail,
        _SYMBOL_SOURCE_ERRORS,
    )
    if source_error is not None:
        return None, artifact, None, source_error
    assert source is not None
    try:
        data = json.loads(source.raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, artifact, None, {
            "status": "invalid",
            "error_code": "python_symbol_index_json_unreadable",
            "error": str(exc),
        }
    if not isinstance(data, dict) or data.get("kind") != "lenskit.python_symbol_index":
        return None, artifact, None, {
            "status": "invalid",
            "error_code": "python_symbol_index_json_invalid_kind",
            "error": "python_symbol_index_json must be a lenskit.python_symbol_index object",
        }
    symbols = data.get("symbols")
    if not isinstance(symbols, list):
        return None, artifact, None, {
            "status": "invalid",
            "error_code": "python_symbol_index_symbols_invalid",
            "error": "python_symbol_index_json symbols must be an array",
        }
    return data, artifact, source, None


def _load_symbol_index(
    manifest_path: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    data, artifact, _source, error = _load_symbol_index_source(manifest_path)
    return data, artifact, error


def search_symbol_index(
    bundle_manifest: str | Path,
    query: str = "",
    *,
    k: int = 25,
    kind: str | None = None,
    path: str | None = None,
    verbose: bool = True,
    compact: bool | None = None,
) -> dict[str, Any]:
    """Symbol lookup with the historical full contract by default.

    Pass ``compact=True`` (or ``verbose=False``) for the bounded agent projection.
    """
    if compact is not None:
        verbose = not compact
    manifest_path = resolve_manifest_path(bundle_manifest)
    return project_read_result(
        _search_symbol_index_full(manifest_path, query, k=k, kind=kind, path=path),
        manifest_path,
        verbose=verbose,
    )


def _search_symbol_index_full(
    manifest_path: Path,
    query: str = "",
    *,
    k: int = 25,
    kind: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    if not isinstance(query, str):
        return _invalid_read_result(
            kind=SYMBOL_SEARCH_KIND,
            bundle_manifest=manifest_path,
            status="invalid",
            error="query must be a string",
            error_code="query_invalid",
            extra={"query": query, "k": k, "symbol_index": None, "hits": []},
        )
    if not isinstance(k, int) or isinstance(k, bool) or k < 1 or k > MAX_SYMBOL_SEARCH_K:
        return _invalid_read_result(
            kind=SYMBOL_SEARCH_KIND,
            bundle_manifest=manifest_path,
            status="invalid",
            error=f"k must be an integer between 1 and {MAX_SYMBOL_SEARCH_K}",
            error_code="k_out_of_bounds",
            extra={"query": query, "k": k, "symbol_index": None, "hits": []},
        )
    data, artifact, error = _load_symbol_index(manifest_path)
    if error is not None:
        return _invalid_read_result(
            kind=SYMBOL_SEARCH_KIND,
            bundle_manifest=manifest_path,
            status=error["status"],
            error=error["error"],
            error_code=error["error_code"],
            extra={"query": query, "k": k, "symbol_index": artifact, "hits": []},
        )
    assert data is not None
    symbols = [item for item in data.get("symbols", []) if isinstance(item, dict)]
    q = query.strip().casefold()
    kind_filter = kind.strip() if isinstance(kind, str) and kind.strip() else None
    path_filter = path.strip().casefold() if isinstance(path, str) and path.strip() else None
    matched: list[tuple[int, int, dict[str, Any]]] = []
    omitted_by_filter = 0
    for position, symbol in enumerate(symbols):
        haystack = " ".join(
            str(symbol.get(field, ""))
            for field in ("name", "qualified_name", "module", "path", "kind")
        ).casefold()
        if q and q not in haystack:
            omitted_by_filter += 1
            continue
        if kind_filter and symbol.get("kind") != kind_filter:
            omitted_by_filter += 1
            continue
        if path_filter and path_filter not in str(symbol.get("path", "")).casefold():
            omitted_by_filter += 1
            continue
        # Rank exact name/qualified_name matches before substring matches so a
        # definition lookup surfaces the symbol itself first. Ties keep index
        # order (stable), preserving prior behavior when no exact match exists.
        exact = 0 if q and (
            str(symbol.get("name", "")).casefold() == q
            or str(symbol.get("qualified_name", "")).casefold() == q
        ) else 1
        matched.append((exact, position, symbol))
    matched.sort(key=lambda item: (item[0], item[1]))
    # Build the (heavier) records only for the k rows that are actually returned.
    hits = [_symbol_record(symbol) for _, _, symbol in matched[:k]]
    availability = _availability_model_for_manifest(manifest_path)
    return {
        "kind": SYMBOL_SEARCH_KIND,
        "version": "v1",
        "status": "available",
        "bundle_manifest": str(manifest_path),
        "query": query,
        "k": k,
        "filters": {"kind": kind, "path": path},
        "symbol_index": artifact,
        "symbol_index_metadata": {
            "language": data.get("language"),
            "symbol_kinds": data.get("symbol_kinds"),
            "skipped_files_count": data.get("skipped_files_count"),
            "skipped_errors": data.get("skipped_errors"),
            "canonical_dump_index_sha256": data.get("canonical_dump_index_sha256"),
        },
        "availability": availability,
        "freshness": availability.get("freshness") if isinstance(availability, dict) else None,
        "hit_count": len(hits),
        "omitted_by_filter_count": omitted_by_filter,
        "truncated": len(matched) > k,
        "hits": hits,
        "mutation_boundary": _read_only_mutation_boundary(),
        "does_not_establish": list(_DOES_NOT_ESTABLISH) + [
            "call_graph_completeness",
            "dependency_completeness",
            "import_success",
            "review_impact",
            "merge_readiness",
        ],
    }


