from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import jsonschema

from merger.repoground.core import doctor
from merger.repoground.core.agent_impact_adapter import RepoGroundAgentImpactAdapter
from merger.repoground.core.ask_context import build_ask_context_pack
from merger.repoground.core.constants import ArtifactRole
from merger.repoground.core.language_structure_access import (
    _expected_record_id,
    load_language_structure_artifact,
)
from merger.repoground.core.merge import scan_repo, write_reports_v2
from merger.repoground.core.snapshot_profiles import (
    REQ_OPTIONAL,
    REQ_EXCLUDED,
    profile_excluded_roles,
    profile_policy,
)
from merger.repoground.tests._test_constants import make_generator_info


ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "merger" / "repoground" / "contracts"


class MockExtras:
    json_sidecar = True
    skip_md = False
    format = "markdown"
    augment_sidecar = False
    health = False
    organism_index = False
    fleet_panorama = False
    delta_reports = False
    heatmap = False
    language_structure = True


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        },
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _bundle(
    tmp_path: Path,
    *,
    language_structure: bool = True,
    dirty_source: bool = False,
):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "src" / "lib.rs").write_text(
        "use crate::config::Config;\n"
        "pub struct Runner {}\n"
        "fn helper() {}\n"
        "pub fn run() {\n"
        "    helper();\n"
        '    println!("ok");\n'
        "}\n",
        encoding="utf-8",
    )
    (repo / "scripts" / "deploy.sh").write_text(
        "#!/usr/bin/env bash\n"
        "prepare() {\n  printf ready\n}\n"
        "deploy() {\n  prepare\n}\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=RepoGround Test",
        "-c",
        "user.email=repoground@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    commit = _git(repo, "rev-parse", "HEAD")
    if dirty_source:
        (repo / "src" / "lib.rs").write_text(
            (repo / "src" / "lib.rs").read_text(encoding="utf-8") + "// uncommitted\n",
            encoding="utf-8",
        )

    out = tmp_path / "out"
    hub = tmp_path / "hub"
    out.mkdir()
    hub.mkdir()
    extras = MockExtras()
    extras.language_structure = language_structure
    artifacts = write_reports_v2(
        merges_dir=out,
        hub=hub,
        repo_summaries=[scan_repo(repo)],
        detail="test",
        mode="gesamt",
        max_bytes=10_000,
        plan_only=False,
        code_only=False,
        extras=extras,
        output_mode="dual",
        generator_info=make_generator_info(),
    )
    assert artifacts.bundle_manifest is not None
    if language_structure and not dirty_source:
        assert artifacts.language_structure is not None
    return repo, commit, artifacts


def _entry(manifest: dict, role: str) -> dict:
    return next(item for item in manifest["artifacts"] if item["role"] == role)


def test_bundle_emits_contract_bound_language_structure_and_access_is_fail_closed(
    tmp_path: Path,
) -> None:
    _repo, commit, artifacts = _bundle(tmp_path)
    manifest_path = artifacts.bundle_manifest
    assert manifest_path is not None
    language_path = artifacts.language_structure
    assert language_path is not None

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_schema = json.loads(
        (CONTRACTS / "bundle-manifest.v2.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(instance=manifest, schema=manifest_schema)
    entry = _entry(manifest, ArtifactRole.LANGUAGE_STRUCTURE_JSON.value)
    assert entry["contract"] == {"id": "language-structure", "version": "v1"}
    assert entry["interpretation"] == {"mode": "contract"}
    assert entry["authority"] == "navigation_index"
    assert entry["canonicality"] == "derived"
    assert entry["risk_class"] == "navigation"
    assert entry["regenerable"] is True
    assert entry["staleness_sensitive"] is True

    document = json.loads(language_path.read_text(encoding="utf-8"))
    language_schema = json.loads(
        (CONTRACTS / "language-structure.v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(instance=document, schema=language_schema)
    assert document["source"]["repository_commit"] == commit
    assert {record["language"] for record in document["records"]} == {"bash", "rust"}

    invalid_commit = json.loads(json.dumps(document))
    invalid_commit["source"]["repository_commit"] = "a" * 41
    assert not jsonschema.Draft7Validator(language_schema).is_valid(invalid_commit)

    invented_static_semantics = json.loads(json.dumps(document))
    static_record = next(
        record
        for record in invented_static_semantics["records"]
        if record["adapter"]["id"] != "rust-scip-structure"
    )
    static_record["record_type"] = "occurrence"
    static_record["relation"] = "reference"
    assert not jsonschema.Draft7Validator(language_schema).is_valid(
        invented_static_semantics
    )

    access = load_language_structure_artifact(manifest_path)
    assert access["status"] == "available"
    assert access["manifest_sha256"] == _sha(manifest_path)
    assert access["content_sha256"] == entry["sha256"]

    language_path.write_bytes(language_path.read_bytes() + b" ")
    blocked = load_language_structure_artifact(manifest_path)
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "language_structure_integrity_mismatch"


def test_bundle_language_structure_is_opt_in_and_refuses_dirty_commit_binding(
    tmp_path: Path,
) -> None:
    _repo, _commit, disabled = _bundle(
        tmp_path / "disabled",
        language_structure=False,
    )
    assert disabled.language_structure is None
    disabled_manifest = json.loads(disabled.bundle_manifest.read_text(encoding="utf-8"))
    assert not any(
        item["role"] == "language_structure_json"
        for item in disabled_manifest["artifacts"]
    )

    _repo, _commit, dirty = _bundle(
        tmp_path / "dirty",
        language_structure=True,
        dirty_source=True,
    )
    assert dirty.language_structure is None


def test_sidecar_record_provenance_must_match_manifest_even_with_updated_hash(
    tmp_path: Path,
) -> None:
    _repo, _commit, artifacts = _bundle(tmp_path)
    manifest_path = artifacts.bundle_manifest
    language_path = artifacts.language_structure
    assert manifest_path is not None
    assert language_path is not None
    document = json.loads(language_path.read_text(encoding="utf-8"))
    document["records"][0]["provenance"]["repository_commit"] = "d" * 40
    language_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = _entry(manifest, ArtifactRole.LANGUAGE_STRUCTURE_JSON.value)
    entry["bytes"] = language_path.stat().st_size
    entry["sha256"] = _sha(language_path)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    blocked = load_language_structure_artifact(manifest_path)

    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "language_structure_bundle_identity_mismatch"


def test_sidecar_consumer_rejects_semantically_invented_static_relation(
    tmp_path: Path,
) -> None:
    _repo, _commit, artifacts = _bundle(tmp_path)
    manifest_path = artifacts.bundle_manifest
    language_path = artifacts.language_structure
    assert manifest_path is not None
    assert language_path is not None
    document = json.loads(language_path.read_text(encoding="utf-8"))
    record = next(
        item
        for item in document["records"]
        if item["adapter"]["id"] != "rust-scip-structure"
    )
    record["record_type"] = "occurrence"
    record["relation"] = "reference"
    record["id"] = _expected_record_id(record)
    language_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = _entry(manifest, ArtifactRole.LANGUAGE_STRUCTURE_JSON.value)
    entry["bytes"] = language_path.stat().st_size
    entry["sha256"] = _sha(language_path)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    blocked = load_language_structure_artifact(manifest_path)

    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "language_structure_bundle_identity_mismatch"


def test_context_pack_composes_relevant_language_evidence_under_shared_budget(
    tmp_path: Path,
) -> None:
    _repo, _commit, artifacts = _bundle(tmp_path)
    manifest_path = artifacts.bundle_manifest
    assert manifest_path is not None

    pack = build_ask_context_pack(
        manifest_path,
        query="rust helper",
        task_profile="basic_repo_question",
        max_context_tokens=2000,
        max_answer_tokens=200,
        k=5,
    )

    jsonschema.validate(
        instance=pack,
        schema=json.loads(
            (CONTRACTS / "repobrief-ask-context-pack.v1.schema.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    language = pack["structured_evidence"]["language_structure"]
    records = language["evidence"]["records"]
    assert records
    assert all(record["language"] == "rust" for record in records)
    assert any(record["symbol"] == "helper" for record in records)
    assert any(
        hit["artifact_role"] == "language_structure_json"
        for hit in pack["retrieval_hits"]
    )
    language_hits = [
        hit
        for hit in pack["retrieval_hits"]
        if hit["artifact_role"] == "language_structure_json"
    ]
    assert all(hit["language"] == "rust" for hit in language_hits)
    assert all(hit["adapter"]["version"] == "1.0" for hit in language_hits)
    assert all(hit["repository_commit"] == _commit for hit in language_hits)
    assert all(hit["bundle_manifest"] == manifest_path.name for hit in language_hits)
    assert all(
        hit["bundle_manifest_sha256"] == _sha(manifest_path) for hit in language_hits
    )
    assert all(hit["evidence_level"] in {"S0", "S1"} for hit in language_hits)
    assert all(0 <= hit["confidence"] <= 1 for hit in language_hits)
    assert all(isinstance(hit["uncertainty"], list) for hit in language_hits)
    assert all(hit["source_range"]["start_line"] >= 1 for hit in language_hits)
    assert any(
        item["artifact_role"] == "language_structure_json"
        for item in pack["resolved_ranges"]
    )
    manifest_sha = _sha(manifest_path)
    for record in records:
        assert record["provenance"]["bundle_manifest_sha256"] == manifest_sha
        assert record["adapter"]["version"] == "1.0"
        assert record["evidence"]["level"] in {"S0", "S1"}
        assert 0.0 <= record["evidence"]["confidence"] <= 1.0
        assert "uncertainty" in record
    assert language["budget"]["used_bytes"] <= language["budget"]["hard_limit_bytes"]
    assert pack["budget"]["context_bytes_used"] <= pack["budget"]["max_context_bytes"]
    text_bytes = sum(
        item.get("text_excerpt_bytes", 0)
        for item in pack["resolved_ranges"]
        if item["artifact_role"] == "canonical_md"
    )
    assert pack["budget"]["context_bytes_used"] == (
        text_bytes + language["budget"]["used_bytes"]
    )
    assert pack["budget"]["unit"] == "utf8_bytes"
    assert pack["budget"]["byte_budget_is_hard"] is True


def test_agent_impact_adapter_projects_language_relations_and_ranges(
    tmp_path: Path,
) -> None:
    _repo, _commit, artifacts = _bundle(tmp_path)
    manifest_path = artifacts.bundle_manifest
    assert manifest_path is not None
    config = tmp_path / "adapter.json"
    config.write_text(
        json.dumps(
            {
                "kind": "repobrief.readonly_adapter_config",
                "version": "1.0",
                "allowed_roots": [str(manifest_path.parent)],
                "snapshots": [{"id": "fixture", "manifest": str(manifest_path)}],
            }
        ),
        encoding="utf-8",
    )
    adapter = RepoGroundAgentImpactAdapter.from_config(config)

    result = adapter.agent_impact_context(
        "fixture",
        changed_paths=["src/lib.rs"],
        mode="impact",
        max_items=20,
        include_query_context=False,
    )

    language_relations = [
        relation
        for relation in result["relations"]
        if relation.get("relation_kind") == "language_structure"
    ]
    assert language_relations
    assert any(relation["relation_type"] == "call" for relation in language_relations)
    assert all(relation["language"] == "rust" for relation in language_relations)
    assert all(
        relation["freshness"]["status"] == "coherent" for relation in language_relations
    )
    assert any(item.get("language") == "rust" for item in result["source_ranges"])
    assert result["composition"]["language_structure"]["status"] == "used"
    assert any(
        item.get("source") == "language_structure_json"
        for item in result["source_statuses"]
    )
    manifest_sha = _sha(manifest_path)
    assert any(
        item.get("provenance", {}).get("bundle_manifest_sha256") == manifest_sha
        for item in result["source_ranges"]
    )


def test_doctor_blocks_broken_optional_adapter_version_without_blocking_core(
    monkeypatch,
) -> None:
    rust_module = "merger.repoground.core.rust_structure_adapter"
    monkeypatch.setattr(
        doctor, "_module_available", lambda module: module == rust_module
    )
    monkeypatch.setattr(
        doctor.importlib,
        "import_module",
        lambda _module: SimpleNamespace(ADAPTER_VERSION="9.9"),
    )

    checks = doctor.check_optional_adapters()
    rust = next(check for check in checks if check["id"] == "adapter:rust_structure")
    assert rust["status"] == "blocked"
    assert rust["cause"] == "adapter_version_contract_mismatch"
    assert rust["evidence"]["adapter_version"] == "1.0"
    assert rust["evidence"]["observed_version"] == "9.9"
    assert rust["optional"] is True
    assert doctor._overall_status(checks) == "available"


def test_language_structure_stays_optional_and_is_excluded_from_public_share() -> None:
    assert (
        profile_policy("agent-portable")["artifact_rules"]["language_structure_json"]
        == REQ_OPTIONAL
    )
    assert (
        profile_policy("public-share")["artifact_rules"]["language_structure_json"]
        == REQ_EXCLUDED
    )
    assert "language_structure_json" in profile_excluded_roles("public-share")
