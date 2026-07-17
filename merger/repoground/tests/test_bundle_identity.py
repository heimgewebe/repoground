from __future__ import annotations

import json
from pathlib import Path

from merger.repoground.core.bundle_identity import (
    CANONICAL_BUNDLE_KIND,
    CANONICAL_BUNDLE_VERSION,
    LEGACY_BUNDLE_KIND,
    LEGACY_BUNDLE_VERSION,
    bundle_identity,
    bundle_schema_path,
    is_bundle_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def test_bundle_schemas_keep_v1_and_version_v2_explicitly() -> None:
    v1 = json.loads((ROOT / "contracts" / "bundle-manifest.v1.schema.json").read_text())
    v2 = json.loads((ROOT / "contracts" / "bundle-manifest.v2.schema.json").read_text())
    assert v1["properties"]["kind"]["const"] == LEGACY_BUNDLE_KIND
    assert v1["properties"]["version"]["const"] == LEGACY_BUNDLE_VERSION
    assert v2["properties"]["kind"]["const"] == CANONICAL_BUNDLE_KIND
    assert v2["properties"]["version"]["const"] == CANONICAL_BUNDLE_VERSION
    assert v1["$id"] != v2["$id"]


def test_bundle_identity_accepts_only_documented_pairs() -> None:
    canonical = {"kind": CANONICAL_BUNDLE_KIND, "version": CANONICAL_BUNDLE_VERSION}
    legacy = {"kind": LEGACY_BUNDLE_KIND, "version": LEGACY_BUNDLE_VERSION}
    assert bundle_identity(canonical) == "canonical"
    assert bundle_identity(legacy) == "legacy"
    assert is_bundle_manifest(canonical)
    assert is_bundle_manifest(legacy)
    assert bundle_schema_path(canonical).name == "bundle-manifest.v2.schema.json"
    assert bundle_schema_path(legacy).name == "bundle-manifest.v1.schema.json"


def test_bundle_identity_rejects_contradictions_and_unknown_values() -> None:
    assert bundle_identity({"kind": CANONICAL_BUNDLE_KIND, "version": LEGACY_BUNDLE_VERSION}) is None
    assert bundle_identity({"kind": LEGACY_BUNDLE_KIND, "version": CANONICAL_BUNDLE_VERSION}) is None
    assert bundle_identity({"kind": CANONICAL_BUNDLE_KIND}) is None
    assert bundle_identity({"kind": LEGACY_BUNDLE_KIND}) == "legacy"
    assert bundle_identity({"kind": "unknown.bundle", "version": "1"}) is None


def test_active_production_code_centralizes_legacy_bundle_identity() -> None:
    active_roots = (
        ROOT.parent / "core",
        ROOT.parent / "retrieval",
        ROOT.parent / "service",
        ROOT.parent / "cli",
        ROOT.parent / "adapters",
        ROOT.parent / "architecture",
        ROOT.parent / "scripts",
        ROOT.parents[1] / "scripts" / "proofs",
    )
    allowed = {ROOT.parent / "core" / "bundle_identity.py"}
    findings: list[str] = []
    for active_root in active_roots:
        for path in sorted(active_root.rglob("*.py")):
            if path in allowed or "tests" in path.parts:
                continue
            if LEGACY_BUNDLE_KIND in path.read_text(encoding="utf-8"):
                findings.append(str(path.relative_to(ROOT.parents[1])))
    assert findings == []
