import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from merger.lenskit.retrieval.audit_lane import plan_audit_lanes


def test_routes_concrete_change_surface_before_query_hints():
    plan = plan_audit_lanes(
        [
            "merger/lenskit/core/bundle_generation.py",
            "merger/lenskit/tests/test_bundle_generation.py",
        ],
        review_query="Check races, rollback and stale cache behaviour",
    )

    ids = [lane["id"] for lane in plan["lanes"]]
    assert ids[0] in {"concurrency_toctou", "cache_publication"}
    assert "test_failure_semantics" in ids
    assert plan["routing"]["path_signal_weight"] == 2
    assert plan["authority"] == "navigation_index"


def test_is_deterministic_and_deduplicates_paths():
    paths = ["src/auth/session.py", "src/auth/session.py", "tests/test_auth.py"]
    first = plan_audit_lanes(paths, review_query="permission bypass")
    second = plan_audit_lanes(paths, review_query="permission bypass")

    assert first == second
    assert first["inputs"]["changed_paths"] == ["src/auth/session.py", "tests/test_auth.py"]
    assert first["lanes"][0]["id"] == "auth_boundaries"


def test_respects_lane_bound_and_uses_catalog_order_for_ties():
    plan = plan_audit_lanes(
        ["src/cache/auth/deploy/ui/index/test.py"],
        review_query="race migration release accessibility performance failure",
        max_lanes=3,
    )

    assert len(plan["lanes"]) == 3
    assert plan["routing"]["selected_count"] == 3


def test_emits_general_lane_when_no_signal_matches():
    plan = plan_audit_lanes(["src/domain/widget.py"])

    assert [lane["id"] for lane in plan["lanes"]] == ["general_change_integrity"]
    assert plan["lanes"][0]["score"] == 0


@pytest.mark.parametrize(
    "paths",
    [
        ["/absolute/path.py"],
        ["../escape.py"],
        ["src\\windows.py"],
        [""],
        [123],
        "src/file.py",
        None,
        123,
    ],
)
def test_rejects_non_repository_paths(paths):
    with pytest.raises(ValueError):
        plan_audit_lanes(paths)


@pytest.mark.parametrize("value", [0, 9, True, 1.5])
def test_rejects_invalid_lane_limits(value):
    with pytest.raises(ValueError):
        plan_audit_lanes(["src/file.py"], max_lanes=value)


def test_output_validates_against_contract():
    schema_path = (
        Path(__file__).parents[1] / "contracts" / "audit-lane-plan.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    plan = plan_audit_lanes(
        ["src/migrations/001_add_index.py", "tests/test_migration.py"],
        review_query="database integrity and rollback",
    )

    Draft7Validator.check_schema(schema)
    Draft7Validator(schema).validate(plan)


def test_normalizes_bounded_plural_and_phrase_aliases():
    plan = plan_audit_lanes(
        ["src/domain/widget.py"],
        review_query="races, migrations, N+1 queries and false positives",
    )

    ids = [lane["id"] for lane in plan["lanes"]]
    assert "concurrency_toctou" in ids
    assert "storage_integrity" in ids
    assert "performance_scale" in ids
    assert "test_failure_semantics" in ids


def test_plan_has_explicit_negative_semantics():
    plan = plan_audit_lanes(["src/auth/token.py"])
    boundary = " ".join(plan["does_not_establish"]).lower()

    assert "defect" in boundary
    assert "completeness" in boundary
    assert "authorize" in boundary
