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
