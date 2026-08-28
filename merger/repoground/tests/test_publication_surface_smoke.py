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


def rust_helper(value):
    return value


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
    (repo / "src").mkdir()
    (repo / "src" / "lib.rs").write_text(
        'pub fn rust_helper() {\n    println!("ok");\n}\n', encoding="utf-8"
    )
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
    if config.language_structure:
        argv.append("--language-structure")
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
    # Every role here backs an agent-facing tool. Excluding one does not shrink
    # that tool's answers, it removes the tool: the symbol index and call graph
    # carry find_symbol/find_references/get_callers/get_callees, `sqlite_index`
    # carries `query`.
    for role, tools in (
        ("python_symbol_index_json", "find_symbol/find_references"),
        ("python_call_graph_json", "get_callers/get_callees"),
        ("sqlite_index", "query"),
    ):
        assert rules[role] != "profile_excluded", (
            f"{role} is excluded from the daily publication; {tools} cannot be served"
        )

    removed = " ".join(snapshot["removed_profile_excluded_artifacts"])
    assert "python_symbol_index" not in removed
    assert "python_call_graph" not in removed
    assert "sqlite" not in removed


@pytest.mark.publication_surface
def test_query_answers_against_the_published_bundle(published_bundle):
    """`query` must find an identifier the published bundle demonstrably contains.

    This is the assertion whose absence let `sqlite_index` be dropped from the
    daily profile: `query` kept reporting `available` while returning nothing for
    every input, including identifiers present in the indexed source.
    """
    manifest_path, _, _ = published_bundle

    response = mcp_tools.query_existing_index(
        bundle_manifest=manifest_path, query="helper", k=5
    )

    assert response["status"] == "available", response.get("retrieval_infrastructure")
    assert response["retrieval_infrastructure"]["index_resolved"] is True
    assert response["retrieval"]["strategy"] != "none"
    assert response["retrieval"]["match_count"] > 0
    assert any(
        entry.get("source_path") == "pkg/core.py"
        for entry in response["resolved_ranges"]
    ), response["resolved_ranges"]


@pytest.mark.publication_surface
def test_query_preserves_structured_evidence_from_published_bundle(published_bundle):
    """The query frontdoor must not drop structure emitted by the real publisher."""
    manifest_path, _, _ = published_bundle

    response = mcp_tools.query_existing_index(
        bundle_manifest=manifest_path, query="Where is rust_helper defined?", k=5
    )

    assert response["status"] == "available"
    assert response["route"] == "symbol_definition"
    assert response["retrieval"]["strategy"] == "symbol_definition"
    assert any(
        hit["path"] == "pkg/core.py" and hit["name"] == "rust_helper"
        for hit in response["navigation_hits"]
    )
    language = response["structured_evidence"]["language_structure"]
    records = language["evidence"]["records"]
    assert records
    assert any(
        record["language"] == "rust" and record["symbol"] == "rust_helper"
        for record in records
    )


def test_query_preserves_explicit_empty_structured_evidence(monkeypatch):
    def fake_pack(*args, **kwargs):
        return {
            "retrieval_infrastructure": {"index_resolved": True, "status": "available"},
            "retrieval": {"strategy": "none", "match_count": 0},
            "retrieval_hits": [],
            "resolved_ranges": [],
            "budget": {},
            "availability": {},
            "freshness": {},
            "answer_scaffold": {"caveats_to_surface": []},
            "structured_evidence": {},
        }

    monkeypatch.setattr(
        "merger.repoground.core.ask_context.build_ask_context_pack", fake_pack
    )

    response = mcp_tools.query_existing_index(
        bundle_manifest="unused", query="no symbol intent"
    )

    assert response["structured_evidence"] == {}


@pytest.mark.publication_surface
def test_query_returns_no_hits_for_an_absent_term(published_bundle):
    """A term genuinely absent from the repo must be an empty answer, not an error.

    Paired with the test above this pins both directions: without it, "always
    returns hits" would pass just as happily as a working index.
    """
    manifest_path, _, _ = published_bundle

    response = mcp_tools.query_existing_index(
        bundle_manifest=manifest_path, query="zzzqqqxyzabsentidentifier", k=5
    )

    assert response["status"] == "available"
    assert response["retrieval_infrastructure"]["index_resolved"] is True
    assert response["retrieval"]["match_count"] == 0
    assert response["resolved_ranges"] == []


@pytest.mark.publication_surface
def test_query_results_depend_on_the_query(published_bundle):
    """Different queries must produce different evidence.

    `context_compose` feeds its `query_snippets` lane from these ranges, so a
    query-independent result there is this failure one layer up: two unrelated
    queries composed byte-identical context while the index was missing.
    """
    manifest_path, _, _ = published_bundle

    helper_ranges = mcp_tools.query_existing_index(
        bundle_manifest=manifest_path, query="helper", k=5
    )["resolved_ranges"]
    caller_ranges = mcp_tools.query_existing_index(
        bundle_manifest=manifest_path, query="run_once", k=5
    )["resolved_ranges"]

    assert helper_ranges and caller_ranges
    assert helper_ranges != caller_ranges
    assert any(r.get("source_path") == "pkg/caller.py" for r in caller_ranges)


@pytest.mark.publication_surface
def test_query_reports_unavailable_when_the_search_index_is_absent(
    published_bundle, tmp_path
):
    """Missing search infrastructure must surface, not masquerade as no results.

    The profile fix restores the index; this pins the behaviour that made its
    absence undetectable for days. A bundle without `sqlite_index` previously
    answered `status: available` with zero hits and advised the caller to
    rephrase — indistinguishable from a genuinely empty repository.
    """
    manifest_path, _, _ = published_bundle
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"] = [
        artifact
        for artifact in manifest["artifacts"]
        if artifact.get("role") != "sqlite_index"
    ]
    stripped = tmp_path / manifest_path.name
    stripped.write_text(json.dumps(manifest), encoding="utf-8")

    response = mcp_tools.query_existing_index(
        bundle_manifest=stripped, query="helper", k=5
    )

    assert response["status"] == "missing"
    infrastructure = response["retrieval_infrastructure"]
    assert infrastructure["index_resolved"] is False
    assert infrastructure["error_code"] == "sqlite_index_missing"
    assert response["availability"]["status"] == "missing"
    # The "rephrase your query" advice is actively wrong here and must not appear.
    assert not any(
        "Rephrase" in caveat.get("detail", "")
        for caveat in response["answer_caveats"]
    ), response["answer_caveats"]


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
