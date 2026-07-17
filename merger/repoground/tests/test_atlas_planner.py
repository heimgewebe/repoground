import json
from pathlib import Path
from merger.repoground.atlas.planner import plan_atlas_outputs, write_mode_outputs

def test_plan_atlas_outputs_inventory():
    plan = plan_atlas_outputs("inventory", "atlas-123")
    assert "summary" in plan
    assert plan["summary"] == "atlas-123.summary.md"
    assert "inventory" in plan
    assert plan["inventory"] == "atlas-123.inventory.jsonl"
    assert "dirs" in plan
    assert plan["dirs"] == "atlas-123.dirs.jsonl"
    assert "topology" not in plan
    assert "workspaces" not in plan

def test_plan_atlas_outputs_topology():
    plan = plan_atlas_outputs("topology", "atlas-123")
    assert "summary" in plan
    assert "topology" in plan
    assert plan["topology"] == "atlas-123.topology.json"
    assert "inventory" not in plan

def test_plan_atlas_outputs_content():
    plan = plan_atlas_outputs("content", "atlas-123")
    assert "summary" in plan
    assert "inventory" in plan
    assert "content" in plan
    assert plan["content"] == "atlas-123.content.json"
    assert "workspaces" not in plan

def test_plan_atlas_outputs_workspace():
    plan = plan_atlas_outputs("workspace", "atlas-123")
    assert "summary" in plan
    assert "workspaces" in plan
    assert plan["workspaces"] == "atlas-123.workspaces.json"
    assert "hotspots" in plan
    assert plan["hotspots"] == "atlas-123.hotspots.json"
    assert "inventory" not in plan

def test_write_mode_outputs(tmp_path: Path):
    planned_outputs = {
        "topology": "out.topology.json",
        "content": "out.content.json",
        "workspaces": "out.workspaces.json",
        "hotspots": "out.hotspots.json"
    }

    # Pass the stats directly at the top level to model the possibility
    # of an un-nested result (as per the code review scenario).
    result_stats = {
        "top_dirs": [
            {"path": "/src", "bytes": 1000},
            {"path": "/docs", "bytes": 500}
        ],
        "workspaces": [
            {
                "workspace_id": "ws_123",
                "root_path": "/src",
                "workspace_kind": "python_project",
                "signals": ["pyproject.toml"],
                "confidence": 0.5,
                "tags": ["python_project"]
            }
        ],
        "topology": {
            "root_path": "/",
            "nodes": {
                "/src": {"path": "/src", "depth": 1, "dirs": []}
            }
        },
        "content": {
            "text_files_count": 10,
            "binary_files_count": 2,
            "large_files": [],
            "extensions": {".py": 10}
        },
        "hotspots": {
            "top_dirs": [{"path": "/src", "bytes": 1000}],
            "highest_file_density": [{"path": "/src", "count": 12}],
            "deepest_paths": [{"path": "/src", "depth": 1}],
            "highest_signal_density": [{"path": "/src", "signals": 1}]
        }
    }

    write_mode_outputs(planned_outputs, result_stats, tmp_path)

    topology_file = tmp_path / "out.topology.json"
    assert topology_file.exists()
    topology_data = json.loads(topology_file.read_text(encoding="utf-8"))
    assert topology_data["root_path"] == "/"
    assert "/src" in topology_data["nodes"]

    content_file = tmp_path / "out.content.json"
    assert content_file.exists()
    content_data = json.loads(content_file.read_text(encoding="utf-8"))
    assert content_data["text_files_count"] == 10
    assert content_data["extensions"][".py"] == 10

    workspaces_file = tmp_path / "out.workspaces.json"
    assert workspaces_file.exists()
    workspaces_data = json.loads(workspaces_file.read_text(encoding="utf-8"))
    assert len(workspaces_data) == 1
    assert workspaces_data[0]["workspace_id"] == "ws_123"
    assert workspaces_data[0]["workspace_kind"] == "python_project"

    hotspots_file = tmp_path / "out.hotspots.json"
    assert hotspots_file.exists()
    hotspots_data = json.loads(hotspots_file.read_text(encoding="utf-8"))
    assert "top_dirs" in hotspots_data
    assert len(hotspots_data["top_dirs"]) == 1
    assert hotspots_data["top_dirs"][0]["path"] == "/src"
    assert "highest_file_density" in hotspots_data
    assert hotspots_data["highest_file_density"][0]["path"] == "/src"

    # Verify formatting (indent=2)
    raw_content = hotspots_file.read_text(encoding="utf-8")
    assert "\n  \"top_dirs\": [\n" in raw_content or "\n  \"top_dirs\": [" in raw_content
