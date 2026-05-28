import json
import copy
import threading
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_STORE_FILENAME = "query_artifacts.json"

# Per-type classification metadata injected into every stored entry.
# authority/canonicality use the vocabulary from bundle-manifest.v1.schema.json.
# artifact_shape encodes the stored data form:
#   "raw"       — unmodified internal execute_query() output (query_trace)
#   "projected" — API-projected form after output-profile filtering (context_bundle)
#   "wrapper"   — session wrapper built from the projected context bundle (agent_query_session)
# retention_policy reflects the store's current behaviour (no GC; unbounded growth).
_RUNTIME_ARTIFACT_METADATA: Dict[str, Dict[str, Any]] = {
    "query_trace": {
        "authority": "runtime_observation",
        "canonicality": "observation",
        "artifact_shape": "raw",
        "retention_policy": "unbounded_currently",
        "lifecycle_status": "active",
        "expires_at": None,
        "claim_boundaries": {
            "does_not_prove": [
                "Artifact ID stability is limited to this store location.",
                "Runtime artifact does not prove live repository state.",
            ]
        },
    },
    "context_bundle": {
        "authority": "runtime_observation",
        "canonicality": "observation",
        "artifact_shape": "projected",
        "retention_policy": "unbounded_currently",
        "lifecycle_status": "active",
        "expires_at": None,
        "claim_boundaries": {
            "does_not_prove": [
                "Artifact ID stability is limited to this store location.",
                "Runtime artifact does not prove live repository state.",
                "Context bundle is stored in projected API form, not raw execute_query form.",
            ]
        },
    },
    "agent_query_session": {
        "authority": "runtime_observation",
        "canonicality": "observation",
        "artifact_shape": "wrapper",
        "retention_policy": "unbounded_currently",
        "lifecycle_status": "active",
        "expires_at": None,
        "claim_boundaries": {
            "does_not_prove": [
                "Artifact ID stability is limited to this store location.",
                "Runtime artifact does not prove live repository state.",
            ]
        },
    },
}

# Derived from _RUNTIME_ARTIFACT_METADATA so it can never drift out of sync.
VALID_ARTIFACT_TYPES = frozenset(_RUNTIME_ARTIFACT_METADATA.keys())


def _with_runtime_metadata(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Return entry with runtime classification fields guaranteed.

    New entries written by store() already contain all fields.  Legacy entries
    loaded from disk may predate this PR and lack authority/canonicality/
    artifact_shape/retention_policy/lifecycle_status/expires_at/claim_boundaries.
    This helper backfills those fields from _RUNTIME_ARTIFACT_METADATA without
    mutating the cached dict and without overwriting any field that was already
    present.

    Unknown artifact_types (shouldn't happen, but safe to handle) are returned
    as a deep copy.  Callers receive an independent copy of all nested
    structures; mutations to the returned dict do not reach the cache.
    """
    artifact_type = entry.get("artifact_type")
    meta = _RUNTIME_ARTIFACT_METADATA.get(artifact_type)
    merged = copy.deepcopy(entry)
    if not meta:
        return merged
    for key, value in meta.items():
        if key not in merged:
            merged[key] = copy.deepcopy(value)
    return merged


def _parse_created_at_for_diagnostics(value: Any) -> Optional[datetime]:
    """Parse created_at for diagnostics min/max comparison.

    Accepts only non-empty strings in ISO-8601 format with an explicit offset.
    A trailing ``Z`` is normalized to ``+00:00`` for parsing only. Naive
    datetimes (without tzinfo) and malformed values are rejected.
    """
    if not isinstance(value, str) or not value:
        return None

    candidate = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return None
    return parsed


class QueryArtifactStore:
    """Persistent store for query runtime artifacts.

    Artifacts (query_trace, context_bundle, agent_query_session) are produced
    ephemerally during execute_query(). This store assigns IDs and persists
    them so they can be retrieved via artifact_lookup without re-executing any
    query.

    ID stability: IDs are stable within this store instance for the lifetime
    of the underlying JSON file.  They are not guaranteed to be resolvable
    after the store location changes (e.g. different merges_dir).

    Known limitations (open, not in scope for this PR):
    - No retention/GC policy: the store grows unbounded.
    - No federation artifact support.
    - No raw-vs-projected artifact distinction (context_bundle is stored in
      the projected API form, not the internal execute_query() form).

    Storage format: JSON list at {storage_dir}/query_artifacts.json.
    All writes use tmp-file replacement.
    """

    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._store_file = self.storage_dir / _STORE_FILENAME
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self._store_file.exists():
                return
            try:
                data = json.loads(self._store_file.read_text(encoding="utf-8"))
                for entry in data:
                    self._cache[entry["id"]] = entry
            except Exception as e:
                logger.error("Failed to load query artifacts from %s: %s", self._store_file, e)

    def _save(self) -> None:
        tmp = self._store_file.with_suffix(".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps(list(self._cache.values()), indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._store_file)

    def store(
        self,
        artifact_type: str,
        data: Dict[str, Any],
        provenance: Dict[str, Any],
        run_id: Optional[str] = None,
    ) -> str:
        """Store a query artifact and return its stable artifact_id.

        Args:
            artifact_type: One of "query_trace", "context_bundle", "agent_query_session".
            data: The artifact payload (must be JSON-serialisable).
            provenance: Dict with at minimum "source_query" and "timestamp".
            run_id: Optional correlation ID linking artifacts from the same execution.

        Returns:
            A stable artifact_id string (e.g. "qart-<hex>").
        """
        if artifact_type not in VALID_ARTIFACT_TYPES:
            raise ValueError(
                f"Invalid artifact_type {artifact_type!r}. "
                f"Must be one of: {sorted(VALID_ARTIFACT_TYPES)}"
            )

        artifact_id = f"qart-{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()

        prov = dict(provenance)
        if run_id is not None:
            prov.setdefault("run_id", run_id)
        prov.setdefault("run_id", None)

        runtime_meta = copy.deepcopy(_RUNTIME_ARTIFACT_METADATA[artifact_type])
        entry: Dict[str, Any] = {
            "id": artifact_id,
            "artifact_type": artifact_type,
            "data": data,
            "provenance": prov,
            "created_at": now,
            **runtime_meta,
        }

        with self._lock:
            self._cache[artifact_id] = entry
            self._save()

        return artifact_id

    def get(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        """Return the stored entry for artifact_id, or None if not found.

        Always returns a dict with runtime classification fields present,
        backfilling from _RUNTIME_ARTIFACT_METADATA for legacy entries that
        predate the metadata schema addition.
        """
        with self._lock:
            raw = self._cache.get(artifact_id)
            if raw is None:
                return None
            return _with_runtime_metadata(raw)

    def get_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return sorted(
                (_with_runtime_metadata(e) for e in self._cache.values()),
                key=lambda e: e.get("created_at", ""),
                reverse=True,
            )

    def diagnostics(self) -> Dict[str, Any]:
        """Return a read-only retention diagnostics snapshot of the store.

        The store currently has no GC and no TTL: it grows unbounded for the
        lifetime of the underlying JSON file.  This method surfaces what *is*
        there (counts, age range, on-disk size) so operators can observe
        growth without enabling any deletion path.

        Read-only contract:
        - Does not mutate the in-memory cache.
        - Does not write to or truncate the on-disk store file.
        - Does not enable any retention/GC/TTL behaviour.
        - Does not enumerate artifact IDs or payloads.

        Legacy entries written before the runtime-metadata schema (which may
        lack lifecycle fields like ``lifecycle_status`` / ``expires_at``) are
        counted from the cache directly; no backfill is persisted.

        Returns:
            Dict with keys:
                ``total_artifacts``         — int, number of entries cached
                ``by_artifact_type``        — dict[str, int], counts per type
                ``oldest_created_at``       — str | None, original ``created_at``
                                              string of the chronologically
                                              oldest valid offset-aware ISO-8601
                                              timestamp; malformed, empty,
                                              non-string, or naive timestamps
                                              are ignored for min/max
                ``newest_created_at``       — str | None, original ``created_at``
                                              string of the chronologically
                                              newest valid offset-aware ISO-8601
                                              timestamp; malformed, empty,
                                              non-string, or naive timestamps
                                              are ignored for min/max; values
                                              are not normalized or rewritten
                ``store_file_size_bytes``   — int, on-disk size of the JSON
                                              file (0 if not yet written)
                ``retention_policy``        — const ``"unbounded_currently"``
                ``gc_enabled``              — const ``False``
                ``ttl_enabled``             — const ``False``
        """
        with self._lock:
            total = len(self._cache)
            by_type: Dict[str, int] = {}
            oldest: Optional[str] = None
            newest: Optional[str] = None
            oldest_dt: Optional[datetime] = None
            newest_dt: Optional[datetime] = None
            for entry in self._cache.values():
                # Robustly handle artifact_type: treat missing, empty, or non-string
                # values as "unknown" for counting purposes.
                artifact_type = entry.get("artifact_type")
                if not isinstance(artifact_type, str) or not artifact_type:
                    artifact_type = "unknown"
                by_type[artifact_type] = by_type.get(artifact_type, 0) + 1

                # For oldest/newest diagnostics, created_at values are validated and parsed
                # only for comparison. Legacy/malformed values are skipped for age range,
                # are not normalized in the returned payload, and are never rewritten.
                created = entry.get("created_at")
                created_dt = _parse_created_at_for_diagnostics(created)
                if created_dt is not None:
                    created_str = created
                    if oldest_dt is None or created_dt < oldest_dt:
                        oldest_dt = created_dt
                        oldest = created_str
                    if newest_dt is None or created_dt > newest_dt:
                        newest_dt = created_dt
                        newest = created_str
            try:
                store_file_size = (
                    self._store_file.stat().st_size if self._store_file.exists() else 0
                )
            except OSError:
                store_file_size = 0

        return {
            "total_artifacts": total,
            "by_artifact_type": by_type,
            "oldest_created_at": oldest,
            "newest_created_at": newest,
            "store_file_size_bytes": store_file_size,
            "retention_policy": "unbounded_currently",
            "gc_enabled": False,
            "ttl_enabled": False,
        }
