"""Focused contract and size comparison tests for RepoGround compact vs full read responses."""
from __future__ import annotations

import json
from pathlib import Path

from merger.repoground.core import bundle_access, mcp_tools
from merger.repoground.core.availability import snapshot_freshness_model
from merger.repoground.core.response_projection import (
    COMPACT_PROJECTION,
    compact_availability,
    compact_freshness,
    compact_graph_availability,
    compact_mutation_boundary,
    compact_role_gaps,
    project_read_result,
)
from merger.repoground.tests.test_call_navigation import _bundle


def test_compact_vs_full_json_size(tmp_path: Path):
    manifest = _bundle(tmp_path)

    compact_sym = bundle_access.search_symbol_index(manifest, "target", compact=True)
    full_sym = bundle_access.search_symbol_index(manifest, "target", verbose=True)

    compact_sym_bytes = len(json.dumps(compact_sym))
    full_sym_bytes = len(json.dumps(full_sym))

    assert compact_sym["projection"] == COMPACT_PROJECTION
    assert compact_sym["mutation_boundary"]["ref"] == "repobrief.mutation_boundary.read_only_frontdoor.v1"
    assert compact_sym["mutation_boundary"]["read_only"] is True
    assert compact_sym["mutation_boundary"]["read_paths_do_not_refresh"] is True
    assert "does_not_mutate" not in compact_sym["mutation_boundary"]
    assert full_sym["mutation_boundary"]["read_paths_do_not_refresh"] is True
    assert "does_not_mutate" in full_sym["mutation_boundary"]
    assert compact_sym_bytes < full_sym_bytes

    compact_refs = bundle_access.find_references(manifest, "target", compact=True)
    full_refs = bundle_access.find_references(manifest, "target", verbose=True)

    assert compact_refs["mutation_boundary"]["ref"] == "repobrief.mutation_boundary.read_only_frontdoor.v1"
    assert compact_refs["does_not_establish"]["items"] == full_refs["does_not_establish"]
    assert len(json.dumps(compact_refs)) < len(json.dumps(full_refs))

    mcp_compact = mcp_tools.find_symbol(bundle_manifest=manifest, name="target")
    mcp_full = mcp_tools.find_symbol(bundle_manifest=manifest, name="target", verbose=True)

    assert mcp_compact["mutation_boundary"]["ref"] == "repobrief.mutation_boundary.read_only_frontdoor.v1"
    assert mcp_compact["mutation_boundary"]["read_only"] is True
    assert mcp_compact["mutation_boundary"]["forbidden_operations"] == [
        "secret_read",
        "snapshot_create_side_effect",
    ]
    assert "forbidden_operations" in mcp_full["mutation_boundary"]
    assert mcp_compact["does_not_establish"]["items"] == mcp_full["does_not_establish"]
    assert len(json.dumps(mcp_compact)) < len(json.dumps(mcp_full))


def test_compact_projection_preserves_freshness_commit_and_non_fresh_reasons(tmp_path: Path):
    manifest = _bundle(tmp_path)
    full = bundle_access.search_symbol_index(manifest, "target", verbose=True)

    freshness = full.get("freshness") or {}
    compact_f = compact_freshness(freshness, manifest)

    assert compact_f["status"] == freshness.get("status", "unknown")
    assert "commit_identity" in compact_f
    assert compact_f["commit_identity"] is None or isinstance(
        compact_f["commit_identity"]["repositories"], list
    )

    availability_full = full.get("availability")
    compact_avail = compact_availability(availability_full, manifest)
    assert compact_avail["status"] == availability_full.get("status", "unknown")
    assert "gaps" in compact_avail

    stale_freshness = {
        "status": "stale",
        "reason": "snapshot_older_than_max_age",
        "age_seconds": 3600,
        "commit_identity": {"repositories": [{"git_commit": "a" * 40}]},
    }
    compact_stale = compact_freshness(stale_freshness, manifest)
    assert compact_stale["status"] == "stale"
    assert compact_stale["reason"] == "snapshot_older_than_max_age"
    assert compact_stale["age_seconds"] == 3600
    assert compact_stale["commit_identity"] == stale_freshness["commit_identity"]


def test_compact_freshness_normalizes_commit_identity_and_preserves_multi_repo(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    explicit = compact_freshness(
        {"status": "fresh", "git_commit": "c" * 40}, str(manifest)
    )
    assert explicit["commit_identity"] == {
        "repositories": [{"git_commit": "c" * 40}]
    }

    multi = compact_freshness(
        {
            "status": "fresh",
            "commit_identity": {
                "repositories": [
                    {"git_commit": "a" * 40, "repo": "alpha"},
                    {"git_commit": "b" * 40, "repo": "beta"},
                ]
            },
        },
        manifest,
    )
    assert multi["commit_identity"] == {
        "repositories": [
            {"git_commit": "a" * 40, "repo": "alpha"},
            {"git_commit": "b" * 40, "repo": "beta"},
        ]
    }


def test_compact_freshness_uses_bound_identity_and_never_falls_back_to_manifest(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    first_manifest = {
        "created_at": "2026-07-23T10:00:00Z",
        "snapshot_provenance": {
            "repositories": [
                {
                    "repo": "alpha",
                    "provenance_status": "present",
                    "git_commit": "a" * 40,
                }
            ]
        },
    }
    bound_freshness = snapshot_freshness_model(first_manifest)

    manifest.write_text(
        json.dumps(
            {
                "created_at": "2026-07-23T11:00:00Z",
                "snapshot_provenance": {
                    "repositories": [
                        {
                            "repo": "beta",
                            "provenance_status": "present",
                            "git_commit": "b" * 40,
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    compact = compact_freshness(bound_freshness, manifest)
    assert compact["commit_identity"] == {
        "repositories": [{"git_commit": "a" * 40, "repo": "alpha"}]
    }

    # Missing bound provenance remains unknown instead of being silently filled
    # from whatever manifest revision happens to exist at projection time.
    unbound = compact_freshness({"status": "fresh"}, manifest)
    assert unbound["commit_identity"] is None


def test_compact_freshness_rejects_structurally_empty_commit_identity(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    compact = compact_freshness(
        {
            "status": "fresh",
            "commit_identity": {"repositories": [{}, {"repo": "missing-commit"}]},
        },
        manifest,
    )

    assert compact["commit_identity"] is None


def test_compact_projection_preserves_explicit_gaps_without_null_reason():
    artifacts = [
        {"role": "sqlite_index", "requirement": "required", "availability": "available"},
        {
            "role": "required_index",
            "requirement": "required",
            "availability": "missing_required",
            "reason": "required artifact is absent",
        },
        {
            "role": "agent_reading_pack",
            "requirement": "recommended",
            "availability": "missing",
            "reason": "not_generated",
        },
        {"role": "optional_card", "requirement": "optional", "availability": "missing"},
        {
            "role": "corrupted_artifact",
            "requirement": "required",
            "availability": "invalid",
            "reason": "path_escapes_root",
        },
        {"role": "degraded_without_reason", "requirement": "required", "availability": "degraded"},
    ]

    gaps = compact_role_gaps(artifacts)
    gaps_by_role = {gap["role"]: gap for gap in gaps}

    assert "sqlite_index" not in gaps_by_role
    assert "optional_card" not in gaps_by_role
    assert gaps_by_role["required_index"]["availability"] == "missing_required"
    assert gaps_by_role["required_index"]["requirement"] == "required"
    assert "agent_reading_pack" in gaps_by_role
    assert "corrupted_artifact" in gaps_by_role
    assert "reason" not in gaps_by_role["degraded_without_reason"]


def test_compact_graph_availability_preserves_not_generated_reason():
    compact = compact_graph_availability(
        {
            "status": "not_generated",
            "reason": "graph index artifact is not listed",
        }
    )

    assert compact == {
        "status": "not_generated",
        "reason": "graph index artifact is not listed",
    }


def test_compact_projection_preserves_errors_and_truncation(tmp_path: Path):
    manifest = _bundle(tmp_path)

    invalid_res = mcp_tools.find_symbol(
        bundle_manifest=manifest, name="target", kind="unknown_kind"
    )
    assert invalid_res["status"] == "invalid"
    assert invalid_res["result"]["error_code"] == "kind_invalid"
    assert "error" in invalid_res["result"]

    refs = bundle_access.find_references(manifest, "target", k=1)
    assert refs["status"] == "available"
    assert refs["truncated"] is True
    assert len(refs["hits"]) == 1


def test_projection_is_idempotent_and_keeps_explicit_safety_semantics(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    raw = {
        "status": "available",
        "mutation_boundary": {
            "writes": [],
            "read_paths_do_not_refresh": True,
            "not_reachable_from_snapshot_create": True,
            "forbidden_operations": [
                "git_push",
                "secret_read",
                "snapshot_create_side_effect",
            ],
        },
        "does_not_establish": ["truth", "runtime_behavior", "merge_readiness"],
    }

    once = project_read_result(raw, str(manifest))
    twice = project_read_result(once, str(manifest))

    assert twice == once
    assert once["projection"] == COMPACT_PROJECTION
    assert once["mutation_boundary"] == {
        "ref": "repobrief.mutation_boundary.read_only_frontdoor.v1",
        "writes": [],
        "read_only": True,
        "read_paths_do_not_refresh": True,
        "not_reachable_from_snapshot_create": True,
        "forbidden_operations": ["secret_read", "snapshot_create_side_effect"],
    }
    assert once["does_not_establish"] == {
        "ref": "repobrief.does_not_establish.default.v1",
        "items": ["truth", "runtime_behavior", "merge_readiness"],
    }


def test_compact_mutation_boundary_fails_closed_without_explicit_writes():
    for boundary in (None, {}, {"writes": "unknown"}):
        compact = compact_mutation_boundary(boundary)
        assert compact["writes"] is None
        assert compact["read_only"] is None
        assert compact["status"] == "unknown"
        assert compact["reason"] in {
            "mutation_boundary_invalid",
            "writes_not_explicit_list",
        }


def test_compact_mutation_boundary_preserves_critical_forbidden_operations():
    compact = compact_mutation_boundary(
        {
            "writes": [],
            "forbidden_operations": [
                "git_push",
                "secret_read",
                "snapshot_create_side_effect",
            ],
        }
    )

    assert compact["read_only"] is True
    assert compact["forbidden_operations"] == [
        "secret_read",
        "snapshot_create_side_effect",
    ]


def test_range_and_query_invalid_paths_support_compact_projection_with_string_manifest(tmp_path: Path):
    manifest = str(tmp_path / "missing-manifest.json")

    range_result = bundle_access.range_get(manifest, "not-an-object", compact=True)
    assert range_result["status"] == "invalid"
    assert range_result["error_code"] == "range_ref_invalid"
    assert range_result["projection"] == COMPACT_PROJECTION
    assert range_result["mutation_boundary"]["read_only"] is True
    assert range_result["does_not_establish"]["items"]

    query_result = bundle_access.query_existing_index(manifest, 123, compact=True)
    assert query_result["status"] == "invalid"
    assert query_result["error_code"] == "query_invalid"
    assert query_result["projection"] == COMPACT_PROJECTION
    assert query_result["mutation_boundary"]["read_only"] is True
    assert query_result["does_not_establish"]["items"]


def test_all_mcp_navigation_tools_support_verbose_opt_in(tmp_path: Path):
    manifest = _bundle(tmp_path)

    cases = [
        (mcp_tools.find_symbol, {"name": "target"}),
        (mcp_tools.find_references, {"name": "target"}),
        (mcp_tools.get_callers, {"name": "target"}),
        (mcp_tools.get_callees, {"name": "target"}),
    ]
    for reader, kwargs in cases:
        compact = reader(bundle_manifest=manifest, **kwargs)
        verbose = reader(bundle_manifest=manifest, verbose=True, **kwargs)
        assert compact["result"]["projection"] == COMPACT_PROJECTION
        assert "ref" in compact["mutation_boundary"]
        assert compact["mutation_boundary"]["forbidden_operations"] == [
            "secret_read",
            "snapshot_create_side_effect",
        ]
        assert compact["does_not_establish"]["items"] == verbose["does_not_establish"]
        assert "forbidden_operations" in verbose["mutation_boundary"]


def test_verbose_navigation_preserves_historical_full_result_shape(tmp_path: Path):
    manifest = _bundle(tmp_path)
    access_result = bundle_access.find_references(manifest, "", path="pkg/a.py")
    wrapped_verbose = mcp_tools.find_references(
        bundle_manifest=str(manifest),
        name="",
        path="pkg/a.py",
        verbose=True,
    )

    assert wrapped_verbose["status"] == "invalid"
    assert wrapped_verbose["result"] == access_result


def _compact_json_bytes(value: object) -> int:
    return len(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )


def test_compact_callers_preserve_navigation_evidence_and_bound_payload(tmp_path: Path):
    manifest = _bundle(tmp_path)
    compact = mcp_tools.get_callers(
        bundle_manifest=manifest,
        name="target",
        path="pkg/target.py",
        k=6,
    )
    verbose = mcp_tools.get_callers(
        bundle_manifest=manifest,
        name="target",
        path="pkg/target.py",
        k=6,
        verbose=True,
    )

    result = compact["result"]
    full = verbose["result"]
    assert [caller["caller_qualified_name"] for caller in result["callers"]] == [
        caller["caller_qualified_name"] for caller in full["callers"]
    ]
    assert [
        caller["caller_symbol"]["range_ref"] for caller in result["callers"]
    ] == [caller["caller_symbol"]["range_ref"] for caller in full["callers"]]
    assert result["total_caller_count"] == full["total_caller_count"]
    assert result["total_call_site_count"] == full["total_call_site_count"]
    assert result["unresolved_reference_count"] == full["unresolved_reference_count"]
    assert (
        result["unresolved_references_truncated"]
        == full["unresolved_references_truncated"]
    )

    call_site = result["callers"][0]["call_sites"][0]
    assert call_site["evidence_level"] == "S1"
    assert call_site["resolution_status"] == "resolved"
    assert call_site["range_ref"].startswith("file:pkg/a.py#")
    assert "source_range" not in call_site
    assert "caller_start_line" not in call_site

    unresolved = result["unresolved_references"][0]
    assert unresolved["evidence_level"] == "S0"
    assert unresolved["resolution_status"] != "resolved"
    assert unresolved["caller_symbol_id"]
    assert unresolved["caller_qualified_name"]
    assert unresolved["range_ref"].startswith("file:")
    assert unresolved["relation_to_selected_target"]

    coverage = result["call_graph_coverage"]
    full_coverage = full["call_graph_coverage"]
    assert coverage["scope"] == full_coverage["scope"]
    assert coverage["completeness"] == full_coverage["completeness"]
    assert coverage["resolved_ratio"] == full_coverage["resolved_ratio"]
    assert coverage["does_not_establish"] == full_coverage["does_not_establish"]
    assert coverage["task_profile_confidence"]["basic_repo_question"]["status"] == (
        full_coverage["task_profile_confidence"]["basic_repo_question"]["status"]
    )
    assert coverage["task_profile_confidence"]["basic_repo_question"][
        "minimum_resolved_ratio"
    ] == full_coverage["task_profile_confidence"]["basic_repo_question"][
        "minimum_resolved_ratio"
    ]
    assert "unresolved_by_reason" not in coverage
    assert "status_ratios" not in coverage

    assert result["symbol_index"]["sha256"] == full["symbol_index"]["sha256"]
    assert result["call_graph"]["sha256"] == full["call_graph"]["sha256"]
    assert "absolute_path" not in result["symbol_index"]
    assert "absolute_path" not in result["call_graph"]
    assert result["call_graph_metadata"]["resolution_counts"] == full[
        "call_graph_metadata"
    ]["resolution_counts"]

    compact_bytes = _compact_json_bytes(result)
    verbose_bytes = _compact_json_bytes(full)
    assert compact_bytes <= verbose_bytes // 2, (
        compact_bytes,
        verbose_bytes,
    )


def test_compact_callees_preserve_navigation_evidence_and_bound_payload(tmp_path: Path):
    manifest = _bundle(tmp_path)
    compact = mcp_tools.get_callees(
        bundle_manifest=manifest,
        name="caller_one",
        path="pkg/a.py",
        k=6,
    )
    verbose = mcp_tools.get_callees(
        bundle_manifest=manifest,
        name="caller_one",
        path="pkg/a.py",
        k=6,
        verbose=True,
    )

    result = compact["result"]
    full = verbose["result"]
    assert result["caller_symbol"]["id"] == full["caller_symbol"]["id"]
    assert result["caller_symbol"]["range_ref"] == full["caller_symbol"]["range_ref"]
    assert [callee["callee_symbol"]["id"] for callee in result["callees"]] == [
        callee["callee_symbol"]["id"] for callee in full["callees"]
    ]
    assert result["total_callee_count"] == full["total_callee_count"]
    assert result["total_call_site_count"] == full["total_call_site_count"]
    assert result["unresolved_call_site_count"] == full["unresolved_call_site_count"]
    assert (
        result["unresolved_call_sites_truncated"]
        == full["unresolved_call_sites_truncated"]
    )

    for callee in result["callees"]:
        assert callee["callee_symbol"]["range_ref"].startswith("file:")
        for call_site in callee["call_sites"]:
            assert call_site["evidence_level"] == "S1"
            assert call_site["resolution_status"] == "resolved"
            assert call_site["range_ref"].startswith("file:")
            assert "source_range" not in call_site

    unresolved = result["unresolved_call_sites"][0]
    assert unresolved["evidence_level"] == "S0"
    assert unresolved["resolution_status"] != "resolved"
    assert unresolved["callee_expression"]
    assert unresolved["range_ref"].startswith("file:")

    coverage = result["call_graph_coverage"]
    full_coverage = full["call_graph_coverage"]
    assert coverage["resolved_ratio"] == full_coverage["resolved_ratio"]
    assert coverage["completeness"] == full_coverage["completeness"]
    assert coverage["task_profile_confidence"]["review"]["status"] == full_coverage[
        "task_profile_confidence"
    ]["review"]["status"]

    compact_bytes = _compact_json_bytes(result)
    verbose_bytes = _compact_json_bytes(full)
    assert compact_bytes <= verbose_bytes // 2, (
        compact_bytes,
        verbose_bytes,
    )


def test_verbose_call_navigation_keeps_full_historical_result(tmp_path: Path):
    manifest = _bundle(tmp_path)

    direct_callers = bundle_access.get_callers(
        manifest,
        "target",
        path="pkg/target.py",
        k=6,
        verbose=True,
    )
    wrapped_callers = mcp_tools.get_callers(
        bundle_manifest=manifest,
        name="target",
        path="pkg/target.py",
        k=6,
        verbose=True,
    )
    assert wrapped_callers["result"] == direct_callers
    assert "source_range" in direct_callers["callers"][0]["call_sites"][0]
    assert "absolute_path" in direct_callers["symbol_index"]

    direct_callees = bundle_access.get_callees(
        manifest,
        "caller_one",
        path="pkg/a.py",
        k=6,
        verbose=True,
    )
    wrapped_callees = mcp_tools.get_callees(
        bundle_manifest=manifest,
        name="caller_one",
        path="pkg/a.py",
        k=6,
        verbose=True,
    )
    assert wrapped_callees["result"] == direct_callees
    assert "source_range" in direct_callees["callees"][0]["call_sites"][0]
    assert "absolute_path" in direct_callees["call_graph"]


def _candidate_symbol(index: int) -> dict[str, object]:
    return {
        "id": f"candidate-{index}",
        "name": "duplicate",
        "qualified_name": f"scope_{index}.duplicate",
        "kind": "function",
        "path": f"pkg/candidate_{index}.py",
        "start_line": index + 1,
        "end_line": index + 2,
        "range_ref": f"file:pkg/candidate_{index}.py#L{index + 1}-L{index + 2}",
    }


def test_compact_callers_bound_ambiguous_candidates_and_candidate_target_ids(
    tmp_path: Path,
):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    full = {
        "kind": "repobrief.call_callers",
        "status": "invalid",
        "error_code": "symbol_ambiguous",
        "k": 2,
        "target_symbol": None,
        "target_candidates": [_candidate_symbol(index) for index in range(5)],
        "callers": [],
        "unresolved_references": [
            {
                "path": "pkg/a.py",
                "range_ref": "file:pkg/a.py#L10-L10",
                "callee_expression": "duplicate",
                "evidence_level": "S0",
                "resolution_status": "ambiguous",
                "resolution_reason": "multiple_targets",
                "relation_type": "call",
                "relation_to_selected_target": "candidate",
                "candidate_target_ids": [f"candidate-{index}" for index in range(5)],
            }
        ],
    }

    compact = project_read_result(full, manifest)
    assert [item["id"] for item in compact["target_candidates"]] == [
        "candidate-0",
        "candidate-1",
    ]
    assert compact["target_candidate_count"] == 5
    assert compact["target_candidates_truncated"] is True

    unresolved = compact["unresolved_references"][0]
    assert unresolved["candidate_target_ids"] == ["candidate-0", "candidate-1"]
    assert unresolved["candidate_target_id_count"] == 5
    assert unresolved["candidate_target_ids_truncated"] is True

    assert project_read_result(compact, manifest) == compact
    assert project_read_result(full, manifest, verbose=True) == full
    assert len(full["target_candidates"]) == 5
    assert len(full["unresolved_references"][0]["candidate_target_ids"]) == 5


def test_compact_callees_bound_ambiguous_candidates_and_candidate_target_ids(
    tmp_path: Path,
):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    full = {
        "kind": "repobrief.call_callees",
        "status": "invalid",
        "error_code": "symbol_ambiguous",
        "k": 3,
        "caller_symbol": None,
        "caller_candidates": [_candidate_symbol(index) for index in range(6)],
        "callees": [],
        "unresolved_call_sites": [
            {
                "path": "pkg/a.py",
                "range_ref": "file:pkg/a.py#L20-L20",
                "callee_expression": "duplicate",
                "evidence_level": "S0",
                "resolution_status": "ambiguous",
                "resolution_reason": "multiple_targets",
                "relation_type": "call",
                "relation_to_selected_target": "candidate",
                "candidate_target_ids": [f"candidate-{index}" for index in range(6)],
            }
        ],
    }

    compact = project_read_result(full, manifest)
    assert [item["id"] for item in compact["caller_candidates"]] == [
        "candidate-0",
        "candidate-1",
        "candidate-2",
    ]
    assert compact["caller_candidate_count"] == 6
    assert compact["caller_candidates_truncated"] is True

    unresolved = compact["unresolved_call_sites"][0]
    assert unresolved["candidate_target_ids"] == [
        "candidate-0",
        "candidate-1",
        "candidate-2",
    ]
    assert unresolved["candidate_target_id_count"] == 6
    assert unresolved["candidate_target_ids_truncated"] is True

    assert project_read_result(compact, manifest) == compact
    assert project_read_result(full, manifest, verbose=True) == full
    assert len(full["caller_candidates"]) == 6
    assert len(full["unresolved_call_sites"][0]["candidate_target_ids"]) == 6
