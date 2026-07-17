from pathlib import Path
from typing import Any, Dict, List

from merger.repoground.adapters.atlas import AtlasScanner

def _scan_workspaces(root: Path) -> List[Dict[str, Any]]:
    """Helper to run a scan and return detected workspaces."""
    scanner = AtlasScanner(root)
    result = scanner.scan()
    return result["stats"]["workspaces"]

def test_atlas_workspace_git_detection(tmp_path: Path):
    git_repo = tmp_path / "git_repo"
    git_repo.mkdir()
    (git_repo / ".git").mkdir()
    (git_repo / "README.md").write_text("Git Repo", encoding="utf-8")

    workspaces = _scan_workspaces(tmp_path)
    ws = next(w for w in workspaces if w["root_path"] == "git_repo")

    assert ws["workspace_kind"] == "git_repo"
    assert ".git" in ws["signals"]
    assert "README.md" in ws["signals"]

def test_atlas_workspace_node_detection(tmp_path: Path):
    node_proj = tmp_path / "node_project"
    node_proj.mkdir()
    (node_proj / "package.json").write_text('{"name": "test"}', encoding="utf-8")

    workspaces = _scan_workspaces(tmp_path)
    ws = next(w for w in workspaces if w["root_path"] == "node_project")

    assert ws["workspace_kind"] == "node_project"
    assert "package.json" in ws["signals"]

def test_atlas_workspace_python_detection(tmp_path: Path):
    py_proj = tmp_path / "python_project"
    py_proj.mkdir()
    (py_proj / "pyproject.toml").write_text("[tool.poetry]", encoding="utf-8")
    (py_proj / "README.md").write_text("Python Project", encoding="utf-8")

    workspaces = _scan_workspaces(tmp_path)
    ws = next(w for w in workspaces if w["root_path"] == "python_project")

    assert ws["workspace_kind"] == "python_project"
    assert "pyproject.toml" in ws["signals"]
    assert "README.md" in ws["signals"]

def test_atlas_workspace_mixed_detection(tmp_path: Path):
    mixed_ws = tmp_path / "mixed"
    mixed_ws.mkdir()
    (mixed_ws / ".ai-context.yml").write_text("context: test", encoding="utf-8")
    (mixed_ws / "README.md").write_text("Mixed", encoding="utf-8")

    workspaces = _scan_workspaces(tmp_path)
    ws = next(w for w in workspaces if w["root_path"] == "mixed")

    assert ws["workspace_kind"] == "mixed_workspace"
    assert ".ai-context.yml" in ws["signals"]
    assert "README.md" in ws["signals"]

def test_atlas_scanner_constants_accessible():
    assert isinstance(AtlasScanner.WORKSPACE_SIGNALS, tuple)
    assert ".ai-context.yml" in AtlasScanner.WORKSPACE_SIGNALS
    assert isinstance(AtlasScanner.DEFAULT_ATLAS_EXCLUDES, tuple)
    assert "proc/**" in AtlasScanner.DEFAULT_ATLAS_EXCLUDES
