import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, ValidationError

from merger.lenskit.retrieval.audit_lane import plan_audit_lanes


def _schema():
    path = Path(__file__).parents[1] / "contracts" / "audit-lane-plan.v1.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_routes_concrete_change_surface_before_query_hints():
    plan = plan_audit_lanes(
        [
            "merger/lenskit/core/bundle_generation.py",
            "merger/lenskit/tests/test_bundle_generation.py",
        ],
        review_query="auth secret permission",
    )
    ids = [lane["id"] for lane in plan["lanes"]]
    assert ids[0] in {"concurrency_toctou", "cache_publication"}
    assert plan["routing"]["path_signal_weight"] == 3
    assert plan["routing"]["query_signal_weight"] == 1


def test_is_deterministic_for_canonical_unique_paths():
    paths = ["src/auth/session.py", "tests/test_auth.py"]
    first = plan_audit_lanes(paths, review_query="permission bypass")
    second = plan_audit_lanes(paths, review_query="permission bypass")
    assert first == second
    assert first["inputs"]["changed_paths"] == paths
    assert first["lanes"][0]["id"] == "auth_boundaries"


@pytest.mark.parametrize(
    "raw",
    [
        "foo//bar.py",
        "foo/./bar.py",
        "./foo.py",
        "foo/",
        ".",
        "foo/../bar.py",
        "foo/bar/../baz.py",
        "/absolute/path.py",
        "src\\windows.py",
        "src/new\nline.py",
        "",
    ],
)
def test_rejects_noncanonical_or_nonrepository_paths(raw):
    with pytest.raises(ValueError):
        plan_audit_lanes([raw])


def test_rejects_duplicate_paths_instead_of_silently_deduplicating():
    with pytest.raises(ValueError, match="duplicates"):
        plan_audit_lanes(["src/auth/session.py", "src/auth/session.py"])


@pytest.mark.parametrize("paths", [[123], "src/file.py", None, 123])
def test_rejects_malformed_path_collections(paths):
    with pytest.raises(ValueError):
        plan_audit_lanes(paths)


@pytest.mark.parametrize("value", [0, 9, True, 1.5])
def test_rejects_invalid_lane_limits(value):
    with pytest.raises(ValueError):
        plan_audit_lanes(["src/file.py"], max_lanes=value)


def test_rejects_bounded_input_overflows():
    with pytest.raises(ValueError, match="at most 5000"):
        plan_audit_lanes((f"src/file_{index}.py" for index in range(5001)))
    with pytest.raises(ValueError, match="4096"):
        plan_audit_lanes(["a" * 4097])
    with pytest.raises(ValueError, match="8192"):
        plan_audit_lanes([], review_query="x" * 8193)


def test_handles_one_thousand_paths_with_bounded_deterministic_output():
    paths = [f"src/domain/file_{index}.py" for index in range(1000)]
    plan = plan_audit_lanes(paths)
    assert plan["inputs"]["changed_paths"] == paths
    assert plan["routing"]["fallback_used"] is True
    assert plan["routing"]["path_token_count"] >= 1002
    assert len(plan["lanes"]) == 1


def test_normalizes_unicode_case_plural_and_phrase_aliases():
    plan = plan_audit_lanes(
        ["src/domain/widget.py"],
        review_query=(
            "RACES, Migrationen, N + 1 Abfragen, false‑positive, "
            "Berechtigungen, Zugänglichkeit und Skalierung"
        ),
        max_lanes=8,
    )
    ids = {lane["id"] for lane in plan["lanes"]}
    assert {
        "concurrency_toctou",
        "storage_integrity",
        "performance_scale",
        "test_failure_semantics",
        "auth_boundaries",
        "ui_accessibility",
    } <= ids


def test_phrase_aliases_do_not_cross_path_boundaries():
    plan = plan_audit_lanes(["src/false", "positive/file.py"])
    lane = plan["lanes"][0]
    assert lane["id"] == "general_change_integrity"


def test_respects_lane_bound_and_uses_catalog_order_for_ties():
    plan = plan_audit_lanes(
        ["src/cache/auth/deploy/ui/index/test.py"],
        review_query="race migration release accessibility performance failure",
        max_lanes=3,
    )
    assert len(plan["lanes"]) == 3
    assert plan["routing"]["selected_count"] == 3
    assert plan["routing"]["candidate_lane_count"] >= 3


def test_emits_general_lane_when_no_signal_matches():
    plan = plan_audit_lanes(["src/domain/widget.py"])
    assert [lane["id"] for lane in plan["lanes"]] == ["general_change_integrity"]
    assert plan["lanes"][0]["score"] == 0
    assert plan["routing"]["fallback_used"] is True


def test_output_validates_against_contract():
    schema = _schema()
    plan = plan_audit_lanes(
        ["src/migrations/001_add_index.py", "tests/test_migration.py"],
        review_query="database integrity and rollback",
    )
    Draft7Validator.check_schema(schema)
    Draft7Validator(schema).validate(plan)


def test_contract_rejects_weak_or_incomplete_negative_semantics():
    schema = _schema()
    plan = plan_audit_lanes(["src/auth/token.py"])
    plan["does_not_establish"] = ["A", "B", "C", "D", "E"]
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(plan)


def test_contract_accepts_negative_semantics_in_any_order():
    schema = _schema()
    plan = plan_audit_lanes(["src/auth/token.py"])
    plan["does_not_establish"].reverse()
    Draft7Validator(schema).validate(plan)
