import json
import pytest

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

@pytest.fixture
def ac_pr_review(tmp_path):
    p = tmp_path / "answer-compliance.json"
    p.write_text(json.dumps({
        "kind": "lenskit.answer_compliance",
        "version": "1.0",
        "task_profile": "pr_review",
        "declared_artifacts": [
            "agent_reading_pack",
            "canonical_md",
            "citation_map_jsonl",
            "post_emit_health"
        ],
        "declared_citations": [],
        "declared_ranges": [],
        "unread_required_artifacts": [],
        "unread_recommended_artifacts": [],
        "epistemic_gaps": [],
        "does_not_establish": DOES_NOT_ESTABLISH
    }), encoding="utf-8")
    return p


def test_cli_required_stdout(capsys):
    rc = main([
        "agent-consumption", "required",
        "--task-profile", "basic_repo_question",
        "--available-roles", "agent_reading_pack,canonical_md,citation_map_jsonl"
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["task_profile"] == "basic_repo_question"
    assert out["status"] in ("pass", "warn")


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
    assert out["status"] in ("pass", "warn")
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
    rr_file.write_text(json.dumps({
        "task_profile": "pr_review",
        "required": ["canonical_md"],
        "recommended": ["citation_map_jsonl"],
        "status": "warn"
    }))
    ac_file = tmp_path / "ac.json"
    ac_file.write_text(json.dumps({
        "task_profile": "pr_review",
        "declared_artifacts": ["canonical_md"],
        "does_not_establish": DOES_NOT_ESTABLISH
    }))
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
    rr_file.write_text(json.dumps({
        "task_profile": "pr_review",
        "required": ["canonical_md"],
        "recommended": ["citation_map_jsonl"],
        "status": "warn"
    }))
    ac_file = tmp_path / "ac.json"
    ac_file.write_text(json.dumps({
        "task_profile": "pr_review",
        "declared_artifacts": ["canonical_md"],
        "does_not_establish": DOES_NOT_ESTABLISH
    }))
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
    rr_file.write_text(json.dumps({
        "task_profile": "pr_review",
        "required": ["canonical_md"],
        "recommended": [],
        "status": "fail"
    }))
    ac_file = tmp_path / "ac.json"
    ac_file.write_text(json.dumps({
        "task_profile": "pr_review",
        "declared_artifacts": [], 
        "does_not_establish": DOES_NOT_ESTABLISH
    }))
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
    rr_file.write_text(json.dumps({
        "task_profile": "pr_review",
        "required": ["canonical_md"],
        "recommended": [],
        "status": "pass"
    }))
    ac_file = tmp_path / "ac.json"
    ac_file.write_text(json.dumps({
        "task_profile": "pr_review",
        "declared_artifacts": ["canonical_md"],
        "does_not_establish": DOES_NOT_ESTABLISH
    }))
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
    rr_file.write_text("{invalid")
    ac_file = tmp_path / "ac.json"
    ac_file.write_text("{}")
    
    rc = main([
        "agent-consumption", "validate-trace",
        "--required-reading", str(rr_file),
        "--answer-compliance", str(ac_file)
    ])
    assert rc == 2
    assert "Invalid JSON" in capsys.readouterr().err


def test_cli_roles_file_list(tmp_path, capsys):
    roles_file = tmp_path / "roles.json"
    roles_file.write_text(json.dumps([
        "agent_reading_pack",
        "canonical_md",
        "citation_map_jsonl",
    ]), encoding="utf-8")
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
    roles_file.write_text(json.dumps({
        "available_roles": [
            "agent_reading_pack",
            "canonical_md",
            "citation_map_jsonl",
        ]
    }), encoding="utf-8")
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
    rr_file.write_text(json.dumps({
        "task_profile": "pr_review",
        "required": ["canonical_md"],
        "recommended": [],
        "status": "pass"
    }))
    ac_file = tmp_path / "ac.json"
    ac_file.write_text(json.dumps({
        "task_profile": "pr_review",
        "declared_artifacts": ["canonical_md", "mystery_from_file", "mystery_from_csv"],
        "does_not_establish": DOES_NOT_ESTABLISH
    }))
    roles_file = tmp_path / "roles.json"
    roles_file.write_text('["mystery_from_file"]')
    
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
    rr_file.write_text(json.dumps({
        "required": [],
        "recommended": [],
        "status": "pass",
    }), encoding="utf-8")
    ac_file = tmp_path / "ac.json"
    ac_file.write_text(json.dumps({
        "declared_artifacts": [],
        "does_not_establish": DOES_NOT_ESTABLISH,
    }), encoding="utf-8")
    
    rc = main([
        "agent-consumption", "validate-trace",
        "--required-reading", str(rr_file),
        "--answer-compliance", str(ac_file)
    ])
    assert rc == 2
    assert "Required reading missing required keys" in capsys.readouterr().err

    rr_file.write_text(json.dumps({
        "task_profile": "pr_review",
        "required": [],
        "recommended": [],
        "status": "pass",
    }), encoding="utf-8")
    ac_file.write_text(json.dumps({
        "declared_artifacts": [],
        "does_not_establish": DOES_NOT_ESTABLISH,
    }), encoding="utf-8")
    
    rc = main([
        "agent-consumption", "validate-trace",
        "--required-reading", str(rr_file),
        "--answer-compliance", str(ac_file)
    ])
    assert rc == 2
    assert "Answer compliance missing required keys" in capsys.readouterr().err
