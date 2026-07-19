from merger.repoground.tests._test_constants import TEST_CONFIG_SHA256
import pytest
import json
from merger.repoground.core.merge import scan_repo, write_reports_v2, ExtrasConfig, parse_human_size
from merger.repoground.core.parity_gates import evaluate_parity_gates


@pytest.fixture
def golden_fixture(tmp_path):
    repo = tmp_path / "golden_repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "test.py").write_text("print('hello')", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "readme.md").write_text("# Readme", encoding="utf-8")
    (repo / ".hidden_dir").mkdir()
    (repo / ".hidden_dir" / "hidden.txt").write_text("secret", encoding="utf-8")
    return repo


def _get_dump_index(output_dir):
    candidates = list(output_dir.glob("*.dump_index.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate.stat().st_mtime)


def _write_frontend_fixture(repo_path, output_dir, *, platform: str, version: str | None) -> None:
    level = "max"
    mode = "gesamt"
    max_bytes = 0
    split_size = parse_human_size("25MB")
    extras_config = ExtrasConfig.from_csv("json_sidecar,augment_sidecar")[0]
    extras_config.json_sidecar = True
    summary = scan_repo(
        repo_path,
        None,
        None,
        max_bytes,
        include_paths=None,
        calculate_md5=True,
        include_hidden=True,
    )
    generator_info = {
        "name": "repoground",
        "platform": platform,
        "config_sha256": TEST_CONFIG_SHA256,
    }
    if version is not None:
        generator_info["version"] = version
    write_reports_v2(
        output_dir,
        repo_path.parent,
        [summary],
        level,
        mode,
        max_bytes,
        False,
        False,
        split_size,
        debug=False,
        path_filter=None,
        ext_filter=None,
        extras=extras_config,
        meta_density="auto",
        output_mode="dual",
        redact_secrets=False,
        generator_info=generator_info,
    )


def run_service_fixture(repo_path, output_dir):
    """Generate one bundle through the service configuration surface."""
    _write_frontend_fixture(repo_path, output_dir, platform="service", version="dev")


def run_cli_fixture(repo_path, output_dir):
    """Generate one bundle through the CLI configuration surface."""
    _write_frontend_fixture(repo_path, output_dir, platform="cli", version=None)


def _frontend_outputs(golden_fixture, tmp_path):
    service_out = tmp_path / "service_out"
    cli_out = tmp_path / "cli_out"
    service_out.mkdir()
    cli_out.mkdir()
    run_service_fixture(golden_fixture, service_out)
    run_cli_fixture(golden_fixture, cli_out)
    return service_out, cli_out


def test_tool_parity_contract_invariants(golden_fixture, tmp_path):
    service_out, cli_out = _frontend_outputs(golden_fixture, tmp_path)
    service_dump_path = _get_dump_index(service_out)
    cli_dump_path = _get_dump_index(cli_out)
    assert service_dump_path and service_dump_path.exists(), "service dump_index missing"
    assert cli_dump_path and cli_dump_path.exists(), "CLI dump_index missing"
    service_dump = json.loads(service_dump_path.read_text(encoding="utf-8"))
    cli_dump = json.loads(cli_dump_path.read_text(encoding="utf-8"))
    assert service_dump["contract"] == "dump-index"
    assert cli_dump["contract"] == "dump-index"

    required_artifacts = [
        "canonical_md",
        "index_sidecar_json",
        "architecture_summary",
        "chunk_index_jsonl",
    ]

    def _verify_artifact(dump, key, surface, out_dir):
        assert key in dump["artifacts"], f"{surface} missing artifact {key}"
        artifact = dump["artifacts"][key]
        assert artifact, f"{surface} artifact {key} entry is null"
        path = out_dir / artifact["path"]
        assert path.exists(), f"{surface} artifact {key} missing: {path}"
        sha256 = artifact["sha256"]
        assert len(sha256) == 64
        int(sha256, 16)

    for key in required_artifacts:
        _verify_artifact(service_dump, key, "service", service_out)
        _verify_artifact(cli_dump, key, "CLI", cli_out)

    service_sidecar = service_out / service_dump["artifacts"]["index_sidecar_json"]["path"]
    cli_sidecar = cli_out / cli_dump["artifacts"]["index_sidecar_json"]["path"]
    service_meta = json.loads(service_sidecar.read_text(encoding="utf-8"))["meta"]
    cli_meta = json.loads(cli_sidecar.read_text(encoding="utf-8"))["meta"]
    assert service_meta["contract"] == cli_meta["contract"]
    assert service_meta["contract_version"] == cli_meta["contract_version"]
    assert service_meta["profile"] == cli_meta["profile"]
    assert service_meta["total_files"] == cli_meta["total_files"]
    required_features = {"semantic_chunk_fields"}
    service_features = set(service_meta.get("features", []))
    cli_features = set(cli_meta.get("features", []))
    assert required_features.issubset(service_features)
    assert required_features.issubset(cli_features)
    assert service_meta["generator"]["name"] == "repoground"
    assert cli_meta["generator"]["name"] == "repoground"
    assert service_meta["generator"]["platform"] == "service"
    assert cli_meta["generator"]["platform"] == "cli"

    service_chunks_path = service_out / service_dump["artifacts"]["chunk_index_jsonl"]["path"]
    cli_chunks_path = cli_out / cli_dump["artifacts"]["chunk_index_jsonl"]["path"]
    service_chunks = [json.loads(line) for line in service_chunks_path.read_text(encoding="utf-8").splitlines()]
    cli_chunks = [json.loads(line) for line in cli_chunks_path.read_text(encoding="utf-8").splitlines()]
    assert service_chunks
    assert cli_chunks
    required_chunk_fields = ["chunk_id", "path", "sha256", "size", "start_byte", "end_byte"]
    semantic_fields = ["section", "layer", "artifact_type", "concepts"]
    for key in required_chunk_fields:
        assert key in service_chunks[0]
        assert key in cli_chunks[0]
    for key in semantic_fields:
        assert key in service_chunks[0]
    service_architecture = service_out / service_dump["artifacts"]["architecture_summary"]["path"]
    cli_architecture = cli_out / cli_dump["artifacts"]["architecture_summary"]["path"]
    service_text = service_architecture.read_text(encoding="utf-8")
    cli_text = cli_architecture.read_text(encoding="utf-8")
    for marker in ("LAYER_DISTRIBUTION", "KEY_MODULES", "TEST_COVERAGE_MAP"):
        assert marker in service_text
        assert marker in cli_text
    assert "# RepoGround Architecture Snapshot" in service_text


def _find_bundle_manifest(output_dir):
    candidates = sorted(output_dir.glob("*.bundle.manifest.json"))
    assert len(candidates) == 1, (
        f"expected exactly one bundle manifest in {output_dir}, found {len(candidates)}"
    )
    return candidates[0]


def test_e2e_service_cli_reach_diagnostic_parity(golden_fixture, tmp_path):
    """The service and CLI surfaces reach diagnostic parity on one source."""
    from merger.repoground.core.parity_state import build_parity_state

    service_out, cli_out = _frontend_outputs(golden_fixture, tmp_path)
    built = build_parity_state(
        _find_bundle_manifest(service_out),
        _find_bundle_manifest(cli_out),
    )
    gates = evaluate_parity_gates(built.state)
    assert gates.content_parity_pass is True, gates.content_reasons
    assert gates.diagnostic_parity_pass is True, gates.diagnostic_reasons
    for role in ("citation_map_jsonl", "retrieval_eval_json", "output_health", "sqlite_index"):
        assert role in built.compared_artifacts
    assert built.left_only_artifacts == []
    assert built.right_only_artifacts == []


def test_e2e_parity_enforce_cli_on_real_bundles(golden_fixture, tmp_path, capsys):
    """The parity command enforces real service/CLI bundle equivalence."""
    from merger.repoground.cli.main import main

    service_out, cli_out = _frontend_outputs(golden_fixture, tmp_path)
    left = _find_bundle_manifest(service_out)
    right = _find_bundle_manifest(cli_out)
    rc = main(["parity", "enforce", str(left), str(right), "--require", "diagnostic", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0, payload
    assert payload["required_level"] == "diagnostic"
    assert payload["enforced_pass"] is True
    rc = main(["parity", "enforce", str(left), str(right), "--require", "content", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0, payload
    assert payload["enforced_pass"] is True


def test_content_parity_gate_can_pass_without_retrieval_eval_json():
    state = {
        "source_paths_equal": True,
        "source_sha256_equal": True,
        "source_chunk_coverage_equal": True,
        "fts_logically_equal": True,
        "fts_non_empty": True,  # tracked but not evaluated for content_parity_pass
        "output_health_verdict_pass": False,
        "range_ref_resolution_ok": False,
        "no_health_errors": False,
        "no_health_warnings": False,
        "manifest_hash_bytes_consistent": True,
        # retrieval_eval_json_expected absent → not required for diagnostic
    }

    gates = evaluate_parity_gates(state)

    assert gates.content_parity_pass is True
    assert gates.diagnostic_parity_pass is False


def test_content_parity_allows_equal_empty_fts():
    """Two frontends producing identically empty FTS still satisfy content parity.
    FTS non-emptiness is a diagnostic/retrieval-capability condition, not equality.
    """
    state = {
        "source_paths_equal": True,
        "source_sha256_equal": True,
        "source_chunk_coverage_equal": True,
        "fts_logically_equal": True,
        "fts_non_empty": False,
        "fts_non_empty_expected": False,  # not required → content parity unaffected
        "output_health_verdict_pass": False,
        "range_ref_resolution_ok": False,
        "no_health_errors": False,
        "no_health_warnings": False,
        "manifest_hash_bytes_consistent": True,
    }

    gates = evaluate_parity_gates(state)

    assert gates.content_parity_pass is True
    assert gates.diagnostic_parity_pass is False


def test_diagnostic_parity_gate_requires_diagnostic_artifacts_and_status():
    state = {
        "source_paths_equal": True,
        "source_sha256_equal": True,
        "source_chunk_coverage_equal": True,
        "fts_logically_equal": True,
        "fts_non_empty": True,  # tracked by caller; not evaluated in content gate
        "output_health_verdict_pass": True,
        "range_ref_resolution_ok": True,
        "no_health_errors": True,
        "no_health_warnings": True,
        "manifest_hash_bytes_consistent": True,
        "retrieval_eval_json_expected": True,
        "retrieval_eval_json_manifested": True,
        "citation_map_jsonl_expected": True,
        "citation_map_jsonl_valid": True,
    }

    gates = evaluate_parity_gates(state)

    assert gates.content_parity_pass is True
    assert gates.diagnostic_parity_pass is True

    state["retrieval_eval_json_manifested"] = False
    gates_missing_eval = evaluate_parity_gates(state)
    assert gates_missing_eval.diagnostic_parity_pass is False


def test_diagnostic_parity_fails_when_content_fails():
    state = {
        "source_paths_equal": False,  # content fails
        "source_sha256_equal": True,
        "source_chunk_coverage_equal": True,
        "fts_logically_equal": True,
        "output_health_verdict_pass": True,
        "range_ref_resolution_ok": True,
        "no_health_errors": True,
        "no_health_warnings": True,
        "manifest_hash_bytes_consistent": True,
    }

    gates = evaluate_parity_gates(state)

    assert gates.content_parity_pass is False
    assert gates.diagnostic_parity_pass is False
    assert any("content_parity_pass" in r for r in gates.diagnostic_reasons)


def test_diagnostic_parity_conditional_not_required_when_not_expected():
    """Diagnostic parity passes when conditional artifacts are absent but not expected."""
    state = {
        "source_paths_equal": True,
        "source_sha256_equal": True,
        "source_chunk_coverage_equal": True,
        "fts_logically_equal": True,
        "output_health_verdict_pass": True,
        "range_ref_resolution_ok": True,
        "no_health_errors": True,
        "no_health_warnings": True,
        "manifest_hash_bytes_consistent": True,
        # retrieval_eval_json_expected absent → not required
        # citation_map_jsonl_expected absent → not required
        # fts_non_empty_expected absent → not required
    }

    gates = evaluate_parity_gates(state)

    assert gates.content_parity_pass is True
    assert gates.diagnostic_parity_pass is True


def test_diagnostic_parity_fails_when_fts_non_empty_expected_but_absent():
    state = {
        "source_paths_equal": True,
        "source_sha256_equal": True,
        "source_chunk_coverage_equal": True,
        "fts_logically_equal": True,
        "output_health_verdict_pass": True,
        "range_ref_resolution_ok": True,
        "no_health_errors": True,
        "no_health_warnings": True,
        "manifest_hash_bytes_consistent": True,
        "fts_non_empty_expected": True,
        "fts_non_empty": False,
    }

    gates = evaluate_parity_gates(state)

    assert gates.content_parity_pass is True
    assert gates.diagnostic_parity_pass is False
    assert any("fts_non_empty" in r for r in gates.diagnostic_reasons)


def test_diagnostic_parity_fails_when_retrieval_eval_expected_but_not_manifested():
    """A stray retrieval_eval_json file that is not in the bundle manifest
    must not satisfy the diagnostic gate.  Only manifested=True counts.
    """
    state = {
        "source_paths_equal": True,
        "source_sha256_equal": True,
        "source_chunk_coverage_equal": True,
        "fts_logically_equal": True,
        "output_health_verdict_pass": True,
        "range_ref_resolution_ok": True,
        "no_health_errors": True,
        "no_health_warnings": True,
        "manifest_hash_bytes_consistent": True,
        "retrieval_eval_json_expected": True,
        "retrieval_eval_json_present": True,   # stray file exists ...
        "retrieval_eval_json_manifested": False,  # ... but not in bundle manifest
    }

    gates = evaluate_parity_gates(state)

    assert gates.content_parity_pass is True
    assert gates.diagnostic_parity_pass is False
    assert any("retrieval_eval_json_manifested" in r for r in gates.diagnostic_reasons)


def test_diagnostic_parity_fails_when_citation_map_expected_but_invalid():
    state = {
        "source_paths_equal": True,
        "source_sha256_equal": True,
        "source_chunk_coverage_equal": True,
        "fts_logically_equal": True,
        "output_health_verdict_pass": True,
        "range_ref_resolution_ok": True,
        "no_health_errors": True,
        "no_health_warnings": True,
        "manifest_hash_bytes_consistent": True,
        "citation_map_jsonl_expected": True,
        "citation_map_jsonl_valid": False,
    }

    gates = evaluate_parity_gates(state)

    assert gates.content_parity_pass is True
    assert gates.diagnostic_parity_pass is False
    assert any("citation_map_jsonl_valid" in r for r in gates.diagnostic_reasons)


def test_expected_flags_must_be_bool():
    """A non-bool *_expected flag is a configuration error and must fail
    the diagnostic gate (fail-closed), not silently skip the check.
    """
    _base = {
        "source_paths_equal": True,
        "source_sha256_equal": True,
        "source_chunk_coverage_equal": True,
        "fts_logically_equal": True,
        "output_health_verdict_pass": True,
        "range_ref_resolution_ok": True,
        "no_health_errors": True,
        "no_health_warnings": True,
        "manifest_hash_bytes_consistent": True,
    }

    # String "true" for retrieval_eval_json_expected
    state = {**_base, "retrieval_eval_json_expected": "true", "retrieval_eval_json_manifested": False}
    gates = evaluate_parity_gates(state)
    assert gates.diagnostic_parity_pass is False
    assert any("retrieval_eval_json_expected" in r for r in gates.diagnostic_reasons)

    # Integer 1 for citation_map_jsonl_expected
    state2 = {**_base, "citation_map_jsonl_expected": 1, "citation_map_jsonl_valid": False}
    gates2 = evaluate_parity_gates(state2)
    assert gates2.diagnostic_parity_pass is False
    assert any("citation_map_jsonl_expected" in r for r in gates2.diagnostic_reasons)

    # String "false" for fts_non_empty_expected
    state3 = {**_base, "fts_non_empty_expected": "false", "fts_non_empty": False}
    gates3 = evaluate_parity_gates(state3)
    assert gates3.diagnostic_parity_pass is False
    assert any("fts_non_empty_expected" in r for r in gates3.diagnostic_reasons)


def test_parity_gates_require_strict_boolean_true():
    """Truthy non-bool values like "true" or 1 must not satisfy a gate field.

    _is_true() uses ``is True`` so strings, integers and other truthy objects
    are rejected.  This prevents silent failures when state dicts come from
    JSON deserialisation or CLI argument parsing.
    """
    state = {
        "source_paths_equal": "true",  # truthy string — must not count
        "source_sha256_equal": True,
        "source_chunk_coverage_equal": True,
        "fts_logically_equal": True,
        "output_health_verdict_pass": True,
        "range_ref_resolution_ok": True,
        "no_health_errors": True,
        "no_health_warnings": True,
        "manifest_hash_bytes_consistent": True,
    }

    gates = evaluate_parity_gates(state)

    assert gates.content_parity_pass is False
    assert any("source_paths_equal" in r for r in gates.content_reasons)

    # Integer 1 is also truthy but not bool True
    state["source_paths_equal"] = 1
    gates_int = evaluate_parity_gates(state)
    assert gates_int.content_parity_pass is False
