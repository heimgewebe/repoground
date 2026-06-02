"""Tests for generator runtime provenance (drift diagnosability).

The bundle manifest ``generator.runtime`` block exists so that runtime /
entry-point drift — a service emitting bundles from a stale build that no longer
matches the repository code — is diagnosable directly from the artifact.
"""

import json

from merger.lenskit.core.constants import ArtifactRole
from merger.lenskit.core.merge import scan_repo, write_reports_v2
from merger.lenskit.core.runtime_provenance import build_runtime_provenance
from merger.lenskit.tests._test_constants import make_generator_info


_MINIMAL_REGISTRY_YAML = """\
kind: lenskit.doc_freshness_registry
version: "1.0"
authority: diagnostic_signal
risk_class: diagnostic
does_not_prove:
  - "a green verify does not prove docs complete or correct"
entries:
  - id: test-claim-done
    doc: docs/README.md
    locator: "section intro"
    claim: "Feature X is implemented"
    status: done
    normative: true
    owner: test
    last_verified: "2026-06-01"
    evidence:
      - kind: symbol
        target: "src/feature.py::FeatureX"
"""


class _Extras:
    json_sidecar = True
    skip_md = False
    format = "markdown"
    augment_sidecar = False
    health = False
    organism_index = False
    fleet_panorama = False
    delta_reports = False
    heatmap = False


_RUNTIME_REQUIRED = {"module", "python_version"}
_RUNTIME_PATH_FIELDS = ("module_file", "package_root", "python_executable")


def test_build_runtime_provenance_has_drift_fields():
    rt = build_runtime_provenance(redact=False)
    # Identity + interpreter must always be present.
    assert rt["module"] == "merger.lenskit.core.merge"
    assert rt["python_version"]
    assert rt["python_executable"]
    # Path fields locate the running build (repo checkout vs site-packages).
    assert rt["module_file"] and rt["module_file"].endswith("merge.py")
    assert rt["package_root"]
    # git_commit/git_dirty may be None (e.g. wheel install) but the keys exist.
    assert "git_commit" in rt
    assert "git_dirty" in rt


def test_generator_runtime_provenance_redacts_absolute_paths_when_redaction_enabled():
    rt = build_runtime_provenance(redact=True)
    # Absolute filesystem paths must be nulled in redacted/export mode.
    for field in _RUNTIME_PATH_FIELDS:
        assert rt[field] is None, f"{field} must be redacted to null"
    # Redaction-safe drift signals are retained.
    assert rt["module"] == "merger.lenskit.core.merge"
    assert rt["python_version"]
    assert "git_commit" in rt  # commit is the redaction-safe drift anchor


def test_redaction_does_not_leak_paths_present_in_unredacted():
    plain = build_runtime_provenance(redact=False)
    red = build_runtime_provenance(redact=True)
    for field in _RUNTIME_PATH_FIELDS:
        # Whatever the unredacted value was, it must not survive redaction.
        assert red[field] is None
        if plain[field] is not None:
            assert red[field] != plain[field]


def _make_single_repo_bundle(tmp_path, *, redact=False):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "README.md").write_text("# Runtime provenance repo\n", encoding="utf-8")
    (src_dir / "docs").mkdir()
    (src_dir / "docs" / "doc-freshness-registry.yml").write_text(
        _MINIMAL_REGISTRY_YAML, encoding="utf-8"
    )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    hub_dir = tmp_path / "hub"
    hub_dir.mkdir()
    summary = scan_repo(src_dir)
    return write_reports_v2(
        merges_dir=out_dir,
        hub=hub_dir,
        repo_summaries=[summary],
        detail="test",
        mode="gesamt",
        max_bytes=10000,
        plan_only=False,
        code_only=False,
        extras=_Extras(),
        output_mode="dual",
        redact_secrets=redact,
        generator_info=make_generator_info(name="rlens", version="dev"),
    )


def test_bundle_manifest_generator_runtime_provenance_present(tmp_path):
    artifacts = _make_single_repo_bundle(tmp_path)
    manifest = json.loads(artifacts.bundle_manifest.read_text(encoding="utf-8"))
    generator = manifest["generator"]
    assert {"name", "version", "config_sha256", "runtime"} <= set(generator)
    runtime = generator["runtime"]
    assert _RUNTIME_REQUIRED <= set(runtime)
    assert runtime["module"] == "merger.lenskit.core.merge"
    # Non-redacted single-repo bundle keeps the locating paths.
    assert runtime["module_file"]
    assert runtime["package_root"]


def test_bundle_manifest_generator_runtime_redacted_when_redaction_enabled(tmp_path):
    artifacts = _make_single_repo_bundle(tmp_path, redact=True)
    manifest = json.loads(artifacts.bundle_manifest.read_text(encoding="utf-8"))
    runtime = manifest["generator"]["runtime"]
    assert runtime["module_file"] is None
    assert runtime["package_root"] is None
    assert runtime["python_executable"] is None
    # Map is still produced and the surface stays coherent under redaction.
    roles = {a["role"] for a in manifest["artifacts"]}
    assert ArtifactRole.CLAIM_EVIDENCE_MAP_JSON.value in roles
