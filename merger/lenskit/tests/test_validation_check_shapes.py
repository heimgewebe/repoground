"""Regression tests for TASK-VALIDATION-DIAG-003 — Check-Shape Consistency Audit.

These tests pin the *currently accepted* shape of the ``checks`` surface emitted by
the three validation producers, so the documented dict-vs-list divergence cannot
drift silently:

- ``output_health["checks"]``            -> mapping/dict keyed by check name
- ``post_emit_health["checks"]``         -> ordered list of check objects
- ``bundle_surface_validation["checks"]`` -> ordered list of check objects

They stabilize *shape only*. They intentionally do not assert verdicts, status
precedence, or per-check semantics (those are covered by each producer's own
suite), and they introduce no new vocabulary or producer behaviour. The audit and
its consumer inventory live in
``docs/proofs/validation-check-shape-consistency-audit.md``.

Fixtures are imported from a shared test helper module to decouple tests.
"""

from merger.lenskit.core.bundle_surface_validate import validate_bundle_surface
from merger.lenskit.core.output_health import compute_output_health
from merger.lenskit.core.post_emit_health import compute_post_emit_health
from merger.lenskit.tests.bundle_fixtures import (
    make_output_health_kwargs,
    make_post_emit_bundle,
    make_surface_manifest,
)


def test_output_health_checks_remains_mapping(tmp_path):
    """output_health['checks'] is a mapping keyed by check name; the range-ref
    diagnostic is a nested object at checks['range_ref_resolution']['validation']."""
    report = compute_output_health(
        **make_output_health_kwargs(tmp_path=tmp_path, with_sqlite=False)
    )

    checks = report["checks"]
    assert isinstance(checks, dict)
    assert "range_ref_resolution" in checks
    rr_check = checks["range_ref_resolution"]
    assert isinstance(rr_check, dict)
    assert "validation" in rr_check
    validation = rr_check["validation"]
    assert isinstance(validation, dict)
    assert {"mode", "engine", "reason"} <= validation.keys()
    for key in ("mode", "engine", "reason"):
        assert isinstance(validation[key], str)


def test_post_emit_health_checks_remains_list_of_named_checks(tmp_path):
    """post_emit_health['checks'] is an ordered list of {name, status, ...} objects.

    A check's ``validation`` is optional, but where present it carries the full
    {mode, engine, reason} triad (the test does not force every check to carry it).
    """
    manifest = make_post_emit_bundle(tmp_path)
    report = compute_post_emit_health(str(manifest))

    checks = report["checks"]
    assert isinstance(checks, list)
    assert checks, "expected at least one check"
    for check in checks:
        assert isinstance(check, dict)
        assert "name" in check
        assert "status" in check
        if "validation" in check:
            validation = check["validation"]
            assert isinstance(validation, dict)
            assert {"mode", "engine", "reason"} <= validation.keys()
            for key in ("mode", "engine", "reason"):
                assert isinstance(validation[key], str)


def test_bundle_surface_validation_checks_remains_list_of_named_checks(tmp_path):
    """bundle_surface_validation['checks'] is an ordered list of {name, status, ...}
    objects; checks that carry validation expose the shared validation triad."""
    manifest = make_surface_manifest(tmp_path, claim_present=True)
    report = validate_bundle_surface(manifest, require_claim_evidence_map=True)

    checks = report["checks"]
    assert isinstance(checks, list)
    assert checks, "expected at least one check"
    for check in checks:
        assert isinstance(check, dict)
        assert "name" in check
        assert "status" in check
        if "validation" in check:
            validation = check["validation"]
            assert isinstance(validation, dict)
            assert {"mode", "engine", "reason"} <= validation.keys()
            for key in ("mode", "engine", "reason"):
                assert isinstance(validation[key], str)
