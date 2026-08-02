"""End-to-end guard: the published daily bundle must serve call navigation.

The profile rules in `snapshot_profiles` and the tests around them only describe
what a publication *should* contain. They stayed green when `fleet-context`
started excluding `python_symbol_index_json` and `python_call_graph_json`, which
silently removed `find_symbol`, `find_references`, `get_callers`, and
`get_callees` from the agent-facing surface for two days without a single
failing test.

This test closes that gap from the other end: it emits a real publication
through the same CLI path the daily fleet publisher uses, then calls all four
tools against the emitted manifest. It fails if the shipped bundle cannot answer
them, regardless of what the profile tables claim.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from merger.repoground.core import mcp_tools

REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLISHER = REPO_ROOT / "scripts/ops/repoground-publish-fleet"

CORE_MODULE = """\
def helper(value):
    return value + 1


def target(value):
    return helper(value)
"""

CALLER_MODULE = """\
from pkg.core import target


def run_once(value):
    return target(value)
"""


def _load_publisher() -> ModuleType:
    module_name = "repoground_publish_fleet_surface_test"
    loader = importlib.machinery.SourceFileLoader(module_name, str(PUBLISHER))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module


def _daily_fleet_config(repo: Path):
    publisher = _load_publisher()
    entry = publisher.RepoEntry(
        key="demo/demo",
        owner="demo",
        repo="demo",
        path=repo,
        remote="git@github.com:demo/demo.git",
    )
    return publisher.publication_config(entry)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _source_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "src"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "core.py").write_text(CORE_MODULE, encoding="utf-8")
    (repo / "pkg" / "caller.py").write_text(CALLER_MODULE, encoding="utf-8")
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    _git(repo, "init", "-q", ".")
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.email=smoke@example.invalid",
        "-c",
        "user.name=smoke",
        "commit",
        "-qm",
        "init",
    )
    return repo


def _publish(tmp_path: Path, repo: Path) -> tuple[dict, dict[str, object]]:
    publication_root = tmp_path / "pub"
    out_dir = publication_root / "gen"
    out_dir.mkdir(parents=True)
    config = _daily_fleet_config(repo)
    argv = [
        sys.executable,
        "-B",
        "-m",
        "merger.repoground.cli.ground",
        "external-manifest",
        "refresh",
        "--repo",
        str(repo),
        "--out",
        str(out_dir),
        "--publication-root",
        str(publication_root),
        "--repository",
        "demo__demo",
        "--ref",
        "main",
        "--profile",
        config.profile,
        "--output-mode",
        config.output_mode,
        "--max-bytes",
        str(config.max_bytes),
        "--split-size",
        config.split_size,
    ]
    if config.redact_secrets:
        argv.append("--redact-secrets")
    completed = subprocess.run(
        argv,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        f"publication failed ({completed.returncode}):\n{completed.stdout[-4000:]}\n"
        f"{completed.stderr[-4000:]}"
    )
    return json.loads(completed.stdout), config.as_dict()


def _published_manifest(tmp_path: Path) -> Path:
    external = tmp_path / "pub" / "external" / "_bundles" / "demo__demo" / "main"
    manifests = sorted(external.rglob("*_merge.bundle.manifest.json"))
    assert manifests, f"no published bundle manifest under {external}"
    return manifests[-1]


@pytest.fixture(scope="module")
def published_bundle(tmp_path_factory) -> tuple[Path, dict, dict[str, object]]:
    tmp_path = tmp_path_factory.mktemp("publication_surface")
    repo = _source_repo(tmp_path)
    report, config = _publish(tmp_path, repo)
    return _published_manifest(tmp_path), report, config


def _available_mcp_result(response: dict, tool: str) -> dict:
    assert response["tool"] == tool
    assert response["status"] == "available"
    result = response["result"]
    assert result["status"] == "available", result.get("error")
    assert result["projection"] == "repobrief.read_response.compact.v1"
    return result


@pytest.mark.publication_surface
def test_daily_profile_publishes_the_call_navigation_artifacts(published_bundle):
    manifest_path, report, config = published_bundle
    snapshot = report["snapshot"]

    assert report["status"] == "ok"
    assert snapshot["status"] == "ok"
    assert snapshot["profile"] == config["profile"]
    evaluation = snapshot["profile_evaluation"]
    assert evaluation["profile"] == config["profile"]
    assert evaluation["status"] == "pass"
    assert evaluation["profile_excluded_present"] == []

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rules = manifest["capabilities"]["repobrief_profile_policy"]["artifact_rules"]
    for role in ("python_symbol_index_json", "python_call_graph_json"):
        assert rules[role] != "profile_excluded", (
            f"{role} is excluded from the daily publication; "
            "find_symbol/find_references/get_callers/get_callees cannot be served"
        )

    # The storage intent of the compact profile is still honoured.
    assert rules["sqlite_index"] == "profile_excluded"
    removed = " ".join(snapshot["removed_profile_excluded_artifacts"])
    assert "python_symbol_index" not in removed
    assert "python_call_graph" not in removed


@pytest.mark.publication_surface
def test_find_symbol_answers_against_the_published_bundle(published_bundle):
    manifest_path, _, _ = published_bundle

    result = _available_mcp_result(
        mcp_tools.find_symbol(bundle_manifest=manifest_path, name="target", k=10),
        "find_symbol",
    )

    assert [(hit["name"], hit["path"]) for hit in result["hits"]] == [
        ("target", "pkg/core.py")
    ]


@pytest.mark.publication_surface
def test_find_references_answers_against_the_published_bundle(published_bundle):
    manifest_path, _, _ = published_bundle

    result = _available_mcp_result(
        mcp_tools.find_references(bundle_manifest=manifest_path, name="target", k=10),
        "find_references",
    )

    assert [(hit["simple_name"], hit["path"]) for hit in result["hits"]] == [
        ("target", "pkg/caller.py")
    ]
    assert result["call_graph_coverage"]["scope"] == "observed_call_edges"
    assert result["call_graph_coverage"]["completeness"] in {"complete", "partial"}


@pytest.mark.publication_surface
def test_get_callers_answers_against_the_published_bundle(published_bundle):
    manifest_path, _, _ = published_bundle

    result = _available_mcp_result(
        mcp_tools.get_callers(bundle_manifest=manifest_path, name="target", k=10),
        "get_callers",
    )

    assert [caller["path"] for caller in result["callers"]] == ["pkg/caller.py"]
    assert result["call_graph_coverage"]["completeness"] in {"complete", "partial"}


@pytest.mark.publication_surface
def test_get_callees_answers_against_the_published_bundle(published_bundle):
    manifest_path, _, _ = published_bundle

    result = _available_mcp_result(
        mcp_tools.get_callees(bundle_manifest=manifest_path, name="run_once", k=10),
        "get_callees",
    )

    assert [
        (callee["callee_symbol"]["name"], callee["callee_symbol"]["path"])
        for callee in result["callees"]
    ] == [("target", "pkg/core.py")]
    assert result["call_graph_coverage"]["scope"] == "observed_call_edges"
    assert result["call_graph_coverage"]["completeness"] in {"complete", "partial"}
