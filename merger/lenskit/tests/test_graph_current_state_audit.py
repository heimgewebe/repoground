from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
AUDIT = REPO_ROOT / "docs/diagnostics/graph-current-state-audit.md"


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_graph_audit_names_existing_contracts_and_surfaces() -> None:
    text = AUDIT.read_text(encoding="utf-8")

    for path in (
        "merger/lenskit/contracts/architecture.graph.v1.schema.json",
        "merger/lenskit/contracts/architecture.graph_index.v1.schema.json",
        "merger/lenskit/contracts/entrypoints.v1.schema.json",
        "merger/lenskit/architecture/import_graph.py",
        "merger/lenskit/architecture/entrypoints.py",
        "merger/lenskit/architecture/graph_index.py",
    ):
        assert (REPO_ROOT / path).is_file()

    for contract in (
        "architecture.graph.v1.schema.json",
        "architecture.graph_index.v1.schema.json",
        "entrypoints.v1.schema.json",
    ):
        assert contract in text


def test_graph_audit_preserves_historical_g3_gap_and_tracks_current_slice() -> None:
    merge_source = _read("merger/lenskit/core/merge.py")
    producer = _read("merger/lenskit/architecture/bundle_sources.py")
    audit = AUDIT.read_text(encoding="utf-8")

    assert "generate_import_graph_document" not in merge_source
    assert "generate_entrypoints_document" not in merge_source
    assert "ensure_bundle_graph_sources(" in merge_source
    assert "generate_import_graph_document(" in producer
    assert "generate_entrypoints_document(" in producer
    assert '.with_suffix(".architecture_graph.json")' in producer
    assert '.with_suffix(".entrypoints.json")' in producer
    assert "_eligible_python_paths(" in producer
    assert "Automatic source-artifact emission | absent" in audit
    assert "Conditional bundle registration | implemented" in audit
    assert (
        REPO_ROOT / "docs/proofs/graph-bundle-source-production-proof.md"
    ).is_file()


def test_graph_audit_keeps_historical_stale_ranking_finding_after_g1_fix() -> None:
    query_source = _read("merger/lenskit/retrieval/query_core.py")
    runtime_contract = _read("docs/architecture/graph-runtime-contract.md")
    audit = AUDIT.read_text(encoding="utf-8")

    assert 'graph_status in ("ok", "stale_or_mismatched")' not in query_source
    assert 'graph_status == "ok"' in query_source
    assert "`stale_or_mismatched`" in runtime_contract
    assert "Ranking fällt auf Baseline zurück" in runtime_contract
    assert "still uses a Graph Index" in audit
    assert "Ignore mismatched Graph Indexes" in audit
    assert (
        REPO_ROOT / "docs/proofs/graph-stale-index-baseline-fallback-proof.md"
    ).is_file()


def test_graph_audit_tracks_exploratory_cli_provenance() -> None:
    cli_source = _read("merger/lenskit/cli/cmd_architecture.py")
    audit = AUDIT.read_text(encoding="utf-8")

    assert "uuid.uuid4" in cli_source
    assert '"0" * 64' in cli_source
    assert "random UUID-derived run ID" in audit
    assert "placeholder hash of 64 zeroes" in audit


def test_g2_compiler_validates_and_binds_both_sources() -> None:
    compiler = _read("merger/lenskit/architecture/graph_index.py")
    validation = _read("merger/lenskit/architecture/graph_source_validation.py")
    merge_source = _read("merger/lenskit/core/merge.py")

    assert "load_source(" in compiler
    assert '"architecture.graph.v1.schema.json"' in compiler
    assert '"entrypoints.v1.schema.json"' in compiler
    assert "require_coherence(" in compiler
    assert "dump_sha256 = _compute_file_sha256(dump_index_path)" in merge_source
    assert "expected_run_id=run_id" in merge_source
    assert "expected_canonical_sha256=dump_sha256" in merge_source
    assert "except (BundleGraphSourceError, GraphIndexCompilationError):" in merge_source
    assert "Draft7Validator" in validation
    assert '"validation_unavailable"' in validation
    assert '"provenance_mismatch"' in validation
    assert (
        REPO_ROOT / "docs/proofs/graph-provenance-coherent-compilation-proof.md"
    ).is_file()


def test_graph_audit_carries_measurement_boundaries_and_priorities() -> None:
    audit = AUDIT.read_text(encoding="utf-8")

    for value in (
        "361 / 360",
        "1,060",
        "360 / 700",
        "4,197",
        "1.0",
        "2 / 42",
        "366 / 694",
    ):
        assert value in audit

    for follow_up in (
        "G1 — Ignore mismatched Graph Indexes",
        "G2 — Provenance-coherent compilation",
        "G3 — Bundle-bound source production",
        "G4 — Resolution and layer quality",
        "G5 — Symbol and wider graph experiments",
    ):
        assert follow_up in audit

    for boundary in (
        "repository understanding",
        "graph or entrypoint completeness",
        "runtime reachability",
        "change impact",
        "test sufficiency",
        "regression absence",
    ):
        assert boundary in audit
