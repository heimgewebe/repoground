"""Tests for TASK-VALIDATION-CHECKVIEW-001 — read-only CheckView adapter.

Covers three producer shapes (OH mapping, PEH list, BSV list), defensive inputs,
and duplicate-name behaviour.  No producer, schema, contract, or CLI output is
modified.
"""

import pytest

from merger.lenskit.core.bundle_surface_validate import validate_bundle_surface
from merger.lenskit.core.check_view import (
    check_by_name,
    checks_by_name,
    iter_check_views,
)
from merger.lenskit.core.output_health import compute_output_health
from merger.lenskit.core.post_emit_health import compute_post_emit_health
from merger.lenskit.tests.bundle_fixtures import (
    make_output_health_kwargs,
    make_post_emit_bundle,
    make_surface_manifest,
)


# ---------------------------------------------------------------------------
# 1. output_health — mapping shape
# ---------------------------------------------------------------------------


def test_oh_scalar_int_not_promoted(tmp_path):
    """chunk_count is an int scalar; CheckView must NOT promote it to a status."""
    report = compute_output_health(
        **make_output_health_kwargs(tmp_path=tmp_path, with_sqlite=False)
    )
    by_name = checks_by_name(report)

    assert "chunk_count" in by_name
    cv = by_name["chunk_count"]
    assert cv.container_shape == "mapping"
    assert isinstance(cv.value, int)
    assert cv.status is None
    assert cv.detail is None
    assert cv.validation is None


def test_oh_scalar_bool_not_promoted(tmp_path):
    """Boolean checks like manifest_present stay as-is with status=None."""
    report = compute_output_health(
        **make_output_health_kwargs(tmp_path=tmp_path, with_sqlite=False)
    )
    by_name = checks_by_name(report)

    assert "manifest_present" in by_name
    cv = by_name["manifest_present"]
    assert cv.container_shape == "mapping"
    assert isinstance(cv.value, bool)
    assert cv.status is None


def test_oh_nested_dict_check_extracts_status_and_validation(tmp_path):
    """range_ref_resolution is a nested dict; status and validation are extracted."""
    report = compute_output_health(
        **make_output_health_kwargs(tmp_path=tmp_path, with_sqlite=False)
    )
    by_name = checks_by_name(report)

    assert "range_ref_resolution" in by_name
    cv = by_name["range_ref_resolution"]
    assert cv.container_shape == "mapping"
    # status is extracted as a string, not None
    assert isinstance(cv.status, str)
    # validation carries the mode/engine/reason triad
    assert cv.validation is not None
    assert {"mode", "engine", "reason"} <= cv.validation.keys()
    for key in ("mode", "engine", "reason"):
        assert isinstance(cv.validation[key], str)


def test_oh_all_views_have_mapping_shape(tmp_path):
    """Every CheckView from an output_health report has container_shape='mapping'."""
    report = compute_output_health(
        **make_output_health_kwargs(tmp_path=tmp_path, with_sqlite=False)
    )
    views = list(iter_check_views(report))
    assert views, "expected at least one view"
    for cv in views:
        assert cv.container_shape == "mapping"


# ---------------------------------------------------------------------------
# 2. post_emit_health — list shape
# ---------------------------------------------------------------------------


def test_peh_manifest_present_check(tmp_path):
    """manifest_present is in the PEH check list with status='pass'."""
    manifest = make_post_emit_bundle(tmp_path)
    report = compute_post_emit_health(str(manifest))
    by_name = checks_by_name(report)

    assert "manifest_present" in by_name
    cv = by_name["manifest_present"]
    assert cv.container_shape == "list"
    assert cv.status == "pass"


def test_peh_all_views_have_list_shape(tmp_path):
    """Every CheckView from a post_emit_health report has container_shape='list'."""
    manifest = make_post_emit_bundle(tmp_path)
    report = compute_post_emit_health(str(manifest))
    views = list(iter_check_views(report))
    assert views, "expected at least one view"
    for cv in views:
        assert cv.container_shape == "list"


def test_peh_range_ref_resolution_validation_triad_when_present(tmp_path):
    """range_ref_resolution in PEH has a validation triad when present."""
    manifest = make_post_emit_bundle(tmp_path)
    report = compute_post_emit_health(str(manifest))
    by_name = checks_by_name(report)

    if "range_ref_resolution" not in by_name:
        pytest.skip("range_ref_resolution not emitted in this environment")
    cv = by_name["range_ref_resolution"]
    assert cv.container_shape == "list"
    assert isinstance(cv.status, str)
    if cv.validation is not None:
        assert {"mode", "engine", "reason"} <= cv.validation.keys()
        for key in ("mode", "engine", "reason"):
            assert isinstance(cv.validation[key], str)


# ---------------------------------------------------------------------------
# 3. bundle_surface_validation — list shape
# ---------------------------------------------------------------------------


def test_bsv_manifest_present_check(tmp_path):
    """manifest_present appears in the BSV check list with status='pass'."""
    manifest = make_surface_manifest(tmp_path, claim_present=True)
    report = validate_bundle_surface(manifest, require_claim_evidence_map=True)
    by_name = checks_by_name(report)

    assert "manifest_present" in by_name
    cv = by_name["manifest_present"]
    assert cv.container_shape == "list"
    assert cv.status == "pass"


def test_bsv_claim_evidence_map_surface_has_validation_triad(tmp_path):
    """claim_evidence_map_surface carries the mode/engine/reason validation triad."""
    manifest = make_surface_manifest(tmp_path, claim_present=True)
    report = validate_bundle_surface(manifest, require_claim_evidence_map=True)
    by_name = checks_by_name(report)

    assert "claim_evidence_map_surface" in by_name
    cv = by_name["claim_evidence_map_surface"]
    assert cv.container_shape == "list"
    assert isinstance(cv.status, str)
    assert cv.validation is not None
    assert {"mode", "engine", "reason"} <= cv.validation.keys()
    for key in ("mode", "engine", "reason"):
        assert isinstance(cv.validation[key], str)


def test_bsv_all_views_have_list_shape(tmp_path):
    """Every CheckView from a bundle_surface_validation report has container_shape='list'."""
    manifest = make_surface_manifest(tmp_path, claim_present=True)
    report = validate_bundle_surface(manifest, require_claim_evidence_map=True)
    views = list(iter_check_views(report))
    assert views, "expected at least one view"
    for cv in views:
        assert cv.container_shape == "list"


# ---------------------------------------------------------------------------
# 4. Defensive inputs
# ---------------------------------------------------------------------------


def test_defensive_no_checks_key():
    """report without 'checks' key yields nothing."""
    assert list(iter_check_views({})) == []


def test_defensive_checks_none():
    """checks=None yields nothing."""
    assert list(iter_check_views({"checks": None})) == []


def test_defensive_checks_empty_list():
    """checks=[] yields nothing; checks_by_name returns {}."""
    assert list(iter_check_views({"checks": []})) == []
    assert checks_by_name({"checks": []}) == {}


def test_defensive_check_by_name_missing():
    """check_by_name returns None for an unknown name."""
    assert check_by_name({"checks": []}, "x") is None


def test_defensive_checks_bad_string():
    """checks='bad' (non-Mapping, non-list) yields nothing."""
    assert list(iter_check_views({"checks": "bad"})) == []


def test_defensive_checks_bad_int():
    """checks=42 yields nothing."""
    assert list(iter_check_views({"checks": 42})) == []


def test_defensive_list_non_dict_entries_skipped():
    """Non-Mapping list entries are skipped; valid entries are kept."""
    report = {"checks": [42, "string", None, {"name": "ok", "status": "pass"}]}
    views = list(iter_check_views(report))
    assert len(views) == 1
    assert views[0].name == "ok"
    assert views[0].status == "pass"


def test_defensive_list_missing_name_skipped():
    """List entries without a string 'name' are skipped."""
    report = {"checks": [{"status": "pass"}, {"name": 42, "status": "pass"}]}
    assert list(iter_check_views(report)) == []


def test_defensive_non_string_status_becomes_none():
    """A non-string 'status' in a nested check dict becomes status=None."""
    report = {"checks": [{"name": "x", "status": 99}]}
    cv = check_by_name(report, "x")
    assert cv is not None
    assert cv.status is None


def test_defensive_non_mapping_validation_becomes_none():
    """A non-Mapping 'validation' is not exposed; validation becomes None."""
    report = {"checks": [{"name": "x", "status": "pass", "validation": "oops"}]}
    cv = check_by_name(report, "x")
    assert cv is not None
    assert cv.validation is None


# ---------------------------------------------------------------------------
# 5. Duplicate names in list shape
# ---------------------------------------------------------------------------


def test_duplicate_names_iter_yields_all():
    """iter_check_views yields all entries, even when names repeat."""
    # Duplicate names are unusual but can appear in synthetic or legacy data.
    report = {
        "checks": [
            {"name": "alpha", "status": "fail"},
            {"name": "alpha", "status": "pass"},
        ]
    }
    views = list(iter_check_views(report))
    assert len(views) == 2
    assert views[0].status == "fail"
    assert views[1].status == "pass"


def test_duplicate_names_checks_by_name_keeps_last():
    """checks_by_name deterministically keeps the last entry for duplicate names.

    This matches the documented contract: iter_check_views preserves insertion
    order; checks_by_name selects the last entry, never raises.
    """
    report = {
        "checks": [
            {"name": "alpha", "status": "fail"},
            {"name": "alpha", "status": "pass"},
        ]
    }
    by_name = checks_by_name(report)
    # last entry wins
    assert by_name["alpha"].status == "pass"


# ---------------------------------------------------------------------------
# 6. List shape: reason fallback
# ---------------------------------------------------------------------------


def test_list_shape_reason_fallback_used_when_detail_missing():
    """When a list entry has 'reason' but no 'detail', reason is used."""
    report = {"checks": [{"name": "x", "status": "pass", "reason": "because"}]}
    cv = check_by_name(report, "x")
    assert cv is not None
    assert cv.detail == "because"


def test_list_shape_detail_wins_over_reason():
    """detail takes precedence over reason in list entries.

    When both 'detail' and 'reason' are present and both are strings,
    'detail' is used and 'reason' is ignored.
    """
    report = {
        "checks": [
            {
                "name": "x",
                "status": "pass",
                "detail": "detail text",
                "reason": "reason text",
            }
        ]
    }
    cv = check_by_name(report, "x")
    assert cv is not None
    assert cv.detail == "detail text"
