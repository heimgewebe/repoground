"""Tests for the diagnostic doc-freshness verifier (v0).

Synthetic fixtures prove the drift detector across the classification spectrum;
a final group asserts the *real* checked-in registry validates and verifies
clean (i.e. the repoLens-spec ExtrasConfig drift is actually closed).
"""
from pathlib import Path

import pytest

from merger.lenskit.core.doc_freshness import (
    DocFreshnessReport,
    EntryResult,
    EvidenceRef,
    classify_entry,
    default_schema_path,
    load_registry,
    render_markdown,
    repo_root_from_here,
    resolve_evidence,
    restamp_last_verified,
    validate_registry,
    verified_entry_ids,
    verify,
)

REPO_ROOT = repo_root_from_here()


# --- evidence resolution -----------------------------------------------------


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_symbol_evidence_present_and_absent(tmp_path):
    _write(tmp_path, "mod.py", "class Foo:\n    pass\n\ndef bar():\n    return 1\n")
    assert resolve_evidence(
        EvidenceRef("symbol", "mod.py::Foo"), tmp_path
    ).satisfied
    assert resolve_evidence(
        EvidenceRef("symbol", "mod.py::bar"), tmp_path
    ).satisfied
    assert not resolve_evidence(
        EvidenceRef("symbol", "mod.py::Missing"), tmp_path
    ).satisfied


def test_symbol_evidence_assignment_and_annassign(tmp_path):
    _write(tmp_path, "c.py", "X = 1\nY: int = 2\n")
    assert resolve_evidence(EvidenceRef("symbol", "c.py::X"), tmp_path).satisfied
    assert resolve_evidence(EvidenceRef("symbol", "c.py::Y"), tmp_path).satisfied


def test_symbol_unparsable_falls_back_to_substring(tmp_path):
    _write(tmp_path, "broken.py", "def (:\n  ExtrasConfig\n")
    # Not valid Python; falls back to substring probe rather than crashing.
    assert resolve_evidence(
        EvidenceRef("symbol", "broken.py::ExtrasConfig"), tmp_path
    ).satisfied


def test_text_and_absent_text(tmp_path):
    _write(tmp_path, "doc.md", "hello TODO world\n")
    assert resolve_evidence(EvidenceRef("text", "doc.md::TODO"), tmp_path).satisfied
    # absent_text is satisfied when the needle is genuinely absent.
    assert resolve_evidence(
        EvidenceRef("absent_text", "doc.md::NOPE"), tmp_path
    ).satisfied
    assert not resolve_evidence(
        EvidenceRef("absent_text", "doc.md::TODO"), tmp_path
    ).satisfied


def test_text_and_absent_text_missing_file_are_not_satisfied(tmp_path):
    assert not resolve_evidence(
        EvidenceRef("text", "missing.md::TODO"), tmp_path
    ).satisfied
    assert not resolve_evidence(
        EvidenceRef("absent_text", "missing.md::TODO"), tmp_path
    ).satisfied


def test_file_proof_test_evidence(tmp_path):
    _write(tmp_path, "docs/proofs/x-proof.md", "# proof\n")
    _write(tmp_path, "tests/test_x.py", "def test_x():\n    assert True\n")
    assert resolve_evidence(
        EvidenceRef("file", "docs/proofs/x-proof.md"), tmp_path
    ).satisfied
    assert resolve_evidence(
        EvidenceRef("proof", "docs/proofs/x-proof.md"), tmp_path
    ).satisfied
    assert resolve_evidence(
        EvidenceRef("test", "tests/test_x.py::test_x"), tmp_path
    ).satisfied
    assert not resolve_evidence(
        EvidenceRef("test", "tests/test_x.py::test_absent"), tmp_path
    ).satisfied
    assert not resolve_evidence(
        EvidenceRef("proof", "docs/proofs/nope.md"), tmp_path
    ).satisfied


def test_test_evidence_matches_async_def(tmp_path):
    _write(tmp_path, "tests/test_async.py", "async def test_async_case():\n    assert True\n")
    assert resolve_evidence(
        EvidenceRef("test", "tests/test_async.py::test_async_case"), tmp_path
    ).satisfied


def test_resolve_evidence_rejects_path_escape(tmp_path):
    outside = tmp_path.parent / "outside.py"
    outside.write_text("class Hidden:\n    pass\n", encoding="utf-8")
    res = resolve_evidence(EvidenceRef("symbol", "../outside.py::Hidden"), tmp_path)
    assert not res.satisfied
    assert "invalid path" in res.detail


def test_read_replaces_invalid_utf8(tmp_path):
    p = tmp_path / "bin.dat"
    p.write_bytes(b"\xff\xfeTODO")
    assert resolve_evidence(EvidenceRef("text", "bin.dat::TODO"), tmp_path).satisfied


def test_symbol_in_non_python_file_uses_substring(tmp_path):
    _write(tmp_path, "schema.json", '{"const": "WidgetThing"}\n')
    assert resolve_evidence(
        EvidenceRef("symbol", "schema.json::WidgetThing"), tmp_path
    ).satisfied


# --- classification ----------------------------------------------------------


def _present_symbol() -> list:
    return [resolve_evidence_stub("symbol", satisfied=True, implies="done")]


def resolve_evidence_stub(kind, *, satisfied, implies=None):
    from merger.lenskit.core.doc_freshness import EvidenceResult

    ref = EvidenceRef(kind, f"x::{kind}", implies=implies)
    return EvidenceResult(ref, satisfied, "stub")


def test_none_with_completion_evidence_is_understated():
    cls, sev, _ = classify_entry("none", _present_symbol())
    assert cls == "understated"
    assert sev == "warning"


def test_none_without_evidence_is_consistent():
    cls, sev, _ = classify_entry(
        "none", [resolve_evidence_stub("symbol", satisfied=False, implies="done")]
    )
    assert cls == "consistent"
    assert sev == "ok"


def test_done_with_evidence_consistent():
    results = [
        resolve_evidence_stub("symbol", satisfied=True, implies="done"),
        resolve_evidence_stub("absent_text", satisfied=True),
    ]
    cls, sev, _ = classify_entry("done", results)
    assert cls == "consistent"
    assert sev == "ok"


def test_done_with_stale_marker_present_flags():
    # The pilot "before" state: implemented, but the TODO heading is still there.
    results = [
        resolve_evidence_stub("symbol", satisfied=True, implies="done"),
        resolve_evidence_stub("absent_text", satisfied=False),  # marker still present
    ]
    cls, sev, _ = classify_entry("done", results)
    assert cls == "stale_marker_present"
    assert sev == "warning"


def test_done_with_missing_evidence_regressed():
    results = [resolve_evidence_stub("symbol", satisfied=False, implies="done")]
    cls, sev, _ = classify_entry("done", results)
    assert cls == "regressed"
    assert sev == "error"


def test_stale_confirmed_when_reproduces():
    # implemented (symbol present) AND doc still shows it open (text/open present).
    results = [
        resolve_evidence_stub("symbol", satisfied=True, implies="done"),
        resolve_evidence_stub("text", satisfied=True, implies="open"),
    ]
    cls, sev, _ = classify_entry("stale", results)
    assert cls == "stale_confirmed"
    assert sev == "ok"  # tracked, not a finding


def test_stale_resolved_when_marker_gone():
    results = [
        resolve_evidence_stub("symbol", satisfied=True, implies="done"),
        resolve_evidence_stub("text", satisfied=False, implies="open"),
    ]
    cls, sev, _ = classify_entry("stale", results)
    assert cls == "stale_resolved"
    assert sev == "warning"


def test_stale_regressed_when_not_actually_done():
    results = [
        resolve_evidence_stub("symbol", satisfied=False, implies="done"),
        resolve_evidence_stub("text", satisfied=True, implies="open"),
    ]
    cls, sev, _ = classify_entry("stale", results)
    assert cls == "regressed"
    assert sev == "error"


def test_partial_not_flagged_even_with_symbol():
    results = [resolve_evidence_stub("symbol", satisfied=True, implies="done")]
    cls, sev, _ = classify_entry("partial", results)
    assert cls == "partial_ok"
    assert sev == "ok"


def test_partial_regressed_when_evidence_vanishes():
    results = [resolve_evidence_stub("symbol", satisfied=False, implies="done")]
    cls, sev, _ = classify_entry("partial", results)
    assert cls == "regressed"


def test_partial_maybe_resolved_when_open_marker_gone():
    """partial entries with text implies:open should warn when marker disappears."""
    results = [resolve_evidence_stub("text", satisfied=False, implies="open")]
    cls, sev, msg = classify_entry("partial", results)
    assert cls == "partial_maybe_resolved"
    assert sev == "warning"
    assert "open marker" in msg.lower()


def test_historical_never_checked():
    results = [resolve_evidence_stub("symbol", satisfied=False, implies="done")]
    cls, sev, _ = classify_entry("historical", results)
    assert cls == "historical"
    assert sev == "ok"


# --- end-to-end verify on synthetic registries -------------------------------


def _make_registry(entries):
    return {
        "kind": "lenskit.doc_freshness_registry",
        "version": "1.0",
        "entries": entries,
    }


def test_verify_detects_understated_drift(tmp_path):
    _write(tmp_path, "core.py", "class Widget:\n    pass\n")
    _write(tmp_path, "plan.md", "TODO: build Widget\n")
    data = _make_registry(
        [
            {
                "id": "widget",
                "doc": "plan.md",
                "claim": "Widget built",
                "status": "none",
                "owner": "x",
                "last_verified": "2026-05-31",
                "evidence": [{"kind": "symbol", "target": "core.py::Widget"}],
            }
        ]
    )
    report = verify(data, tmp_path)
    assert report.status == "warn"
    assert report.results[0].classification == "understated"


def test_verify_pilot_before_and_after(tmp_path):
    """A 'done' entry flips from stale_marker_present to consistent when the
    stale TODO heading is removed — the exact pilot transition."""
    _write(tmp_path, "core.py", "class ExtrasConfig:\n    pass\n")
    _write(tmp_path, "docs/proofs/p.md", "# proof\n")
    data = _make_registry(
        [
            {
                "id": "extras",
                "doc": "spec.md",
                "claim": "ExtrasConfig implemented",
                "status": "done",
                "normative": True,
                "owner": "spec",
                "last_verified": "2026-05-31",
                "evidence": [
                    {"kind": "symbol", "target": "core.py::ExtrasConfig"},
                    {"kind": "proof", "target": "docs/proofs/p.md"},
                    {"kind": "absent_text", "target": "spec.md::### TODO: Extras"},
                ],
            }
        ]
    )

    # BEFORE: spec still carries the TODO heading → flagged.
    _write(tmp_path, "spec.md", "### TODO: Extras\nstuff\n")
    before = verify(data, tmp_path)
    assert before.status == "warn"
    assert before.results[0].classification == "stale_marker_present"

    # AFTER: TODO heading removed → consistent, clean.
    _write(tmp_path, "spec.md", "### Extras — implemented\nstuff\n")
    after = verify(data, tmp_path)
    assert after.status == "pass"
    assert after.results[0].classification == "consistent"


def test_verify_dangling_evidence_is_error(tmp_path):
    _write(tmp_path, "spec.md", "done\n")
    data = _make_registry(
        [
            {
                "id": "gone",
                "doc": "spec.md",
                "claim": "Thing done",
                "status": "done",
                "owner": "x",
                "last_verified": "2026-05-31",
                "evidence": [{"kind": "symbol", "target": "missing.py::Thing"}],
            }
        ]
    )
    report = verify(data, tmp_path)
    assert report.status == "fail"
    assert report.error_count == 1
    assert report.results[0].classification == "regressed"


def test_verify_dangling_doc_is_error():
    """Registry entry with missing doc file should report dangling_doc error."""
    data = _make_registry(
        [
            {
                "id": "missing-doc",
                "doc": "nonexistent.md",
                "claim": "test",
                "status": "done",
                "normative": True,
                "evidence": [{"kind": "symbol", "target": "mod.py::Foo"}],
            }
        ]
    )
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Create the evidence file but NOT the doc file
        _write(root, "mod.py", "class Foo:\n    pass\n")
        report = verify(data, root)
        assert report.status == "fail"
        assert report.error_count == 1
        assert any(r.classification == "dangling_doc" for r in report.results)
        assert any("does not exist" in r.message for r in report.results)


def test_verify_dangling_doc_invalid_path_is_error(tmp_path):
    data = _make_registry(
        [
            {
                "id": "invalid-doc",
                "doc": "../outside.md",
                "claim": "test",
                "status": "done",
                "normative": True,
                "evidence": [{"kind": "symbol", "target": "mod.py::Foo"}],
            }
        ]
    )
    _write(tmp_path, "mod.py", "class Foo:\n    pass\n")
    report = verify(data, tmp_path)
    assert report.status == "fail"
    assert any(r.classification == "dangling_doc" for r in report.results)
    assert any("invalid" in r.message for r in report.results)


def test_verify_missing_absent_text_target_is_error(tmp_path):
    _write(tmp_path, "spec.md", "done\n")
    _write(tmp_path, "core.py", "class Thing:\n    pass\n")
    data = _make_registry(
        [
            {
                "id": "missing-absent-text-target",
                "doc": "spec.md",
                "claim": "Thing done",
                "status": "done",
                "owner": "x",
                "last_verified": "2026-05-31",
                "evidence": [
                    {"kind": "symbol", "target": "core.py::Thing"},
                    {"kind": "absent_text", "target": "missing.md::### TODO: Thing"},
                ],
            }
        ]
    )

    report = verify(data, tmp_path)
    assert report.status == "fail"
    assert report.error_count == 1
    assert report.results[0].classification == "regressed"
    assert "MISSING file" in report.results[0].message


def test_strict_escalates_normative_stale_confirmed(tmp_path):
    _write(tmp_path, "core.py", "class Done:\n    pass\n")
    _write(tmp_path, "spec.md", "### TODO: Done later\n")
    data = _make_registry(
        [
            {
                "id": "s",
                "doc": "spec.md",
                "claim": "Done",
                "status": "stale",
                "normative": True,
                "owner": "x",
                "last_verified": "2026-05-31",
                "evidence": [
                    {"kind": "symbol", "target": "core.py::Done"},
                    {
                        "kind": "text",
                        "target": "spec.md::### TODO: Done later",
                        "implies": "open",
                    },
                ],
            }
        ]
    )
    non_strict = verify(data, tmp_path, strict=False)
    assert non_strict.status == "pass"  # tracked, not a finding
    assert non_strict.stale_confirmed

    strict = verify(data, tmp_path, strict=True)
    assert strict.status == "fail"  # normative + stale_confirmed escalates
    assert len(strict.findings) == 1


# --- render + restamp --------------------------------------------------------


def _ok_report():
    r = DocFreshnessReport()
    r.results.append(
        EntryResult(
            entry_id="a",
            doc="d.md",
            claim="c",
            declared_status="done",
            normative=False,
            classification="consistent",
            severity="ok",
            message="ok",
        )
    )
    r.entries_scanned = 1
    return r


def test_render_markdown_deterministic_and_tabular():
    data = _make_registry(
        [
            {
                "id": "a",
                "doc": "d.md",
                "claim": "c",
                "status": "done",
                "owner": "o",
                "last_verified": "2026-05-31",
                "evidence": [{"kind": "file", "target": "d.md"}],
            }
        ]
    )
    report = _ok_report()
    out1 = render_markdown(data, report, "2026-05-31")
    out2 = render_markdown(data, report, "2026-05-31")
    assert out1 == out2
    assert "GENERATED FILE" in out1
    assert "| ID | Status | Verdict | Doc | Claim | last_verified |" in out1
    assert "`a`" in out1


def test_restamp_last_verified_surgical():
    text = (
        "# header comment\n"
        "entries:\n"
        "  - id: alpha\n"
        "    last_verified: \"2020-01-01\"\n"
        "    status: done\n"
        "  - id: beta\n"
        "    last_verified: \"2020-01-01\"\n"
    )
    new_text, changed = restamp_last_verified(text, {"alpha": "2026-05-31"})
    assert changed == ["alpha"]
    assert "# header comment" in new_text  # comments preserved
    assert 'last_verified: "2026-05-31"' in new_text
    # beta untouched
    assert new_text.count('last_verified: "2020-01-01"') == 1


def test_verified_entry_ids_excludes_findings():
    r = DocFreshnessReport()
    r.results = [
        EntryResult("ok1", "d", "c", "done", False, "consistent", "ok", "m"),
        EntryResult("bad", "d", "c", "done", False, "regressed", "error", "m"),
        EntryResult("stale1", "d", "c", "stale", False, "stale_confirmed", "ok", "m"),
    ]
    ids = verified_entry_ids(r)
    assert "ok1" in ids
    assert "stale1" in ids  # tracked-but-ok is stampable
    assert "bad" not in ids


# --- the REAL checked-in registry --------------------------------------------


@pytest.fixture
def real_registry():
    from merger.lenskit.core.doc_freshness import default_registry_path

    return load_registry(default_registry_path(REPO_ROOT))


@pytest.mark.doc_freshness_live
def test_real_registry_schema_valid(real_registry):
    errors = validate_registry(real_registry, default_schema_path(REPO_ROOT))
    assert errors == [], f"registry schema errors: {errors}"


@pytest.mark.doc_freshness_live
def test_real_registry_verifies_clean(real_registry):
    """The live registry must be green: every tracked claim matches its
    evidence (proves the repoLens-spec ExtrasConfig drift is actually closed)."""
    report = verify(real_registry, REPO_ROOT)
    assert report.status == "pass", report.to_dict()
    assert report.error_count == 0


@pytest.mark.doc_freshness_live
def test_real_registry_strict_clean(real_registry):
    """No normative doc carries an unresolved stale drift."""
    report = verify(real_registry, REPO_ROOT, strict=True)
    assert report.status == "pass", report.to_dict()
