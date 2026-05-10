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
    GRAPH_INDEX_JSON = "graph_index_json"
    ARCHITECTURE_SUMMARY = "architecture_summary"
    SOURCE_FILE = "source_file"
    OUTPUT_HEALTH = "output_health"
    CITATION_MAP_JSONL = "citation_map_jsonl"
