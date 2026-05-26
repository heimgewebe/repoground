"""
Retrieval Evaluation Diagnostics Calibrator

Classifies retrieval evaluation misses into diagnostic categories without modifying
existing metrics or ranking behavior. Provides per-miss root-cause analysis by checking:

1. Does the expected target exist in the index?
2. Does it exist in canonical_md?
3. Is it reachable via citation_map?
4. Is it ranked outside top-k (ranking problem)?
5. Is the expected target stale or ambiguous?

This module is diagnostic only - it does not propose fixes, rerank results, or modify
the gold set. It answers "why" a miss occurred, enabling targeted remediation decisions.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
import re


class RetrievalEvalDiagnosticsError(Exception):
    """Base exception for diagnostics module."""
    pass


class MissingArtifactError(RetrievalEvalDiagnosticsError):
    """Raised when required diagnostic artifacts are unavailable."""
    pass


class DiagnosticsRecord:
    """Single diagnostic record for a query miss."""

    PRIMARY_DIAGNOSES = {
        "target_in_top_k",
        "target_exists_not_in_top_k",
        "target_missing_from_index",
        "target_missing_from_canonical",
        "target_missing_from_citation_map",
        "stale_expected_target",
        "query_target_ambiguous",
        "diagnostic_inconclusive",
    }

    SECONDARY_DIAGNOSES = {
        "low_query_specificity",
        "partial_match_outside_top_k",
        "index_stale",
        "citation_gap",
        "ambiguous_target_definition",
    }

    def __init__(
        self,
        query_id: str,
        query_text: str,
        expected_target: str,
        primary_diagnosis: str,
        diagnosis_details: Dict[str, Any],
    ):
        """Initialize a diagnostics record."""
        if primary_diagnosis not in self.PRIMARY_DIAGNOSES:
            raise ValueError(
                f"Invalid primary_diagnosis '{primary_diagnosis}'. "
                f"Must be one of {sorted(self.PRIMARY_DIAGNOSES)}"
            )

        self.query_id = query_id
        self.query_text = query_text
        self.expected_target = expected_target
        self.primary_diagnosis = primary_diagnosis
        self.diagnosis_details = diagnosis_details

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to dictionary (for JSON serialization)."""
        return {
            "query_id": self.query_id,
            "query_text": self.query_text,
            "expected_target": self.expected_target,
            "primary_diagnosis": self.primary_diagnosis,
            "diagnosis_details": self.diagnosis_details,
        }


class IndexInspector:
    """Inspects index and canonical artifacts to support diagnostics."""

    def __init__(self, index_path: Optional[Path] = None):
        """
        Initialize inspector.

        Args:
            index_path: Path to chunk index (e.g., chunks.jsonl or index.sqlite).
        """
        self.index_path = index_path
        self._index_paths_cache: Optional[set] = None
        self._path_to_chunk_ids_cache: Optional[Dict[str, set]] = None
        self._canonical_md_content: Optional[str] = None
        self._citation_map_cache: Optional[Dict[str, Any]] = None

    def load_index_paths(self, force_reload: bool = False) -> set:
        """
        Load all unique paths from the index (chunk_index).

        Args:
            force_reload: Force reload from disk.

        Returns:
            Set of all unique paths in the index.
        """
        if self._index_paths_cache is not None and not force_reload:
            return self._index_paths_cache

        if self.index_path is None:
            return set()

        if self.index_path.suffix != ".jsonl":
            raise MissingArtifactError(f"Unsupported chunk index format: {self.index_path}")

        paths = set()
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        if "path" in chunk:
                            paths.add(chunk["path"])
                    except (json.JSONDecodeError, KeyError):
                        continue
        except (IOError, OSError) as e:
            raise MissingArtifactError(
                f"Failed to read chunk index from {self.index_path}: {e}"
            )
        # For SQLite index, would need similar logic
        # For now, assume JSONL format

        self._index_paths_cache = paths
        return paths

    def load_path_to_chunk_ids(self, force_reload: bool = False) -> Dict[str, set]:
        """
        Load mapping of path -> set(chunk_id) from chunk index JSONL.

        This is required to bridge path-based expectations to citation_map entries,
        which are keyed by citation_id and reference chunk_id.
        """
        if self._path_to_chunk_ids_cache is not None and not force_reload:
            return self._path_to_chunk_ids_cache

        mapping: Dict[str, set] = {}
        if self.index_path is None:
            self._path_to_chunk_ids_cache = mapping
            return mapping

        if self.index_path.suffix != ".jsonl":
            raise MissingArtifactError(f"Unsupported chunk index format: {self.index_path}")

        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    path = chunk.get("path")
                    chunk_id = chunk.get("chunk_id")
                    if isinstance(path, str) and isinstance(chunk_id, str):
                        mapping.setdefault(path, set()).add(chunk_id)
        except (IOError, OSError) as e:
            raise MissingArtifactError(
                f"Failed to read chunk index from {self.index_path}: {e}"
            )

        self._path_to_chunk_ids_cache = mapping
        return mapping

    @staticmethod
    def find_matching_paths(expected_target: str, index_paths: set) -> List[str]:
        """Return index paths that contain the expected target as substring."""
        if not isinstance(expected_target, str) or not expected_target:
            return []
        return sorted([p for p in index_paths if expected_target in p or p in expected_target])

    def load_canonical_md(self, canonical_path: Path) -> str:
        """
        Load canonical markdown content.

        Args:
            canonical_path: Path to canonical_md artifact.

        Returns:
            Full content of canonical_md.
        """
        if self._canonical_md_content is not None:
            return self._canonical_md_content

        if not canonical_path.exists():
            raise MissingArtifactError(f"canonical_md not found: {canonical_path}")

        try:
            with open(canonical_path, "r", encoding="utf-8") as f:
                self._canonical_md_content = f.read()
        except (IOError, OSError) as e:
            raise MissingArtifactError(
                f"Failed to read canonical_md from {canonical_path}: {e}"
            )

        return self._canonical_md_content

    def check_target_in_canonical(self, target: str, canonical_md: str) -> Tuple[bool, str, List[str]]:
        """
        Check if target exists in canonical_md.

        Args:
            target: Expected target path/identifier.
            canonical_md: Content of canonical_md artifact.

        Returns:
            (exists, check_status, similar_paths)
            - exists: Whether exact match found
            - check_status: 'exact_match' | 'variant_found' | 'not_found'
            - similar_paths: List of paths that might be related
        """
        # Exact match search
        if f"`{target}`" in canonical_md or f"/{target}" in canonical_md:
            return True, "exact_match", []

        # Look for variants (path separators, file extensions)
        similar = []
        # Extract all code blocks and paths from markdown
        code_blocks = re.findall(r"`([^`]+)`", canonical_md)
        for block in code_blocks:
            if target in block or block in target:
                similar.append(block)

        if similar:
            return False, "variant_found", similar[:5]

        return False, "not_found", []

    def load_citation_map(self, citation_path: Path) -> Dict[str, Any]:
        """
        Load citation_map_jsonl for cross-referencing.

        Args:
            citation_path: Path to citation_map_jsonl.

        Returns:
            Dict mapping citation IDs to citation records.
        """
        if self._citation_map_cache is not None:
            return self._citation_map_cache

        if not citation_path.exists():
            raise MissingArtifactError(f"citation_map_jsonl not found: {citation_path}")

        citation_map = {}
        try:
            with open(citation_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        # Assume citation_id is the key
                        if "citation_id" in record:
                            citation_map[record["citation_id"]] = record
                    except json.JSONDecodeError:
                        continue
        except (IOError, OSError) as e:
            raise MissingArtifactError(
                f"Failed to read citation_map from {citation_path}: {e}"
            )

        self._citation_map_cache = citation_map
        return citation_map


class RetrievalEvalDiagnosticsCalibrator:
    """
    Diagnostic calibrator for retrieval evaluation misses.

    Classifies why each miss occurred without modifying ranking, metrics, or gold set.
    """

    def __init__(
        self,
        index_path: Optional[Path] = None,
        canonical_path: Optional[Path] = None,
        citation_path: Optional[Path] = None,
    ):
        """
        Initialize the calibrator.

        Args:
            index_path: Path to chunk_index.jsonl
            canonical_path: Path to canonical_md artifact
            citation_path: Path to citation_map_jsonl
        """
        self.index_path = index_path
        self.canonical_path = canonical_path
        self.citation_path = citation_path
        self.inspector = IndexInspector(index_path)

        # Load artifacts once
        self._index_paths: Optional[set] = None
        self._path_to_chunk_ids: Optional[Dict[str, set]] = None
        self._index_unavailable: bool = False
        self._canonical_md: Optional[str] = None
        self._citation_map: Optional[Dict[str, Any]] = None
        self._citation_chunk_ids: Optional[set] = None

    def _load_artifacts(self) -> None:
        """Load and cache required artifacts."""
        if self.index_path:
            try:
                self._index_paths = self.inspector.load_index_paths()
                self._path_to_chunk_ids = self.inspector.load_path_to_chunk_ids()
                self._index_unavailable = False
            except MissingArtifactError:
                self._index_paths = None
                self._path_to_chunk_ids = None
                self._index_unavailable = True

        if self.canonical_path:
            try:
                self._canonical_md = self.inspector.load_canonical_md(self.canonical_path)
            except MissingArtifactError:
                self._canonical_md = None

        if self.citation_path:
            try:
                self._citation_map = self.inspector.load_citation_map(self.citation_path)
                self._citation_chunk_ids = {
                    rec.get("chunk_id")
                    for rec in self._citation_map.values()
                    if isinstance(rec, dict) and isinstance(rec.get("chunk_id"), str)
                }
            except MissingArtifactError:
                self._citation_map = None
                self._citation_chunk_ids = None

    def diagnose_miss(
        self,
        query_id: str,
        query_text: str,
        expected_target: str,
        found_in_results: bool,
        rank_in_results: Optional[int] = None,
        top_k: Optional[int] = None,
        query_had_zero_hits: bool = False,
    ) -> DiagnosticsRecord:
        """
        Diagnose why a query miss occurred.

        Args:
            query_id: Unique query identifier.
            query_text: The query string as executed.
            expected_target: Expected target path/identifier from gold set.
            found_in_results: Was the target found in results?
            rank_in_results: Rank position in results (1-indexed), or None.
            top_k: The k value used for top-k evaluation.
            query_had_zero_hits: Did the query return 0 total results?

        Returns:
            DiagnosticsRecord with primary diagnosis and details.
        """
        # Load artifacts if not already loaded
        if self._index_paths is None:
            self._load_artifacts()

        details: Dict[str, Any] = {
            "target_found_in_index": False,
            "target_found_in_canonical": False,
            "target_found_in_citation_map": False,
            "rank_in_results": rank_in_results,
            "top_k": top_k,
            "query_had_zero_hits": query_had_zero_hits,
            "canonical_path_check": "unavailable",
            "possible_path_variants": [],
            "staleness_indicator": "none",
            "secondary_diagnoses": [],
            "confidence": "medium",
            "instrumentation_notes": None,
        }

        if self._index_unavailable:
            details["instrumentation_notes"] = "index artifact unavailable or unsupported format"
            details["confidence"] = "low"

        # Found-in-results only proves a top-k hit when rank metadata confirms rank <= top_k.
        if (
            found_in_results
            and rank_in_results is not None
            and top_k is not None
            and rank_in_results <= top_k
        ):
            record = DiagnosticsRecord(
                query_id=query_id,
                query_text=query_text,
                expected_target=expected_target,
                primary_diagnosis="target_in_top_k",
                diagnosis_details=details,
            )
            details["confidence"] = "high"
            return record

        matching_paths: List[str] = []

        # Check if target is in the index by substring match against indexed paths.
        if self._index_paths:
            matching_paths = self.inspector.find_matching_paths(expected_target, self._index_paths)
            details["target_found_in_index"] = bool(matching_paths)

        # Check if target is in canonical_md
        if self._canonical_md:
            canonical_exists, check_status, variants = self.inspector.check_target_in_canonical(
                expected_target, self._canonical_md
            )
            details["target_found_in_canonical"] = canonical_exists
            details["canonical_path_check"] = check_status
            if variants:
                details["possible_path_variants"] = variants

        # Check citation linkage via chunk_id bridge: expected_target -> index path(s) -> chunk_id(s) -> citation_map.chunk_id
        if self._citation_chunk_ids is not None and self._path_to_chunk_ids is not None:
            chunk_ids_for_target = set()
            for path in matching_paths:
                chunk_ids_for_target.update(self._path_to_chunk_ids.get(path, set()))
            details["target_found_in_citation_map"] = bool(chunk_ids_for_target & self._citation_chunk_ids)

        # Now determine primary diagnosis based on what we found
        primary_diagnosis = self._classify_miss(
            expected_target,
            found_in_results,
            rank_in_results,
            top_k,
            details,
        )

        # Detect staleness if applicable
        if self._is_stale_indicator(expected_target):
            details["staleness_indicator"] = "path_format_obsolete"
            if primary_diagnosis != "stale_expected_target":
                details["secondary_diagnoses"].append("index_stale")

        record = DiagnosticsRecord(
            query_id=query_id,
            query_text=query_text,
            expected_target=expected_target,
            primary_diagnosis=primary_diagnosis,
            diagnosis_details=details,
        )

        return record

    def _classify_miss(
        self,
        expected_target: str,
        found_in_results: bool,
        rank_in_results: Optional[int],
        top_k: Optional[int],
        details: Dict[str, Any],
    ) -> str:
        """
        Classify the primary diagnosis based on diagnostic checks.

        Decision tree (in priority order):
        1. Check for staleness or ambiguity indicators first
        2. If target not in index -> target_missing_from_index
        3. If target not in canonical -> target_missing_from_canonical
        4. If target not in citation_map -> target_missing_from_citation_map
        5. If target in index but not observed in top-k -> target_exists_not_in_top_k
        6. Else -> diagnostic_inconclusive
        """
        # Check for staleness indicators first (before index check)
        if self._is_stale_indicator(expected_target):
            return "stale_expected_target"

        # Check for ambiguity (before index check)
        if self._is_ambiguous_target(expected_target):
            return "query_target_ambiguous"

        # Non path-like targets cannot be proven against path-only index keys.
        if not self._target_looks_path_like(expected_target):
            return "query_target_ambiguous"

        # If an index path was configured but could not be read, do not infer absence.
        if self._index_unavailable or self._index_paths is None:
            return "diagnostic_inconclusive"

        # Check index with substring semantics.
        if self._index_paths is not None and not details["target_found_in_index"]:
            return "target_missing_from_index"

        # Check canonical_md
        if self._canonical_md is not None and not details["target_found_in_canonical"]:
            return "target_missing_from_canonical"

        # Check citation_map
        if self._citation_map is not None and details["target_found_in_index"] and not details["target_found_in_citation_map"]:
            return "target_missing_from_citation_map"

        # If target exists in index but is not observed in top-k results,
        # classify as top-k/ranking signal without claiming absolute rank.
        if details["target_found_in_index"] and (
            not found_in_results
            or (
                found_in_results
                and rank_in_results is not None
                and top_k is not None
                and rank_in_results > top_k
            )
        ):
            return "target_exists_not_in_top_k"

        # Fallback
        return "diagnostic_inconclusive"

    def _is_stale_indicator(self, target: str) -> bool:
        """Check if target has staleness indicators (e.g., obsolete path format)."""
        # Examples: very old date patterns, deprecated naming
        stale_patterns = [r"^\d{4}-\d{2}-\d{2}/", r"^/tmp/", r"^\.git/"]
        return any(re.match(pat, target) for pat in stale_patterns)

    def _is_ambiguous_target(self, target: str) -> bool:
        """Check if target is ambiguous or malformed."""
        # Examples: empty, special characters, non-file-like
        if not target or len(target) < 2:
            return True
        # Check for suspicious patterns
        suspicious = [r"^[^a-zA-Z0-9/._-]+$", r"^<.+>$"]
        return any(re.match(pat, target) for pat in suspicious)

    def _target_looks_path_like(self, target: str) -> bool:
        """Heuristic: expected target behaves like a path/path-substring token."""
        if not isinstance(target, str) or not target:
            return False
        return "/" in target or "." in target

    def generate_report(
        self,
        misses: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Generate a complete diagnostics report from a list of misses.

        Args:
            misses: List of miss dictionaries, each with keys:
                - query_id: str
                - query_text: str
                - expected_target: str
                - found_in_results: bool
                - rank_in_results: Optional[int]
                - top_k: Optional[int]
                - query_had_zero_hits: bool

        Returns:
            Complete diagnostics report conforming to schema.
        """
        # Load artifacts once
        self._load_artifacts()

        diagnostics_records = []
        breakdowns = {
            "target_in_top_k": 0,
            "target_exists_not_in_top_k": 0,
            "target_missing_from_index": 0,
            "target_missing_from_canonical": 0,
            "target_missing_from_citation_map": 0,
            "stale_expected_target": 0,
            "query_target_ambiguous": 0,
            "diagnostic_inconclusive": 0,
        }

        for miss in misses:
            record = self.diagnose_miss(
                query_id=miss.get("query_id", ""),
                query_text=miss.get("query_text", ""),
                expected_target=miss.get("expected_target", ""),
                found_in_results=miss.get("found_in_results", False),
                rank_in_results=miss.get("rank_in_results"),
                top_k=miss.get("top_k"),
                query_had_zero_hits=miss.get("query_had_zero_hits", False),
            )

            diagnostics_records.append(record.to_dict())
            breakdowns[record.primary_diagnosis] += 1

        # Build report
        total_paths = len(self._index_paths) if self._index_paths else 0
        total_chunks = (
            sum(len(ids) for ids in self._path_to_chunk_ids.values())
            if self._path_to_chunk_ids
            else 0
        )

        report = {
            "authority": "diagnostic_signal",
            "risk_class": "diagnostic",
            "metadata": {
                "version": "1.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_misses": len(misses),
                "diagnostic_breakdowns": breakdowns,
                "index_stats": {
                    "total_chunks": total_chunks,
                    "total_paths": total_paths,
                    "canonical_md_exists": self._canonical_md is not None,
                    "citation_map_exists": self._citation_map is not None,
                },
            },
            "diagnostics": sorted(
                diagnostics_records,
                key=lambda x: (x["query_id"], x["expected_target"]),
            ),
        }

        return report

    def to_json(self, report: Dict[str, Any]) -> str:
        """Convert report to JSON string."""
        return json.dumps(report, indent=2, ensure_ascii=False)

    def save_report(self, report: Dict[str, Any], output_path: Path) -> None:
        """Save report to JSON file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(self.to_json(report))
