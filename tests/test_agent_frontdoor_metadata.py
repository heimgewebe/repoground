from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _yaml(path: str) -> dict[str, object]:
    data = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_agents_explicit_document_links_exist() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    documented_paths = {
        value
        for value in re.findall(r"`(docs/[^`]+\.md)`", agents)
        if "*" not in value
    }
    assert documented_paths
    missing = sorted(path for path in documented_paths if not (ROOT / path).is_file())
    assert missing == []


def test_agents_describes_real_operating_flow_and_cli_boundary() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for phrase in (
        "Bind live state",
        "Choose a task profile",
        "Read RepoGround evidence",
        "Plan in the agent",
        "Execute through Grabowski",
        "Read back reality",
    ):
        assert phrase in agents
    assert "merger/repoground/cli/serve.py` is the RepoGround service entry point / launcher" in agents
    assert "docs/blueprints/repoground-cli-operational-blueprint.md" in agents
    assert "docs/blueprints/repoground-cli-client-blueprint.md" not in agents


def test_wgx_active_identity_is_repoground() -> None:
    profile = _yaml(".wgx/profile.yml")
    assert profile["profile"] == "repoground"
    assert profile["class"] == "knowledge-compiler"
    assert "RepoGround" in str(profile["description"])
    active_text = (ROOT / ".wgx/profile.yml").read_text(encoding="utf-8")
    assert "lenskit" not in active_text.lower()
    assert "repolens" not in active_text.lower()
    meta = profile["meta"]
    assert isinstance(meta, dict)
    assert "repoground" in meta["tags"]
    tasks = profile["tasks"]
    assert isinstance(tasks, dict)
    assert all("repoground" in str(command).lower() for command in tasks.values())


def test_ai_context_explains_visibility_and_python_certification() -> None:
    context = _yaml(".ai-context.yml")
    project = context["project"]
    assert isinstance(project, dict)
    assert project["visibility"] == "internal"
    semantics = str(project["visibility_semantics"]).lower()
    assert "keine zugriffskontrolle" in semantics
    dependencies = context["dependencies"]
    assert isinstance(dependencies, dict)
    external = dependencies["external"]
    assert isinstance(external, list)
    python = next(item for item in external if item.get("name") == "python")
    assert python["version"] == ">=3.11"
    assert python["support_semantics"] == "minimum_supported"
    assert python["ci_certified_versions"] == ["3.12"]
