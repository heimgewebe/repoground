from pathlib import Path
from typing import Optional

def resolve_atlas_base_dir(registry_db_path: Optional[Path] = None) -> Path:
    """
    Determines the canonical base directory for Atlas artifacts.

    If a registry path is provided, the base is derived deterministically
    from it (two levels up from the registry sqlite file).

    If no registry path is known, it falls back to the current working
    directory's 'atlas' folder (explicit fallback).
    """
    if registry_db_path is not None:
        return registry_db_path.resolve().parent.parent

    # Fallback only used if absolutely unavoidable
    return (Path.cwd() / "atlas").resolve()

def resolve_index_db_path(registry_db_path: Optional[Path] = None) -> Path:
    """
    Determines the canonical path for the global Atlas FTS index.

    Per ADR-008 the index lives at ``<atlas_base>/indexes/fts.sqlite``. The
    base is derived deterministically from the registry path (independent of
    the process CWD), matching the registry/artifact resolution strategy.
    """
    atlas_base = resolve_atlas_base_dir(registry_db_path)
    return atlas_base / "indexes" / "fts.sqlite"

def resolve_snapshot_dir(atlas_base_dir: Path, machine_id: str, root_id: str, snapshot_id: str) -> Path:
    """
    Determines the canonical directory for a specific snapshot.
    """
    return atlas_base_dir / "machines" / machine_id / "roots" / root_id / "snapshots" / snapshot_id

def resolve_artifact_ref(atlas_base_dir: Path, ref_path: str) -> Path:
    """
    Resolves a stored artifact reference. If the reference is absolute,
    it is returned as-is. If it is relative, it is resolved against the
    canonical atlas base directory (NOT the process CWD).
    """
    p = Path(ref_path)
    if p.is_absolute():
        return p

    # Handle legacy paths that include 'atlas/' prefix
    # when the base directory itself is named 'atlas'
    parts = p.parts
    if atlas_base_dir.name == "atlas" and parts and parts[0] == "atlas":
        p = Path(*parts[1:])

    resolved_path = (atlas_base_dir / p).resolve()

    # Path traversal prevention
    try:
        resolved_path.relative_to(atlas_base_dir.resolve())
    except ValueError:
        raise ValueError("Artifact reference escapes atlas base directory")

    return resolved_path
