import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from ..service.query_artifact_store import QueryArtifactStore


def _resolve_storage_dir(hub: Optional[str]) -> Optional[Path]:
    if hub:
        # When --hub is given the service may have used a custom merges_dir.
        # We can only probe the default path here; if a custom merges_dir was
        # used at service start the caller should pass --hub pointing at it.
        return Path(hub) / "merges" / ".rlens-service"
    # Fall back to cwd-relative convention.
    candidate = Path.cwd() / "merges" / ".rlens-service"
    if candidate.exists():
        return candidate
    return None


def run_artifact_lookup(args: argparse.Namespace) -> int:
    storage_dir = _resolve_storage_dir(getattr(args, "hub", None))
    if storage_dir is None:
        print(
            "Error: could not locate .rlens-service directory. "
            "Pass --hub <hub_path> explicitly.",
            file=sys.stderr,
        )
        return 1

    artifact_type = getattr(args, "artifact_type", None)

    store = QueryArtifactStore(storage_dir)
    entry = store.get(args.id)

    if entry is None:
        result = {
            "artifact_type": artifact_type,
            "id": args.id,
            "status": "not_found",
            "artifact": None,
            "warnings": [f"No artifact found with id={args.id!r}"],
        }
        print(json.dumps(result, indent=2))
        return 1

    # If --artifact-type is given, validate that the stored type matches.
    if artifact_type is not None and entry["artifact_type"] != artifact_type:
        result = {
            "artifact_type": artifact_type,
            "id": args.id,
            "status": "not_found",
            "artifact": None,
            "warnings": [
                f"Artifact {args.id!r} has type {entry['artifact_type']!r}, "
                f"not {artifact_type!r}"
            ],
        }
        print(json.dumps(result, indent=2))
        return 1

    result = {
        "artifact_type": entry["artifact_type"],
        "id": entry["id"],
        "status": "ok",
        "artifact": {
            "provenance": entry["provenance"],
            "created_at": entry["created_at"],
            "data": entry["data"],
        },
        "warnings": [],
    }
    print(json.dumps(result, indent=2))
    return 0
