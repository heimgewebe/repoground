"""End-to-end guard: the published daily bundle must serve call navigation.

The profile rules in `snapshot_profiles` and the tests around them only describe
what a publication *should* contain. They stayed green when `fleet-context`
started excluding `python_symbol_index_json` and `python_call_graph_json`, which
silently removed `find_symbol`, `get_callers`, and `get_callees` from the
agent-facing surface for two days without a single failing test.

This test closes that gap from the other end: it emits a real publication
through the same CLI path the daily fleet publisher uses, then calls all three
tools against the emitted manifest. It fails if the shipped bundle cannot answer
them, regardless of what the profile tables claim.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from merger.repoground.core.bundle_access import get_callees, get_callers
from merger.repoground.core.mcp_tools import find_symbol

# The profile the fleet publisher selects for ordinary daily publications.
# Keep this in sync with `publication_config` in scripts/ops/repoground-publish-fleet.
DAILY_FLEET_PROFILE = "fleet-context"

REPO_ROOT = Path(__file__).resolve().parents[3]

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


def _publish(tmp_path: Path, repo: Path) -> dict:
    publication_root = tmp_path / "pub"
    out_dir = publication_root / "gen"
    out_dir.mkdir(parents=True)
    completed = subprocess.run(
        [
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
            DAILY_FLEET_PROFILE,
            "--output-mode",
            "dual",
            "--max-bytes",
            "0",
            "--split-size",
            "25MB",
            "--redact-secrets",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        f"publication failed ({completed.returncode}):\n{completed.stdout[-4000:]}\n"
        f"{completed.stderr[-4000:]}"
    )
    return json.loads(completed.stdout)


def _published_manifest(tmp_path: Path) -> Path:
    external = tmp_path / "pub" / "external" / "_bundles" / "demo__demo" / "main"
    manifests = sorted(external.rglob("*_merge.bundle.manifest.json"))
    assert manifests, f"no published bundle manifest under {external}"
    return manifests[-1]


@pytest.fixture(scope="module")
def published_bundle(tmp_path_factory) -> tuple[Path, dict]:
    tmp_path = tmp_path_factory.mktemp("publication_surface")
    repo = _source_repo(tmp_path)
    report = _publish(tmp_path, repo)
    return _published_manifest(tmp_path), report


@pytest.mark.publication_surface
def test_daily_profile_publishes_the_call_navigation_artifacts(published_bundle):
    manifest_path, report = published_bundle
    snapshot = report["snapshot"]

    assert report["status"] == "ok"
    assert snapshot["status"] == "ok"
    assert snapshot["profile"] == DAILY_FLEET_PROFILE
    evaluation = snapshot["profile_evaluation"]
    assert evaluation["profile"] == DAILY_FLEET_PROFILE
    assert evaluation["status"] == "pass"
    assert evaluation["profile_excluded_present"] == []

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rules = manifest["capabilities"]["repobrief_profile_policy"]["artifact_rules"]
    for role in ("python_symbol_index_json", "python_call_graph_json"):
        assert rules[role] != "profile_excluded", (
            f"{role} is excluded from the daily publication; "
            "find_symbol/get_callers/get_callees cannot be served"
        )

    # The storage intent of the compact profile is still honoured.
    assert rules["sqlite_index"] == "profile_excluded"
    removed = " ".join(snapshot["removed_profile_excluded_artifacts"])
    assert "python_symbol_index" not in removed
    assert "python_call_graph" not in removed


@pytest.mark.publication_surface
def test_find_symbol_answers_against_the_published_bundle(published_bundle):
    manifest_path, _ = published_bundle

    result = find_symbol(bundle_manifest=manifest_path, name="target", k=10)["result"]

    assert result["status"] == "available", result.get("error")
    assert [(hit["name"], hit["path"]) for hit in result["hits"]] == [
        ("target", "pkg/core.py")
    ]


@pytest.mark.publication_surface
def test_get_callers_answers_against_the_published_bundle(published_bundle):
    manifest_path, _ = published_bundle

    result = get_callers(manifest_path, "target", k=10)

    assert result["status"] == "available", result.get("error")
    assert [caller["path"] for caller in result["callers"]] == ["pkg/caller.py"]
    assert result["call_graph_coverage"]["completeness"] in {"complete", "partial"}


@pytest.mark.publication_surface
def test_get_callees_answers_against_the_published_bundle(published_bundle):
    manifest_path, _ = published_bundle

    result = get_callees(manifest_path, "run_once", k=10)

    assert result["status"] == "available", result.get("error")
    assert result["callees"], "run_once calls target; the callee list must not be empty"
    assert result["call_graph_coverage"]["completeness"] in {"complete", "partial"}
