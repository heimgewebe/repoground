"""Real publication of the existing cross-language relationship projection."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import jsonschema

from merger.repoground.core.merge import FileInfo, write_reports_v2
from merger.repoground.core.relationship_projection_access import read_structure_neighborhood
from merger.repoground.tests._test_constants import make_generator_info
from merger.repoground.tests.git_fixture import commit_fixture
from merger.repoground.tests.test_bundle_manifest_integration import MockExtras


def published_bundle(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    sources = {
        "pkg/__init__.py": "",
        "pkg/core.py": "def work():\n    return 1\n\ndef dynamic(func):\n    return func()\n",
        "pkg/use.py": "from pkg.core import work\n\ndef run():\n    return work()\n",
        "README.md": "[Core](pkg/core.py)\n",
        "default.nix": "import ./config.nix\n",
        "config.nix": "{ value = 1; }\n",
        "web/main.mjs": 'import { value } from "./value.mjs";\nexport const result = value;\n',
        "web/value.mjs": "export const value = 1;\n",
        "schemas/core.json": '{"type":"object"}\n',
        "schemas/use.json": '{"$ref":"./core.json"}\n',
        "compose.yml": "services:\n  app:\n    env_file: ./app.env\n",
        "app.env": "MODE=test\n",
        ".github/actions/local/action.yml": "runs:\n  using: composite\n  steps: []\n",
        ".github/workflows/ci.yml": (
            "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - uses: ./.github/actions/local\n"
            "      - run: &script |\n          uses: ./not-a-real-action\n"
        ),
    }
    files = []
    for relative, text in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        files.append(FileInfo(
            root_label="fixture", abs_path=path, rel_path=Path(relative),
            size=path.stat().st_size, is_text=True, md5="fixture",
            category="code", tags=[], ext=path.suffix, skipped=False,
        ))
    commit = commit_fixture(root)
    out, hub = tmp_path / "bundles", tmp_path / "hub"
    out.mkdir()
    hub.mkdir()
    artifacts = write_reports_v2(
        merges_dir=out, hub=hub,
        repo_summaries=[{"name": "fixture", "root": root, "path": str(root),
                         "files": files, "source_files": files}],
        detail="max", mode="gesamt", max_bytes=1_000_000,
        plan_only=False, code_only=False, extras=MockExtras(), output_mode="dual",
        generator_info=make_generator_info(),
    )
    assert artifacts.bundle_manifest is not None
    manifest = json.loads(artifacts.bundle_manifest.read_text(encoding="utf-8"))
    return root, commit, artifacts, manifest


def role_record(manifest, role="relationship_projection_json"):
    return next(row for row in manifest["artifacts"] if row["role"] == role)


def test_publication_registers_verified_projection_and_remains_readable_without_checkout(tmp_path):
    root, commit, artifacts, manifest = published_bundle(tmp_path)
    record = role_record(manifest)
    projection_path = artifacts.bundle_manifest.parent / record["path"]
    raw = projection_path.read_bytes()
    projection = json.loads(raw)
    assert artifacts.relationship_projection == projection_path
    assert projection_path in artifacts.get_all_paths()
    assert record["bytes"] == len(raw)
    assert record["sha256"] == hashlib.sha256(raw).hexdigest()
    assert record["contract"] == {"id": "relationship_projection", "version": "v1"}
    assert record["interpretation"] == {"mode": "contract"}
    assert record["authority"] == "navigation_index"
    assert record["canonicality"] == "derived"
    assert record["risk_class"] == "navigation"
    assert record["regenerable"] is True
    assert record["staleness_sensitive"] is True
    assert projection["run_id"] == manifest["run_id"]
    assert projection["canonical_dump_index_sha256"] == role_record(manifest, "dump_index_json")["sha256"]
    contracts = Path(__file__).parents[1] / "contracts"
    for version in ("v1", "v2"):
        # Both manifest versions share the additive artifact-role contract.
        schema = json.loads((contracts / f"bundle-manifest.{version}.schema.json").read_text())
        artifact_schema = schema["properties"]["artifacts"]["items"]
        jsonschema.validate(record, artifact_schema)

    result = read_structure_neighborhood(artifacts.bundle_manifest, target_id="file:README.md")
    assert result["status"] == "available"
    identity = result["bundle_identity"]
    assert identity["source_commit"] == commit
    assert identity["source_commit_binding"] == "unique"
    assert identity["manifest_sha256"] == hashlib.sha256(artifacts.bundle_manifest.read_bytes()).hexdigest()
    assert identity["generator_commit"] == manifest["generator"]["runtime"]["git_commit"]
    assert any(edge["relation"] == "references" and edge["dst"] == "file:pkg/core.py"
               and edge["evidence_level"] == "S1" for edge in result["outgoing"])
    shutil.rmtree(root)
    repeated = read_structure_neighborhood(artifacts.bundle_manifest, target_id="file:README.md")
    assert repeated == result
    assert repeated["implicit_refresh"] is False


def test_published_projection_keeps_real_language_relations_and_s0(tmp_path):
    _, _, artifacts, manifest = published_bundle(tmp_path)
    projection = json.loads(artifacts.relationship_projection.read_text())
    edges = projection["edges"]
    assert any(edge["src"] == "file:default.nix" and edge["dst"] == "file:config.nix"
               and edge["evidence_level"] == "S1" for edge in edges)
    assert any(edge["src"] == "file:web/main.mjs" and edge["dst"] == "file:web/value.mjs"
               and edge["evidence_level"] == "S1" for edge in edges)
    assert any(edge["src"] == "file:schemas/use.json" and edge["dst"] == "file:schemas/core.json"
               and edge["evidence_level"] == "S1" for edge in edges)
    assert any(edge["src"] == "file:.github/workflows/ci.yml"
               and edge["dst"] == "file:.github/actions/local/action.yml"
               and edge["evidence_level"] == "S1" for edge in edges)
    assert not any("not-a-real-action" in edge["dst"] for edge in edges)
    calls = read_structure_neighborhood(
        artifacts.bundle_manifest, target_id="py:pkg:core.py:function:work",
    )
    assert any(edge["relation"] == "calls" and edge["src"] == "py:pkg:use.py:function:run"
               and edge["evidence_level"] == "S1" for edge in calls["incoming"])
    uncertain = read_structure_neighborhood(
        artifacts.bundle_manifest, target_id="py:pkg:core.py:function:dynamic",
    )
    assert uncertain["unresolved_from_symbol"]
    assert all(edge["evidence_level"] == "S0" for edge in uncertain["unresolved_from_symbol"])
    assert "dynamic_call_resolution" in uncertain["does_not_establish"]
    assert uncertain["coverage"]


def test_cli_and_real_mcp_handler_read_the_published_role(tmp_path, capsys):
    from merger.repoground.cli.main import main
    from merger.repoground.cli.mcp_stdio import RepoGroundMcpStdioServer
    from merger.repoground.tests.test_mcp_stdio import _initialize

    _, commit, artifacts, _ = published_bundle(tmp_path)
    capsys.readouterr()
    assert main(["architecture", "--relationships", "--bundle-manifest",
                 str(artifacts.bundle_manifest), "--target-id", "file:README.md"]) == 0
    cli = json.loads(capsys.readouterr().out)
    assert cli["status"] == "available"
    assert cli["result"]["bundle_identity"]["source_commit"] == commit
    server = RepoGroundMcpStdioServer(bundle_root=artifacts.bundle_manifest)
    _initialize(server)
    response = server.handle_message({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "get_structure_neighborhood", "arguments": {
            "bundle_manifest": str(artifacts.bundle_manifest), "target_id": "file:README.md",
            "max_items": 5,
        }},
    })
    assert response["result"]["isError"] is False
    payload = response["result"]["structuredContent"]
    assert payload["tool"] == "get_structure_neighborhood"
    assert payload["status"] == "available"
    assert payload["result"]["bundle_identity"]["source_commit"] == commit
    assert payload["result"]["implicit_refresh"] is False
    assert "live_freshness" in payload
