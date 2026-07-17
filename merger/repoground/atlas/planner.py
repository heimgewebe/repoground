import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

def plan_atlas_outputs(scan_mode: str, scan_id: Optional[str] = None) -> Dict[str, str]:
    """
    Determines the set of artifacts to generate based on the scan mode.
    Returns a mapping of logical artifact keys to their expected filenames.
    """
    prefix = f"{scan_id}." if scan_id else ""
    outputs = {
        "summary": f"{prefix}summary.md"
    }

    if scan_mode == "inventory":
        outputs["inventory"] = f"{prefix}inventory.jsonl"
        outputs["dirs"] = f"{prefix}dirs.jsonl"
    elif scan_mode == "topology":
        outputs["topology"] = f"{prefix}topology.json"
    elif scan_mode == "content":
        outputs["inventory"] = f"{prefix}inventory.jsonl"
        outputs["content"] = f"{prefix}content.json"
    elif scan_mode == "workspace":
        outputs["workspaces"] = f"{prefix}workspaces.json"
        outputs["hotspots"] = f"{prefix}hotspots.json"

    return outputs

def write_mode_outputs(planned_outputs: Dict[str, str], result_stats: Dict[str, Any], output_dir: Path) -> None:
    """
    Writes actual JSON artifacts for structural modes (topology, content, workspace)
    and hotspot artifacts to the given output directory.
    """
    def _write_json_atomic(file_path: Path, data: dict):
        # We write atomically like app.py does but locally
        dir_path = file_path.parent
        dir_path.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=str(dir_path), prefix=f".tmp_{file_path.name}")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, str(file_path))
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    stats = result_stats.get("stats") if isinstance(result_stats.get("stats"), dict) else result_stats

    if "topology" in planned_outputs:
        topology_path = output_dir / planned_outputs["topology"]
        topology_data = stats.get("topology", {"root_path": ".", "nodes": {}})
        _write_json_atomic(topology_path, topology_data)

    if "content" in planned_outputs:
        content_path = output_dir / planned_outputs["content"]
        content_data = stats.get("content", {})
        _write_json_atomic(content_path, content_data)

    if "workspaces" in planned_outputs:
        workspaces_path = output_dir / planned_outputs["workspaces"]
        workspaces_data = stats.get("workspaces", [])
        _write_json_atomic(workspaces_path, workspaces_data)

    if "hotspots" in planned_outputs:
        hotspots_path = output_dir / planned_outputs["hotspots"]
        hotspots_data = stats.get("hotspots", {"top_dirs": stats.get("top_dirs", [])})
        _write_json_atomic(hotspots_path, hotspots_data)
