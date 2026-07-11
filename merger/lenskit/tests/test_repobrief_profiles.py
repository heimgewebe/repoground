from merger.lenskit.core.repobrief_profiles import (
    ARTIFACT_ORDER,
    PROFILE_ARTIFACT_RULES,
    VALID_REQUIREMENTS,
    evaluate_profile,
    present_roles_from_manifest,
    profile_level,
    profile_names,
    profile_output_mode_plan,
    profile_policy,
)


def test_all_profiles_are_machine_readable_and_complete():
    assert set(profile_names()) == {
        "local-private",
        "agent-portable",
        "full-max",
        "pr-review",
        "security-export-review",
        "public-share",
        "ci-artifact",
    }
    for profile in profile_names():
        policy = profile_policy(profile)
        assert policy["profile"] == profile
        assert policy["generator_level"] == profile_level(profile)
        assert set(policy["artifact_rules"]) == set(ARTIFACT_ORDER)
        assert set(policy["artifact_rules"].values()).issubset(set(VALID_REQUIREMENTS))
        assert policy["valid_requirements"] == list(VALID_REQUIREMENTS)


def test_missing_required_artifacts_become_missing_required():
    evaluation = evaluate_profile(
        "agent-portable",
        {
            "canonical_md",
            "bundle_manifest",
            "agent_reading_pack",
            "citation_map_jsonl",
            "chunk_index_jsonl",
            "output_health",
            "post_emit_health",
            "bundle_surface_validation",
            "retrieval_eval_json",
        },
    )

    assert evaluation["status"] == "fail"
    assert evaluation["missing_required"] == ["export_safety_report"]
    artifact = next(a for a in evaluation["artifacts"] if a["role"] == "export_safety_report")
    assert artifact["requirement"] == "required"
    assert artifact["availability"] == "missing_required"


def test_not_applicable_and_profile_excluded_are_explicit():
    local_eval = evaluate_profile("local-private", set())
    pr_delta = next(a for a in local_eval["artifacts"] if a["role"] == "pr_delta_cards_jsonl")
    assert pr_delta["requirement"] == "not_applicable"
    assert pr_delta["availability"] == "not_applicable"

    public_absent = evaluate_profile("public-share", set())
    sqlite_absent = next(a for a in public_absent["artifacts"] if a["role"] == "sqlite_index")
    assert sqlite_absent["requirement"] == "profile_excluded"
    assert sqlite_absent["availability"] == "profile_excluded"

    public_present = evaluate_profile("public-share", {"sqlite_index"})
    sqlite_present = next(a for a in public_present["artifacts"] if a["role"] == "sqlite_index")
    assert public_present["status"] == "fail"
    assert public_present["profile_excluded_present"] == ["sqlite_index"]
    assert sqlite_present["availability"] == "profile_excluded_present"


def test_present_roles_from_manifest_reads_artifacts_and_links():
    manifest = {
        "artifacts": [
            {"role": "canonical_md", "path": "x.md"},
            {"role": "output_health", "path": "x.output_health.json"},
        ],
        "links": {
            "post_emit_health_path": "x.bundle_health.post.json",
            "bundle_surface_validation_path": "x.bundle_surface_validation.json",
        },
    }

    assert present_roles_from_manifest(manifest) == {
        "bundle_manifest",
        "canonical_md",
        "output_health",
        "post_emit_health",
        "bundle_surface_validation",
    }


def test_profile_rules_match_expected_high_signal_requirements():
    assert PROFILE_ARTIFACT_RULES["agent-portable"]["export_safety_report"] == "required"
    assert PROFILE_ARTIFACT_RULES["pr-review"]["pr_delta_cards_jsonl"] == "required"
    assert PROFILE_ARTIFACT_RULES["full-max"]["sqlite_index"] == "required"
    assert PROFILE_ARTIFACT_RULES["local-private"]["citation_map_jsonl"] == "optional"


def test_profile_output_mode_plan_is_machine_readable():
    public_default = profile_output_mode_plan("public-share")
    assert public_default["selected_output_mode"] == "archive"
    assert public_default["defaulted"] is True
    assert public_default["conflicts"] == []
    assert public_default["excluded_roles"] == ["sqlite_index", "python_symbol_index_json"]

    public_dual = profile_output_mode_plan("public-share", "dual")
    assert public_dual["selected_output_mode"] == "dual"
    assert public_dual["defaulted"] is False
    assert public_dual["conflicts"] == ["sqlite_index"]

    agent_default = profile_output_mode_plan("agent-portable")
    assert agent_default["selected_output_mode"] == "dual"
    assert agent_default["conflicts"] == []


def test_placeholder_for_availability_model_import():
    from merger.lenskit.core.repobrief_availability import AVAILABILITY_VALUES
    assert "missing_required" in AVAILABILITY_VALUES


def test_availability_model_required_and_freshness(tmp_path):
    import datetime
    import json
    from merger.lenskit.core.repobrief_availability import snapshot_availability_model
    data = {
        "created_at": "2026-07-06T10:00:00Z",
        "artifacts": [],
        "links": {},
        "capabilities": {"repobrief_profile": "agent-portable"},
        "snapshot_provenance": {"repositories": [{"provenance_status": "present", "git_commit": "a" * 40}]},
    }
    path = tmp_path / "bundle.manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    model = snapshot_availability_model(path, data, max_age_seconds=3600, as_of=datetime.datetime(2026, 7, 6, 10, 30, tzinfo=datetime.timezone.utc))
    canonical = next(a for a in model["artifacts"] if a["role"] == "canonical_md")
    assert canonical["availability"] == "missing_required"
    assert model["freshness"]["status"] == "fresh"


def test_availability_model_profile_excluded_and_not_applicable(tmp_path):
    import json
    from merger.lenskit.core.repobrief_availability import snapshot_availability_model
    data = {"created_at": "2026-07-06T10:00:00Z", "artifacts": [], "links": {}, "capabilities": {"repobrief_profile": "public-share"}}
    path = tmp_path / "bundle.manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    model = snapshot_availability_model(path, data)
    sqlite = next(a for a in model["artifacts"] if a["role"] == "sqlite_index")
    pr_delta = next(a for a in model["artifacts"] if a["role"] == "pr_delta_cards_jsonl")
    assert sqlite["availability"] == "profile_excluded"
    assert pr_delta["availability"] == "not_applicable"


def _write_graph_index(path, sha):
    import json
    path.write_text(json.dumps({
        "kind": "lenskit.architecture.graph_index",
        "version": "1.0",
        "run_id": "run-1",
        "canonical_dump_index_sha256": sha,
        "distances": {},
        "metrics": {
            "entrypoint_count": 0,
            "nodes_reachable": 0,
            "unreachable_nodes": 0,
        },
    }), encoding="utf-8")


def test_graph_availability_is_exposed_when_not_generated(tmp_path):
    import json
    from merger.lenskit.core.repobrief_availability import snapshot_availability_model

    data = {
        "created_at": "2026-07-06T10:00:00Z",
        "artifacts": [],
        "links": {},
        "capabilities": {"repobrief_profile": "agent-portable"},
    }
    path = tmp_path / "bundle.manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    graph = snapshot_availability_model(path, data)["graph_availability"]

    assert graph["kind"] == "repobrief.graph_availability"
    assert graph["status"] == "not_generated"
    assert graph["retrieval_eligible"] is False
    assert graph["stale_graph_must_not_influence_retrieval"] is True
    assert graph["degradation"]["degradation"] == "missing"
    assert graph["degradation"]["severity"] == "info"
    assert graph["degradation"]["graph_must_not_influence_retrieval"] is True
    assert "test_sufficiency" in graph["does_not_establish"]
    assert "runtime_reachability" in graph["does_not_establish"]
    assert "runtime_causality" in graph["does_not_establish"]
    assert "change_impact" in graph["does_not_establish"]


def test_graph_availability_reports_available_and_stale(tmp_path):
    import json
    from merger.lenskit.core.repobrief_availability import snapshot_availability_model

    graph_path = tmp_path / "x.architecture_graph.json"
    graph_path.write_text('{"kind":"placeholder"}', encoding="utf-8")
    graph_index = tmp_path / "x.graph_index.json"
    expected_sha = "a" * 64
    _write_graph_index(graph_index, expected_sha)
    data = {
        "created_at": "2026-07-06T10:00:00Z",
        "artifacts": [
            {"role": "architecture_graph_json", "path": graph_path.name},
            {"role": "graph_index_json", "path": graph_index.name},
        ],
        "links": {"canonical_dump_index_sha256": expected_sha},
        "capabilities": {"repobrief_profile": "agent-portable"},
    }
    path = tmp_path / "bundle.manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    graph = snapshot_availability_model(path, data)["graph_availability"]
    assert graph["status"] == "available"
    assert graph["graph_index"]["load_status"] == "ok"
    assert graph["retrieval_eligible"] is True
    assert graph["degradation"]["degradation"] == "none"
    assert graph["degradation"]["retrieval_eligible"] is True

    stale = dict(data)
    stale["links"] = {"canonical_dump_index_sha256": "b" * 64}
    stale_graph = snapshot_availability_model(path, stale)["graph_availability"]
    assert stale_graph["status"] == "stale"
    assert stale_graph["graph_index"]["load_status"] == "stale_or_mismatched"
    assert stale_graph["retrieval_eligible"] is False
    assert stale_graph["degradation"]["degradation"] == "stale"
    assert stale_graph["degradation"]["severity"] == "warn"
    assert stale_graph["degradation"]["graph_must_not_influence_retrieval"] is True


def test_graph_availability_reports_validation_unavailable_as_degraded(tmp_path, monkeypatch):
    import json
    from merger.lenskit.core import repobrief_availability as availability

    graph_path = tmp_path / "x.architecture_graph.json"
    graph_path.write_text('{"kind":"placeholder"}', encoding="utf-8")
    graph_index = tmp_path / "x.graph_index.json"
    graph_index.write_text('{"kind":"placeholder"}', encoding="utf-8")
    expected_sha = "a" * 64
    data = {
        "created_at": "2026-07-06T10:00:00Z",
        "artifacts": [
            {"role": "architecture_graph_json", "path": graph_path.name},
            {"role": "graph_index_json", "path": graph_index.name},
        ],
        "links": {"canonical_dump_index_sha256": expected_sha},
        "capabilities": {"repobrief_profile": "agent-portable"},
    }
    path = tmp_path / "bundle.manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(
        availability,
        "load_graph_index",
        lambda *_args, **_kwargs: {"status": "validation_unavailable", "graph": None},
    )

    graph = availability.snapshot_availability_model(path, data)["graph_availability"]

    assert graph["status"] == "validation_unavailable"
    assert graph["graph_index"]["load_status"] == "validation_unavailable"
    assert graph["retrieval_eligible"] is False
    assert graph["degradation"]["degradation"] == "degraded"
    assert graph["degradation"]["severity"] == "warn"
    assert graph["degradation"]["graph_must_not_influence_retrieval"] is True


def test_graph_availability_profile_excluded_for_public_share(tmp_path):
    import json
    from merger.lenskit.core.repobrief_availability import snapshot_availability_model

    data = {
        "created_at": "2026-07-06T10:00:00Z",
        "artifacts": [],
        "links": {},
        "capabilities": {"repobrief_profile": "public-share"},
    }
    path = tmp_path / "bundle.manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    graph = snapshot_availability_model(path, data)["graph_availability"]
    assert graph["status"] == "profile_excluded"
    assert graph["retrieval_eligible"] is False
    assert graph["degradation"]["degradation"] == "profile_excluded"
    assert graph["degradation"]["severity"] == "info"


def test_all_snapshot_profiles_have_explicit_export_semantics():
    from merger.lenskit.core.repobrief_profiles import (
        PROFILE_LEVELS,
        profile_export_semantics,
    )

    for profile in PROFILE_LEVELS:
        semantics = profile_export_semantics(profile)
        assert set(semantics) == {
            "agent_facing",
            "public_facing",
            "redaction_required",
            "post_emit_health_required",
            "agent_export_gate_required",
            "exportable",
        }
        assert semantics["exportable"] is True

    assert profile_export_semantics("full-max")["agent_facing"] is True
    assert profile_export_semantics("public-share")["public_facing"] is True
