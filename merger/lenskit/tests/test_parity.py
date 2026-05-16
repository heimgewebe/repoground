from merger.lenskit.tests._test_constants import TEST_CONFIG_SHA256
import pytest
import json
from merger.lenskit.core.merge import scan_repo, write_reports_v2, ExtrasConfig, parse_human_size


def _evaluate_parity_gates(state):
    """Evaluate separated parity gates for content vs diagnostics."""
    content_parity_pass = all(
        [
            state["source_file_count_equal"],
            state["missing_source_paths_count"] == 0,
            state["source_sha256_equal"],
            state["source_chunk_coverage_equal"],
            state["fts_logically_equal"],
            state["fts_non_empty"],
        ]
    )

    diagnostic_parity_pass = content_parity_pass and all(
        [
            state["output_health_verdict_pass"],
            state["range_ref_resolution_status_ok"],
            state["retrieval_eval_json_manifested"],
            state["health_warnings_errors_empty"],
            state["manifest_hash_bytes_consistent"],
            state["citation_map_requirement_satisfied"],
        ]
    )

    return {
        "content_parity_pass": content_parity_pass,
        "diagnostic_parity_pass": diagnostic_parity_pass,
    }

@pytest.fixture
def golden_fixture(tmp_path):
    repo = tmp_path / "golden_repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "test.py").write_text("print('hello')", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "readme.md").write_text("# Readme", encoding="utf-8")
    # Minimal hidden file for implicit include_hidden check
    (repo / ".hidden_dir").mkdir()
    (repo / ".hidden_dir" / "hidden.txt").write_text("secret", encoding="utf-8")
    return repo

def _get_dump_index(output_dir):
    """Finds and loads the dump index JSON from the output directory."""
    candidates = list(output_dir.glob("*.dump_index.json"))
    if not candidates:
        return None
    # Return the newest dump index if multiple exist
    return max(candidates, key=lambda p: p.stat().st_mtime)

def run_rlens_fixture(repo_path, output_dir):
    """Mimic rlens (Service) execution logic using plain dict config."""
    # Service defaults (simulated)
    req = {
        "level": "max",
        "mode": "gesamt",
        "max_bytes": "0",
        "split_size": "25MB",
        "extras": "json_sidecar,augment_sidecar",
        "meta_density": "auto",
        "json_sidecar": True,
        "output_mode": "dual",
        "redact_secrets": False,
        "include_hidden": True
    }

    max_bytes = parse_human_size(req["max_bytes"])
    extras_config = ExtrasConfig.from_csv(req["extras"])[0]
    if req["json_sidecar"]:
        extras_config.json_sidecar = True

    summary = scan_repo(
        repo_path,
        None, # extensions
        None, # path_filter
        max_bytes,
        include_paths=None,
        calculate_md5=True,
        include_hidden=req["include_hidden"]
    )

    generator_info = {
        "name": "rlens",
        "version": "dev",
        "platform": "service"
    }

    generator_info["config_sha256"] = TEST_CONFIG_SHA256
    write_reports_v2(
        output_dir,
        repo_path.parent, # Hub
        [summary],
        req["level"],
        req["mode"],
        max_bytes,
        False, # plan_only
        False, # code_only
        parse_human_size(req["split_size"]),
        debug=False,
        path_filter=None,
        ext_filter=None,
        extras=extras_config,
        meta_density=req["meta_density"],
        output_mode=req["output_mode"],
        redact_secrets=req["redact_secrets"],
        generator_info=generator_info,
    )

def run_repolens_fixture(repo_path, output_dir):
    """Mimic repolens (CLI/Frontend) execution logic using local defaults."""
    # CLI defaults (simulated)
    level = "max"
    mode = "gesamt"
    max_bytes = 0
    split_size = parse_human_size("25MB")
    extras_str = "json_sidecar,augment_sidecar"
    meta_density = "auto"
    include_hidden = True
    output_mode = "dual"
    redact_secrets = False

    extras_config = ExtrasConfig.from_csv(extras_str)[0]
    extras_config.json_sidecar = True

    summary = scan_repo(
        repo_path,
        None,
        None,
        max_bytes,
        include_paths=None,
        calculate_md5=True,
        include_hidden=include_hidden
    )

    generator_info = {
        "name": "repolens",
        "platform": "cli"
    }

    generator_info["config_sha256"] = TEST_CONFIG_SHA256
    write_reports_v2(
        output_dir,
        repo_path.parent, # Hub
        [summary],
        level,
        mode,
        max_bytes,
        False, # plan_only
        False, # code_only
        split_size,
        debug=False,
        path_filter=None,
        ext_filter=None,
        extras=extras_config,
        meta_density=meta_density,
        output_mode=output_mode,
        redact_secrets=redact_secrets,
        generator_info=generator_info,
    )

def test_tool_parity_contract_invariants(golden_fixture, tmp_path):
    rlens_out = tmp_path / "rlens_out"
    repolens_out = tmp_path / "repolens_out"
    rlens_out.mkdir()
    repolens_out.mkdir()

    run_rlens_fixture(golden_fixture, rlens_out)
    run_repolens_fixture(golden_fixture, repolens_out)

    # 1. Canonical Entry Point: dump_index
    r_dump_path = _get_dump_index(rlens_out)
    p_dump_path = _get_dump_index(repolens_out)

    assert r_dump_path and r_dump_path.exists(), "rlens dump_index missing"
    assert p_dump_path and p_dump_path.exists(), "repolens dump_index missing"

    with open(r_dump_path) as f: r_dump = json.load(f)
    with open(p_dump_path) as f: p_dump = json.load(f)

    # Verify dump contract
    assert r_dump["contract"] == "dump-index"
    assert p_dump["contract"] == "dump-index"

    # 2. Check Artifacts existence via dump_index
    # We expect at least: canonical_md, index_sidecar_json, chunk_index_jsonl (since dual mode), architecture_summary
    required_artifacts = ["canonical_md", "index_sidecar_json", "architecture_summary", "chunk_index_jsonl"]

    def _verify_artifact(dump, key, tool_name, out_dir):
        assert key in dump["artifacts"], f"{tool_name} missing artifact {key} in dump_index"
        art = dump["artifacts"][key]
        assert art, f"{tool_name} artifact {key} entry is null"
        path = out_dir / art["path"]
        assert path.exists(), f"{tool_name} artifact {key} file missing: {path}"
        sha = art["sha256"]
        assert sha != "ERROR", f"{tool_name} artifact {key} sha256 is ERROR"
        assert len(sha) == 64, f"{tool_name} artifact {key} sha256 length invalid"
        try:
            int(sha, 16)
        except ValueError:
            pytest.fail(f"{tool_name} artifact {key} sha256 is not hex: {sha}")

    for key in required_artifacts:
        _verify_artifact(r_dump, key, "rlens", rlens_out)
        _verify_artifact(p_dump, key, "repolens", repolens_out)

    # 3. Parity on Sidecar Invariants
    r_sidecar_path = rlens_out / r_dump["artifacts"]["index_sidecar_json"]["path"]
    p_sidecar_path = repolens_out / p_dump["artifacts"]["index_sidecar_json"]["path"]

    with open(r_sidecar_path) as f: r_meta = json.load(f)["meta"]
    with open(p_sidecar_path) as f: p_meta = json.load(f)["meta"]

    # Contract invariants
    assert r_meta["contract"] == p_meta["contract"]
    assert r_meta["contract_version"] == p_meta["contract_version"]

    # Configuration parity (we invoked them similarly)
    assert r_meta["profile"] == p_meta["profile"]
    assert r_meta["total_files"] == p_meta["total_files"], "Total file count mismatch"

    # Feature parity (Subset check)
    r_features = set(r_meta.get("features", []))
    p_features = set(p_meta.get("features", []))

    required_features = {"semantic_chunk_fields"}
    # If architecture_summary feature flag exists, we might want to check it,
    # but based on prompt we just ensure required is subset
    assert required_features.issubset(r_features), f"rlens missing features: {required_features - r_features}"
    assert required_features.issubset(p_features), f"repolens missing features: {required_features - p_features}"

    # Allowed differences: Generator info
    assert r_meta["generator"]["name"] == "rlens"
    assert p_meta["generator"]["name"] == "repolens"
    assert r_meta["generator"]["platform"] == "service"
    assert p_meta["generator"]["platform"] == "cli"

    # 4. Chunk Index Contract
    r_chunk_path = rlens_out / r_dump["artifacts"]["chunk_index_jsonl"]["path"]
    p_chunk_path = repolens_out / p_dump["artifacts"]["chunk_index_jsonl"]["path"]

    with open(r_chunk_path) as f: r_chunks = [json.loads(line) for line in f]
    with open(p_chunk_path) as f: p_chunks = [json.loads(line) for line in f]

    assert len(r_chunks) > 0, "rlens chunks empty"
    assert len(p_chunks) > 0, "repolens chunks empty"

    # Relaxed chunk count check: only if versions match
    r_ver = r_meta.get("generator", {}).get("version")
    p_ver = p_meta.get("generator", {}).get("version")
    if r_ver and p_ver and r_ver == p_ver:
        assert len(r_chunks) == len(p_chunks), "Chunk count mismatch (same version)"

    # Verify fields (Contract v2)
    required_chunk_fields = ["chunk_id", "path", "sha256", "size", "start_byte", "end_byte"]
    semantic_fields = ["section", "layer", "artifact_type", "concepts"]

    # Check first chunk as sample
    c0 = r_chunks[0]
    for k in required_chunk_fields:
        assert k in c0, f"Missing standard chunk field {k}"

    # Check repolens sample too
    c1 = p_chunks[0]
    for k in required_chunk_fields:
        assert k in c1, f"Missing standard chunk field {k} (repolens)"

    # repo is optional but must be str if present
    if "repo" in c0:
        assert isinstance(c0["repo"], str), "repo field must be string"

    if "semantic_chunk_fields" in r_features:
        for k in semantic_fields:
            assert k in c0, f"Missing semantic chunk field {k}"

    # 5. Architecture Summary Markers
    r_arch_path = rlens_out / r_dump["artifacts"]["architecture_summary"]["path"]
    p_arch_path = repolens_out / p_dump["artifacts"]["architecture_summary"]["path"]

    r_arch_content = r_arch_path.read_text(encoding="utf-8")
    p_arch_content = p_arch_path.read_text(encoding="utf-8")

    # Robust markers
    assert "LAYER_DISTRIBUTION" in r_arch_content
    assert "LAYER_DISTRIBUTION" in p_arch_content
    assert "KEY_MODULES" in r_arch_content
    assert "TEST_COVERAGE_MAP" in r_arch_content

    assert "# Lenskit Architecture Snapshot" in r_arch_content


def test_content_parity_gate_can_pass_without_retrieval_eval_json():
    state = {
        "source_file_count_equal": True,
        "missing_source_paths_count": 0,
        "source_sha256_equal": True,
        "source_chunk_coverage_equal": True,
        "fts_logically_equal": True,
        "fts_non_empty": True,
        "output_health_verdict_pass": False,
        "range_ref_resolution_status_ok": False,
        "retrieval_eval_json_manifested": False,
        "health_warnings_errors_empty": False,
        "manifest_hash_bytes_consistent": True,
        "citation_map_requirement_satisfied": True,
    }

    gates = _evaluate_parity_gates(state)

    assert gates["content_parity_pass"] is True
    assert gates["diagnostic_parity_pass"] is False


def test_diagnostic_parity_gate_requires_diagnostic_artifacts_and_status():
    state = {
        "source_file_count_equal": True,
        "missing_source_paths_count": 0,
        "source_sha256_equal": True,
        "source_chunk_coverage_equal": True,
        "fts_logically_equal": True,
        "fts_non_empty": True,
        "output_health_verdict_pass": True,
        "range_ref_resolution_status_ok": True,
        "retrieval_eval_json_manifested": True,
        "health_warnings_errors_empty": True,
        "manifest_hash_bytes_consistent": True,
        "citation_map_requirement_satisfied": True,
    }

    gates = _evaluate_parity_gates(state)

    assert gates["content_parity_pass"] is True
    assert gates["diagnostic_parity_pass"] is True

    state["retrieval_eval_json_manifested"] = False
    gates_missing_eval = _evaluate_parity_gates(state)
    assert gates_missing_eval["diagnostic_parity_pass"] is False
