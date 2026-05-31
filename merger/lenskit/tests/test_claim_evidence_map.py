import json
from pathlib import Path

import jsonschema
import pytest

from merger.lenskit.core.claim_evidence_map import (
    build_claim_evidence_map,
    produce_claim_evidence_map,
)


def _schema() -> dict:
    schema_path = (
        Path(__file__).parent.parent / "contracts" / "claim-evidence-map.v1.schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _registry_fixture() -> dict:
    return {
        "kind": "lenskit.doc_freshness_registry",
        "version": "1.0",
        "entries": [
            {
                "id": "b-open",
                "doc": "docs/roadmap/lenskit-master-roadmap.md",
                "locator": "Phase 5",
                "claim": "Open claim",
                "status": "partial",
                "normative": False,
                "owner": "roadmap",
                "last_verified": "2026-05-31",
                "evidence": [
                    {
                        "kind": "text",
                        "target": "x.py::pending marker",
                        "implies": "open",
                    }
                ],
            },
            {
                "id": "a-done",
                "doc": "docs/architecture/system-map.lenskit.md",
                "locator": "section alpha",
                "claim": "Done claim",
                "status": "done",
                "normative": True,
                "owner": "architecture",
                "last_verified": "2026-05-30",
                "evidence": [
                    {
                        "kind": "symbol",
                        "target": "merger/lenskit/core/x.py::Thing",
                    }
                ],
            },
        ],
    }


def _collect_field_names(value):
    names = set()
    if isinstance(value, dict):
        for key, item in value.items():
            names.add(key)
            names.update(_collect_field_names(item))
    elif isinstance(value, list):
        for item in value:
            names.update(_collect_field_names(item))
    return names


def test_claim_evidence_map_schema_accepts_minimal_valid_document():
    doc = {
        "kind": "lenskit.claim_evidence_map",
        "version": "1.0",
        "authority": "navigation_index",
        "canonicality": "derived",
        "risk_class": "evidence_index",
        "source": {
            "registry_path": "docs/doc-freshness-registry.yml",
            "registry_sha256": "a" * 64,
            "generated_at": "2026-05-31T00:00:00Z",
        },
        "does_not_establish": [
            "truth",
            "sufficiency",
            "causality",
            "completeness",
            "freshness_beyond_last_verified",
        ],
        "claims": [
            {
                "id": "x",
                "claim": "c",
                "doc": "docs/a.md",
                "locator": "l",
                "status": "done",
                "normative": False,
                "owner": "o",
                "last_verified": "2026-05-31",
                "requires_live_check": False,
                "evidence_refs": [{"kind": "symbol", "target": "a.py::X"}],
                "relation": "declared_evidence_ref",
                "does_not_establish": [
                    "truth",
                    "sufficiency",
                    "causality",
                    "completeness",
                ],
            }
        ],
    }

    jsonschema.validate(instance=doc, schema=_schema())


def test_build_claim_evidence_map_is_deterministic_and_preserves_evidence_shape():
    registry = _registry_fixture()

    first = build_claim_evidence_map(
        registry,
        registry_sha256="b" * 64,
        generated_at="2026-05-31T12:00:00Z",
    )
    second = build_claim_evidence_map(
        registry,
        registry_sha256="b" * 64,
        generated_at="2026-05-31T12:00:00Z",
    )

    assert first == second

    ids = [row["id"] for row in first["claims"]]
    assert ids == ["a-done", "b-open"]

    done = first["claims"][0]
    open_claim = first["claims"][1]

    assert done["requires_live_check"] is False
    assert open_claim["requires_live_check"] is True

    assert done["evidence_refs"] == [
        {"kind": "symbol", "target": "merger/lenskit/core/x.py::Thing"}
    ]
    assert open_claim["evidence_refs"] == [
        {"kind": "text", "target": "x.py::pending marker", "implies": "open"}
    ]

    assert first["does_not_establish"] == [
        "truth",
        "sufficiency",
        "causality",
        "completeness",
        "freshness_beyond_last_verified",
    ]


def test_claim_evidence_map_has_no_truth_verdict_fields():
    doc = build_claim_evidence_map(
        _registry_fixture(),
        registry_sha256="c" * 64,
        generated_at="2026-05-31T12:00:00Z",
    )
    field_names = _collect_field_names(doc)

    forbidden_field_names = {
        "supported",
        "unsupported",
        "true_claim",
        "false_claim",
        "proven",
    }
    assert forbidden_field_names.isdisjoint(field_names)


def test_produce_claim_evidence_map_from_doc_freshness_registry(tmp_path):
    registry_path = tmp_path / "docs" / "doc-freshness-registry.yml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        """
kind: lenskit.doc_freshness_registry
version: "1.0"
entries:
  - id: x
    doc: docs/a.md
    locator: l
    claim: c
    status: partial
    normative: false
    owner: o
    last_verified: "2026-05-31"
    evidence:
      - kind: text
        target: a.py::open marker
        implies: open
""".lstrip(),
        encoding="utf-8",
    )

    contracts_dir = tmp_path / "merger" / "lenskit" / "contracts"
    contracts_dir.mkdir(parents=True)
    source_schema = (
        Path(__file__).parent.parent / "contracts" / "doc-freshness-registry.v1.schema.json"
    )
    (contracts_dir / "doc-freshness-registry.v1.schema.json").write_text(
        source_schema.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    out = tmp_path / "out" / "bundle.claim_evidence_map.json"
    result = produce_claim_evidence_map(
        registry_path,
        out,
        generated_at="2026-05-31T10:00:00Z",
    )

    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert text.endswith("\n")

    from_disk = json.loads(text)
    assert result == from_disk
    jsonschema.validate(instance=from_disk, schema=_schema())
    assert from_disk["claims"][0]["requires_live_check"] is True


def test_produce_claim_evidence_map_generated_at_is_deterministic_from_registry(tmp_path):
        registry_path = tmp_path / "docs" / "doc-freshness-registry.yml"
        registry_path.parent.mkdir(parents=True)
        registry_path.write_text(
                (
                        "kind: lenskit.doc_freshness_registry\n"
                        "version: \"1.0\"\n"
                        "entries:\n"
                        "  - id: a\n"
                        "    doc: docs/a.md\n"
                        "    locator: a\n"
                        "    claim: a\n"
                        "    status: done\n"
                        "    normative: false\n"
                        "    owner: o\n"
                        "    last_verified: \"2026-05-30\"\n"
                        "    evidence:\n"
                        "      - kind: file\n"
                        "        target: docs/a.md\n"
                        "  - id: b\n"
                        "    doc: docs/b.md\n"
                        "    locator: b\n"
                        "    claim: b\n"
                        "    status: done\n"
                        "    normative: false\n"
                        "    owner: o\n"
                        "    last_verified: \"2026-05-31\"\n"
                        "    evidence:\n"
                        "      - kind: file\n"
                        "        target: docs/b.md\n"
                ),
                encoding="utf-8",
        )

        contracts_dir = tmp_path / "merger" / "lenskit" / "contracts"
        contracts_dir.mkdir(parents=True)
        source_schema = (
                Path(__file__).parent.parent / "contracts" / "doc-freshness-registry.v1.schema.json"
        )
        (contracts_dir / "doc-freshness-registry.v1.schema.json").write_text(
                source_schema.read_text(encoding="utf-8"),
                encoding="utf-8",
        )

        out1 = tmp_path / "out" / "a.claim_evidence_map.json"
        out2 = tmp_path / "out" / "b.claim_evidence_map.json"

        first = produce_claim_evidence_map(registry_path, out1)
        second = produce_claim_evidence_map(registry_path, out2)

        assert first["source"]["generated_at"] == "2026-05-31T00:00:00Z"
        assert first["source"]["generated_at"] == second["source"]["generated_at"]
        assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")


def test_produce_claim_evidence_map_raises_for_invalid_registry(tmp_path):
    registry_path = tmp_path / "docs" / "doc-freshness-registry.yml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("kind: not-valid\n", encoding="utf-8")

    contracts_dir = tmp_path / "merger" / "lenskit" / "contracts"
    contracts_dir.mkdir(parents=True)
    source_schema = (
        Path(__file__).parent.parent / "contracts" / "doc-freshness-registry.v1.schema.json"
    )
    (contracts_dir / "doc-freshness-registry.v1.schema.json").write_text(
        source_schema.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    out = tmp_path / "out" / "bundle.claim_evidence_map.json"
    with pytest.raises(ValueError, match="validation failed"):
        produce_claim_evidence_map(registry_path, out)
