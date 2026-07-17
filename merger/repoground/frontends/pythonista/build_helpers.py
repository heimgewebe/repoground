# -*- coding: utf-8 -*-
from typing import Dict, Any, Optional, List, Union
from build_utils import normalize_path, normalize_repo_id

def resolve_pool_include_paths(pool_entry: Optional[Union[Dict[str, Any], List[str]]]) -> Optional[List[str]]:
    """
    Resolves the effective include_paths for scan_repo from a pool entry.

    Contract:
    - Input None -> None (ALL)
    - Input {} (empty dict) -> None (ALL)
    - Entry is list -> list (Legacy Partial/Block; [] means BLOCK)
    - Entry 'compressed': None -> None (ALL)
    - Entry 'compressed': [] -> [] (BLOCK)
    - Entry 'compressed': [...] -> [...] (PARTIAL)

    This function strictly decides the semantic meaning for the merger.
    It does NOT implement fallback logic or sanitization; that happens during deserialization.
    """
    if pool_entry is None:
        # No entry -> default behavior (usually ALL, handled by caller passing None to scan_repo)
        return None

    # Handle Legacy List
    if isinstance(pool_entry, list):
        return pool_entry

    # Handle empty dict
    if isinstance(pool_entry, dict) and not pool_entry:
        return None

    # Structured format expectation
    compressed = pool_entry.get("compressed")

    if compressed is None:
        return None # ALL

    if isinstance(compressed, list):
        # Strict: empty list means BLOCK ([]), populated list means PARTIAL
        return compressed

    # Should not be reached if deserialization contract holds, but fail safe
    return None


def deserialize_prescan_pool(pool_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Deserialize prescan pool with strict contract enforcement, sanitization, and controlled fallback.

    Returns dict mapping repo -> {"raw": ..., "compressed": ...}
    Keys are normalized using normalize_repo_id to prevent drift.
    """
    deserialized = {}
    if not isinstance(pool_data, dict):
        return {}

    for repo, selection in pool_data.items():
        processed_entry = _deserialize_entry(selection)
        if processed_entry:
             # Normalize key to prevent drift (e.g. Hub/Repo -> repo)
             norm_key = normalize_repo_id(repo)
             if norm_key: # Ignore empty keys
                 deserialized[norm_key] = processed_entry

    return deserialized


def _deserialize_entry(selection: Any) -> Optional[Dict[str, Any]]:
    """
    Process a single pool entry.

    Internal representation (structured):
    - {"raw": None, "compressed": None}: ALL state
    - {"raw": list[str], "compressed": list[str]}: Partial selection (or Block if empty)
    """
    # 1. Handle Legacy / Simple Types
    if selection is None:
        # ALL state
        return {"raw": None, "compressed": None}

    if isinstance(selection, list):
        # Legacy format: simple list is used for both.
        # Sanitize list
        valid_paths, dropped = _sanitize_list(selection)
        # Even if dropped, for legacy list we just use what we have.
        # Empty list here implies BLOCK (or empty selection).
        normalized = [normalize_path(p) for p in valid_paths]
        return {"raw": normalized, "compressed": normalized}

    if not isinstance(selection, dict):
        # Unknown format - drop
        return None

    # 2. Handle Structured Format
    raw_input = selection.get("raw")
    compressed_input = selection.get("compressed")

    # Case: ALL
    if raw_input is None and compressed_input is None:
        return {"raw": None, "compressed": None}

    # Case: Partial / Block
    # Sanitize inputs
    raw_clean, raw_dropped = _sanitize_list(raw_input)

    # Special handling for compressed=None (Explicit ALL in structured format)
    # If compressed_input is explicitly None, it should remain None (ALL), NOT become [] (BLOCK).
    # _sanitize_list(None) returns [], False which would convert None to [].
    if compressed_input is None:
        compressed_clean = None
        compressed_dropped = False
    else:
        compressed_clean, compressed_dropped = _sanitize_list(compressed_input)

    sanitized_dropped = raw_dropped or compressed_dropped

    # Fallback Logic (Strictly Limited)
    # If:
    #   - compressed is empty (BLOCK) - but NOT None
    #   - raw has content
    #   - we dropped something during sanitization (indicating data corruption/type issues)
    # Then:
    #   - Fallback to raw (assume compressed was corrupted)

    final_compressed = compressed_clean

    # Only consider fallback if compressed is an empty list (BLOCK), not if it is None (ALL)
    if (final_compressed is not None and len(final_compressed) == 0 and
        len(raw_clean) > 0 and
        sanitized_dropped):
            # One-time fallback
            final_compressed = raw_clean

    # Normalize paths
    normalized_raw = [normalize_path(p) for p in raw_clean]

    normalized_compressed = None
    if final_compressed is not None:
        normalized_compressed = [normalize_path(p) for p in final_compressed]

    return {
        "raw": normalized_raw,
        "compressed": normalized_compressed
    }


def _sanitize_list(data: Any) -> tuple[List[str], bool]:
    """
    Filter non-string entries.
    Returns (clean_list, dropped_flag)
    """
    if data is None:
        return [], False

    if not isinstance(data, list):
        return [], True

    clean = []
    dropped = False
    for item in data:
        if isinstance(item, str):
            clean.append(item)
        else:
            dropped = True

    return clean, dropped
