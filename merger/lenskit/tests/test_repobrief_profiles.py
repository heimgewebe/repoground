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
    assert public_default["excluded_roles"] == ["sqlite_index"]

    public_dual = profile_output_mode_plan("public-share", "dual")
    assert public_dual["selected_output_mode"] == "dual"
    assert public_dual["defaulted"] is False
    assert public_dual["conflicts"] == ["sqlite_index"]

    agent_default = profile_output_mode_plan("agent-portable")
    assert agent_default["selected_output_mode"] == "dual"
    assert agent_default["conflicts"] == []
