import json
from merger.lenskit.cli.main import main


DOES_NOT_ESTABLISH = [
    "actual_reading_proven",
    "answer_correct",
    "repo_understood",
    "all_relevant_context_used",
    "claims_true",
    "test_sufficiency",
    "regression_absence",
    "runtime_behavior",
    "forensic_ready"
]


def test_cli_required_stdout(capsys):
    rc = main([
        "agent-consumption", "required",
        "--task-profile", "basic_repo_question",
        "--available-roles", "agent_reading_pack,canonical_md,citation_map_jsonl"
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["task_profile"] == "basic_repo_question"
    assert out["status"] == "pass"
    assert out["missing_required"] == []
    assert out["missing_recommended"] == []


def test_cli_required_out_file(tmp_path, capsys):
    out_file = tmp_path / "out.json"
    rc = main([
        "agent-consumption", "required",
        "--task-profile", "basic_repo_question",
        "--available-roles", "agent_reading_pack,canonical_md,citation_map_jsonl",
        "--output", str(out_file)
    ])
    assert rc == 0
    assert out_file.exists()
    out = json.loads(out_file.read_text(encoding="utf-8"))
    assert out["task_profile"] == "basic_repo_question"
    assert out["status"] == "pass"
    assert out["missing_required"] == []
    assert out["missing_recommended"] == []
    assert capsys.readouterr().out == ""


def test_cli_required_missing_required(capsys):
    rc = main([
        "agent-consumption", "required",
        "--task-profile", "pr_review",
        "--available-roles", "agent_reading_pack"
    ])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "fail"
    assert out["required"]
    assert out["available_required"] == ["agent_reading_pack"]
    assert out["missing_required"]


def test_cli_required_unknown_profile(capsys):
    rc = main([
        "agent-consumption", "required",
        "--task-profile", "unknown_profile"
    ])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "not_applicable"


def test_cli_validate_trace_pass(tmp_path, capsys):
    rr_file = tmp_path / "rr.json"
    rr_data = {
        "task_profile": "pr_review",
        "required": ["agent_reading_pack", "canonical_md", "citation_map_jsonl", "post_emit_health"],
        "recommended": ["bundle_surface_validation", "claim_evidence_map_json"],
        "status": "pass"
    }
    rr_file.write_text(json.dumps(rr_data), encoding="utf-8")
    
    ac_file = tmp_path / "ac.json"
    ac_data = {
        "task_profile": "pr_review",
        "declared_artifacts": sorted(rr_data["required"] + rr_data["recommended"]),
        "does_not_establish": DOES_NOT_ESTABLISH
    }
    ac_file.write_text(json.dumps(ac_data), encoding="utf-8")

    capsys.readouterr() # clear

    rc = main([
        "agent-consumption", "validate-trace",
        "--required-reading", str(rr_file),
        "--answer-compliance", str(ac_file),
        "--available-roles", "agent_reading_pack,canonical_md,citation_map_jsonl,post_emit_health,bundle_surface_validation,claim_evidence_map_json"
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["status"] == "pass"


def test_cli_validate_trace_warn(tmp_path, capsys):
    rr_file = tmp_path / "rr.json"
    rr_data = {
        "task_profile": "pr_review",
        "required": ["canonical_md"],
        "recommended": ["citation_map_jsonl"],
        "status": "warn"
    }
    rr_file.write_text(json.dumps(rr_data), encoding="utf-8")
    ac_file = tmp_path / "ac.json"
    ac_data = {
        "task_profile": "pr_review",
        "declared_artifacts": ["canonical_md"],
        "does_not_establish": DOES_NOT_ESTABLISH
    }
    ac_file.write_text(json.dumps(ac_data), encoding="utf-8")
    rc = main([
        "agent-consumption", "validate-trace",
        "--required-reading", str(rr_file),
        "--answer-compliance", str(ac_file)
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "warn"


def test_cli_validate_trace_warn_strict(tmp_path, capsys):
    rr_file = tmp_path / "rr.json"
    rr_data = {
        "task_profile": "pr_review",
        "required": ["canonical_md"],
        "recommended": ["citation_map_jsonl"],
        "status": "warn"
    }
    rr_file.write_text(json.dumps(rr_data), encoding="utf-8")
    ac_file = tmp_path / "ac.json"
    ac_data = {
        "task_profile": "pr_review",
        "declared_artifacts": ["canonical_md"],
        "does_not_establish": DOES_NOT_ESTABLISH
    }
    ac_file.write_text(json.dumps(ac_data), encoding="utf-8")
    rc = main([
        "agent-consumption", "validate-trace",
        "--required-reading", str(rr_file),
        "--answer-compliance", str(ac_file),
        "--strict"
    ])
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "warn"
    assert rc == 1


def test_cli_validate_trace_fail(tmp_path, capsys):
    rr_file = tmp_path / "rr.json"
    rr_data = {
        "task_profile": "pr_review",
        "required": ["canonical_md"],
        "recommended": [],
        "status": "fail"
    }
    rr_file.write_text(json.dumps(rr_data), encoding="utf-8")
    ac_file = tmp_path / "ac.json"
    ac_data = {
        "task_profile": "pr_review",
        "declared_artifacts": [], 
        "does_not_establish": DOES_NOT_ESTABLISH
    }
    ac_file.write_text(json.dumps(ac_data), encoding="utf-8")
    rc = main([
        "agent-consumption", "validate-trace",
        "--required-reading", str(rr_file),
        "--answer-compliance", str(ac_file)
    ])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "fail"


def test_cli_validate_trace_out_file(tmp_path, capsys):
    rr_file = tmp_path / "rr.json"
    rr_data = {
        "task_profile": "pr_review",
        "required": ["canonical_md"],
        "recommended": [],
        "status": "pass"
    }
    rr_file.write_text(json.dumps(rr_data), encoding="utf-8")
    ac_file = tmp_path / "ac.json"
    ac_data = {
        "task_profile": "pr_review",
        "declared_artifacts": ["canonical_md"],
        "does_not_establish": DOES_NOT_ESTABLISH
    }
    ac_file.write_text(json.dumps(ac_data), encoding="utf-8")
    out_file = tmp_path / "trace.json"
    rc = main([
        "agent-consumption", "validate-trace",
        "--required-reading", str(rr_file),
        "--answer-compliance", str(ac_file),
        "--out", str(out_file)
    ])
    assert rc == 0
    assert out_file.exists()
    out = json.loads(out_file.read_text(encoding="utf-8"))
    assert out["status"] == "pass"
    assert capsys.readouterr().out == ""


def test_cli_missing_input_path(capsys):
    rc = main([
        "agent-consumption", "validate-trace",
        "--required-reading", "does_not_exist.json",
        "--answer-compliance", "does_not_exist2.json"
    ])
    assert rc == 2
    assert "Could not read" in capsys.readouterr().err


def test_cli_invalid_json(tmp_path, capsys):
    rr_file = tmp_path / "rr.json"
    rr_file.write_text("{invalid", encoding="utf-8")
    ac_file = tmp_path / "ac.json"
    ac_file.write_text("{}", encoding="utf-8")
    
    rc = main([
        "agent-consumption", "validate-trace",
        "--required-reading", str(rr_file),
        "--answer-compliance", str(ac_file)
    ])
    assert rc == 2
    assert "Invalid JSON" in capsys.readouterr().err


def test_cli_roles_file_list(tmp_path, capsys):
    roles_file = tmp_path / "roles.json"
    roles_data = [
        "agent_reading_pack",
        "canonical_md",
        "citation_map_jsonl",
    ]
    roles_file.write_text(json.dumps(roles_data), encoding="utf-8")
    rc = main([
        "agent-consumption", "required",
        "--task-profile", "basic_repo_question",
        "--available-roles-file", str(roles_file)
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pass"
    assert out["missing_required"] == []
    assert out["missing_recommended"] == []


def test_cli_roles_file_object(tmp_path, capsys):
    roles_file = tmp_path / "roles.json"
    roles_data = {
        "available_roles": [
            "agent_reading_pack",
            "canonical_md",
            "citation_map_jsonl",
        ]
    }
    roles_file.write_text(json.dumps(roles_data), encoding="utf-8")
    rc = main([
        "agent-consumption", "required",
        "--task-profile", "basic_repo_question",
        "--available-roles-file", str(roles_file)
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pass"
    assert out["missing_required"] == []
    assert out["missing_recommended"] == []


def test_cli_roles_union(tmp_path, capsys):
    roles_file = tmp_path / "roles.json"
    roles_file.write_text('["agent_reading_pack"]', encoding="utf-8")
    rc = main([
        "agent-consumption", "required",
        "--task-profile", "basic_repo_question",
        "--available-roles", "canonical_md,citation_map_jsonl",
        "--available-roles-file", str(roles_file)
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pass"
    assert out["missing_required"] == []
    assert out["missing_recommended"] == []


def test_cli_roles_union_validate_trace(tmp_path, capsys):
    rr_file = tmp_path / "rr.json"
    rr_data = {
        "task_profile": "pr_review",
        "required": ["canonical_md"],
        "recommended": [],
        "status": "pass"
    }
    rr_file.write_text(json.dumps(rr_data), encoding="utf-8")
    ac_file = tmp_path / "ac.json"
    ac_data = {
        "task_profile": "pr_review",
        "declared_artifacts": ["canonical_md", "mystery_from_file", "mystery_from_csv"],
        "does_not_establish": DOES_NOT_ESTABLISH
    }
    ac_file.write_text(json.dumps(ac_data), encoding="utf-8")
    roles_file = tmp_path / "roles.json"
    roles_file.write_text('["mystery_from_file"]', encoding="utf-8")
    
    rc = main([
        "agent-consumption", "validate-trace",
        "--required-reading", str(rr_file),
        "--answer-compliance", str(ac_file),
        "--available-roles", "mystery_from_csv",
        "--available-roles-file", str(roles_file)
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pass"
    assert out.get("unknown_declared_artifacts", []) == []


def test_cli_invalid_roles_file_shape(tmp_path, capsys):
    roles_file = tmp_path / "roles.json"
    roles_file.write_text(json.dumps("canonical_md"), encoding="utf-8")
    rc = main([
        "agent-consumption", "required",
        "--task-profile", "basic_repo_question",
        "--available-roles-file", str(roles_file)
    ])
    assert rc == 2
    assert "Invalid available roles file" in capsys.readouterr().err

    roles_file.write_text(json.dumps({"available_roles": "canonical_md"}), encoding="utf-8")
    rc = main([
        "agent-consumption", "required",
        "--task-profile", "basic_repo_question",
        "--available-roles-file", str(roles_file)
    ])
    assert rc == 2
    assert "Invalid available roles file" in capsys.readouterr().err


def test_cli_validate_trace_missing_shape(tmp_path, capsys):
    rr_file = tmp_path / "rr.json"
    rr_data = {
        "required": [],
        "recommended": [],
        "status": "pass",
    }
    rr_file.write_text(json.dumps(rr_data), encoding="utf-8")
    ac_file = tmp_path / "ac.json"
    ac_data = {
        "declared_artifacts": [],
        "does_not_establish": DOES_NOT_ESTABLISH,
    }
    ac_file.write_text(json.dumps(ac_data), encoding="utf-8")
    
    rc = main([
        "agent-consumption", "validate-trace",
        "--required-reading", str(rr_file),
        "--answer-compliance", str(ac_file)
    ])
    assert rc == 2
    assert "Required reading missing required keys" in capsys.readouterr().err

    rr_data = {
        "task_profile": "pr_review",
        "required": [],
        "recommended": [],
        "status": "pass",
    }
    rr_file.write_text(json.dumps(rr_data), encoding="utf-8")
    ac_data = {
        "declared_artifacts": [],
        "does_not_establish": DOES_NOT_ESTABLISH,
    }
    ac_file.write_text(json.dumps(ac_data), encoding="utf-8")
    
    rc = main([
        "agent-consumption", "validate-trace",
        "--required-reading", str(rr_file),
        "--answer-compliance", str(ac_file)
    ])
    assert rc == 2
    assert "Answer compliance missing required keys" in capsys.readouterr().err


def test_cli_preflight_stdout_from_bundle_manifest(tmp_path, capsys):
    manifest = tmp_path / "bundle.manifest.json"
    manifest.write_text(json.dumps({
        "artifacts": [
            {"role": "agent_reading_pack"},
            {"role": "canonical_md"},
            {"role": "citation_map_jsonl"},
            {"role": "claim_evidence_map_json"},
        ],
        "links": {
            "post_emit_health_path": "demo.post_emit_health.json",
            "bundle_surface_validation_path": "demo.bundle_surface_validation.json",
        },
    }), encoding="utf-8")

    rc = main([
        "agent-consumption", "preflight",
        "--task-profile", "pr_review",
        "--bundle-manifest", str(manifest),
    ])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["kind"] == "lenskit.agent_consumption_preflight"
    assert out["status"] == "pass"
    assert out["required_reading"]["status"] == "pass"
    assert "post_emit_health" in out["available_roles"]
    assert "bundle_surface_validation" in out["available_roles"]
    assert out["agent_consumption_trace"] is None
    assert set(out["answer_compliance_template"]["declared_artifacts"]) == set(
        out["required_reading"]["required"] + out["required_reading"]["recommended"]
    )
    assert "repo_understood" in out["does_not_establish"]


def test_cli_preflight_validates_answer_compliance(tmp_path, capsys):
    ac_file = tmp_path / "answer-compliance.json"
    ac_file.write_text(json.dumps({
        "task_profile": "basic_repo_question",
        "declared_artifacts": ["agent_reading_pack", "canonical_md", "citation_map_jsonl"],
        "does_not_establish": DOES_NOT_ESTABLISH,
    }), encoding="utf-8")

    rc = main([
        "agent-consumption", "preflight",
        "--task-profile", "basic_repo_question",
        "--available-roles", "agent_reading_pack,canonical_md,citation_map_jsonl",
        "--answer-compliance", str(ac_file),
    ])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pass"
    assert out["agent_consumption_trace"]["status"] == "pass"
    assert out["agent_consumption_trace"]["declared_artifacts"] == [
        "agent_reading_pack", "canonical_md", "citation_map_jsonl"
    ]


def test_cli_preflight_warn_strict_exits_1(tmp_path, capsys):
    rc = main([
        "agent-consumption", "preflight",
        "--task-profile", "basic_repo_question",
        "--available-roles", "agent_reading_pack,canonical_md",
        "--strict",
    ])

    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "warn"
    assert out["required_reading"]["missing_recommended"] == ["citation_map_jsonl"]


def test_cli_preflight_invalid_manifest_shape(tmp_path, capsys):
    manifest = tmp_path / "bundle.manifest.json"
    manifest.write_text(json.dumps({"artifacts": {}}), encoding="utf-8")

    rc = main([
        "agent-consumption", "preflight",
        "--task-profile", "basic_repo_question",
        "--bundle-manifest", str(manifest),
    ])

    assert rc == 2
    assert "expected artifacts array" in capsys.readouterr().err
