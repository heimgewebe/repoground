from enum import Enum


class ArtifactRole(str, Enum):
    """
    Eindeutige Rollenliste (Taxonomie) für Artefakte.
    Verhindert Drift ("role"-Strings sind sonst Spaghetti).
    """
    CANONICAL_MD = "canonical_md"
    INDEX_SIDECAR_JSON = "index_sidecar_json"
    CHUNK_INDEX_JSONL = "chunk_index_jsonl"
    DUMP_INDEX_JSON = "dump_index_json"
    SQLITE_INDEX = "sqlite_index"
    RETRIEVAL_EVAL_JSON = "retrieval_eval_json"
    DERIVED_MANIFEST_JSON = "derived_manifest_json"
    PR_DELTA_JSON = "delta_json"
    ARCHITECTURE_GRAPH_JSON = "architecture_graph_json"
    ENTRYPOINTS_JSON = "entrypoints_json"
    GRAPH_INDEX_JSON = "graph_index_json"
    ARCHITECTURE_SUMMARY = "architecture_summary"
    SOURCE_FILE = "source_file"
    OUTPUT_HEALTH = "output_health"
    CITATION_MAP_JSONL = "citation_map_jsonl"
    CLAIM_EVIDENCE_MAP_JSON = "claim_evidence_map_json"
    AGENT_READING_PACK = "agent_reading_pack"
    AGENT_ENTRY_MANIFEST = "agent_entry_manifest"
    EXPORT_SAFETY_REPORT = "export_safety_report"
    LENS_CARDS_JSONL = "lens_cards_jsonl"
    PR_DELTA_CARDS_JSONL = "pr_delta_cards_jsonl"


CLAIM_EVIDENCE_MAP_ABSENCE_REASON_LINK_KEY = "claim_evidence_map_absence_reason"
CLAIM_EVIDENCE_MAP_ABSENCE_REASONS = (
    "no_registry",
    "multi_repo_out_of_scope",
    "unexpected_missing_with_registry",
)

CLAIM_EVIDENCE_MAP_ABSENCE_REASON_MESSAGES = {
    "no_registry": "registry missing (docs/doc-freshness-registry.yml not found in source repo)",
    "multi_repo_out_of_scope": "multi-repo aggregation is out of scope",
    "unexpected_missing_with_registry": "registry existed but claim_evidence_map emission unexpectedly missing",
}
