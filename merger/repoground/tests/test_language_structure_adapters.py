from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from collections import Counter
from collections.abc import Iterator, Mapping
from pathlib import Path

import jsonschema
import pytest

from merger.repoground.core import doctor
from merger.repoground.core.bash_structure_adapter import scan_bash_repository
from merger.repoground.core.language_structure import (
    build_language_structure_document,
    compose_language_structure_evidence,
    make_record,
    select_language_structure_evidence,
    source_range,
)
from merger.repoground.core.language_structure_benchmark import (
    _metric,
    _true_null_observation,
    decide_language_adapter_promotion,
    evaluate_language_structure_goldset,
    load_language_goldset,
)
from merger.repoground.core.language_structure_agent_benefit import (
    build_language_structure_agent_benefit,
    receipt_sha256,
)
from merger.repoground.core.rust_structure_adapter import (
    _rust_call_evidence,
    scan_rust_repository,
)

COMMIT = "b" * 40
DUMP_SHA = "c" * 64
MANIFEST = "fixture.bundle.manifest.json"
ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "merger" / "repoground" / "contracts"


def _kwargs() -> dict[str, str]:
    return {
        "repository_commit": COMMIT,
        "bundle_manifest": MANIFEST,
        "canonical_dump_index_sha256": DUMP_SHA,
    }


def _selection_record(
    *,
    language: str,
    symbol: str,
    source_path: str,
    line: int = 1,
    relation: str = "definition",
    target_symbol: str | None = None,
) -> dict:
    adapter_id = {
        "bash": "bash-static-structure",
        "rust": "rust-static-structure",
    }[language]
    return make_record(
        language=language,
        adapter_id=adapter_id,
        adapter_version="1.0",
        record_type="symbol" if relation == "definition" else "relation",
        relation=relation,
        symbol=symbol,
        target_symbol=target_symbol,
        symbol_kind="function",
        source_path=source_path,
        source_range_value=source_range(
            line=line,
            start_character=0,
            end_character=len(symbol),
        ),
        evidence_level="S0",
        confidence=0.7,
        basis="ranking regression fixture",
        **_kwargs(),
    )


def _normalized_scip_artifact() -> dict:
    return {
        "kind": "repoground.scip_symbol_relations",
        "version": "1.0",
        "authority": "navigation_index",
        "canonicality": "derived",
        "status": "available",
        "source": {
            "format": "decoded_scip_protobuf_json",
            "protocol": "SCIP",
            "protocol_version": "0.4.0",
            "index_sha256": "e" * 64,
            "repository_commit": COMMIT,
            "indexer": {
                "name": "scip-rust",
                "version": "1.0",
                "arguments_sha256": "f" * 64,
            },
            "project_root_sha256": "a" * 64,
            "text_document_encoding": "UTF-8",
        },
        "languages": ["rust"],
        "records": [
            {
                "language": "rust",
                "record_type": "occurrence",
                "relation": "reference",
                "symbol": "scip-rust cargo demo 1 src/run().",
                "target_symbol": "scip-rust cargo demo 1 src/Runner#",
                "roles": [],
                "source": {
                    "path": "src/lib.rs",
                    "range": {
                        "start_line": 1,
                        "end_line": 1,
                        "start_character": 3,
                        "end_character": 6,
                        "position_encoding": "UTF8CodeUnitOffsetFromLineStart",
                    },
                },
                "source_rule": "scip_occurrence_symbol_roles",
            }
        ],
        "record_count": 1,
        "degradations": [],
        "consumer_enablement": {
            "requires_language_benchmark": True,
            "default_promoted": False,
            "eligible_for_review": False,
        },
        "does_not_establish": [
            f"normalized_scip_boundary_{index}" for index in range(12)
        ],
    }


def test_bash_static_subset_emits_functions_calls_and_literal_dependencies(tmp_path):
    script = tmp_path / "scripts" / "deploy.sh"
    script.parent.mkdir()
    script.write_text(
        "#!/usr/bin/env bash\n"
        "source ./lib.sh\n"
        "prepare() {\n  printf ok\n}\n"
        "run() {\n  prepare\n}\n",
        encoding="utf-8",
    )

    result = scan_bash_repository(tmp_path, **_kwargs())

    assert {record["relation"] for record in result["records"]} == {
        "definition",
        "dependency",
        "call",
    }
    prepare = next(
        record for record in result["records"] if record["symbol"] == "prepare"
    )
    assert prepare["language"] == "bash"
    assert prepare["adapter"] == {"id": "bash-static-structure", "version": "1.0"}
    assert prepare["provenance"]["repository_commit"] == COMMIT
    assert prepare["provenance"]["bundle_manifest"] == MANIFEST
    assert prepare["evidence"]["level"] == "S0"
    assert prepare["source"]["range"]["start_line"] == 3


def test_bash_dynamic_constructs_are_omitted_with_reasons(tmp_path):
    script = tmp_path / "dynamic.sh"
    script.write_text(
        '#!/bin/bash\nsource "$LIB"\neval "$ACTION"\nresult=$(helper)\n',
        encoding="utf-8",
    )

    result = scan_bash_repository(tmp_path, **_kwargs())

    reasons = {item["reason"] for item in result["degradations"]}
    assert "dynamic_source_target" in reasons
    assert "eval_not_resolved" in reasons
    assert "command_substitution_not_resolved" in reasons
    assert result["status"] == "degraded"


def test_rust_static_subset_is_low_evidence_and_macros_are_visible(tmp_path):
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text(
        "use crate::config::Config;\n"
        "pub struct Runner {}\n"
        "fn helper() {}\n"
        "pub fn run() {\n"
        "    helper();\n"
        '    println!("ok");\n'
        "}\n",
        encoding="utf-8",
    )

    result = scan_rust_repository(tmp_path, **_kwargs())

    assert any(record["symbol"] == "Runner" for record in result["records"])
    call = next(record for record in result["records"] if record["relation"] == "call")
    assert call["target_symbol"] == "helper"
    assert call["evidence"]["level"] == "S0"
    reasons = {item["reason"] for item in result["degradations"]}
    assert "macro_invocation_not_expanded" in reasons
    assert "scip_evidence_not_supplied" in reasons


def test_rust_lexer_does_not_invent_calls_from_comments_or_strings(tmp_path):
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text(
        'fn helper() {}\nfn run() {\n    // helper();\n    let text = "helper()";\n}\n',
        encoding="utf-8",
    )

    result = scan_rust_repository(tmp_path, **_kwargs())

    assert not [record for record in result["records"] if record["relation"] == "call"]


def test_rust_call_evidence_looks_up_only_scanned_candidates():
    class LookupOnlyFunctions(Mapping[str, list[tuple[int, int, int]]]):
        def __getitem__(self, key: str) -> list[tuple[int, int, int]]:
            if key != "known":
                raise AssertionError(f"unexpected function lookup: {key}")
            return [(1, 0, 5)]

        def __iter__(self) -> Iterator[str]:
            raise AssertionError("function mapping must not be enumerated")

        def __len__(self) -> int:
            raise AssertionError("function mapping size must not be inspected")

        def keys(self):
            raise AssertionError("function mapping keys must not be inspected")

    records, degradations = _rust_call_evidence(
        "known();",
        line_number=7,
        path="src/lib.rs",
        functions=LookupOnlyFunctions(),
        binding=_kwargs(),
    )

    assert degradations == []
    assert [record["target_symbol"] for record in records] == ["known"]
    assert records[0]["source"]["range"] == {
        "start_line": 7,
        "end_line": 7,
        "start_character": 0,
        "end_character": 5,
        "coordinate_basis": "source_lines_1_based_unicode_characters",
    }


def test_rust_call_evidence_preserves_candidate_order_dedup_and_unknown_omission():
    records, degradations = _rust_call_evidence(
        "zeta(); missing(); alpha(); alpha();",
        line_number=11,
        path="src/lib.rs",
        functions={
            "zeta": [(1, 0, 4)],
            "alpha": [(2, 0, 5)],
            "unused": [(3, 0, 6)],
        },
        binding=_kwargs(),
    )

    assert degradations == []
    assert [record["target_symbol"] for record in records] == ["alpha", "zeta"]
    assert [record["source"]["range"]["start_character"] for record in records] == [
        19,
        0,
    ]


def test_rust_scip_records_are_lifted_as_s1(tmp_path):
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text("fn run() {}\n", encoding="utf-8")
    scip = _normalized_scip_artifact()
    jsonschema.validate(
        scip,
        json.loads(
            (CONTRACTS / "scip-symbol-relations.v1.schema.json").read_text(
                encoding="utf-8"
            )
        ),
    )

    result = scan_rust_repository(tmp_path, scip_artifact=scip, **_kwargs())
    document = build_language_structure_document(
        tmp_path,
        rust_scip_artifact=scip,
        run_id="scip-contract",
        **_kwargs(),
    )
    language_schema = json.loads(
        (CONTRACTS / "language-structure.v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(document, language_schema)

    lifted = next(
        record
        for record in result["records"]
        if record["adapter"]["id"] == "rust-scip-structure"
    )
    assert lifted["evidence"]["level"] == "S1"
    assert lifted["evidence"]["confidence"] == 0.98
    assert lifted["source"]["range"]["position_encoding"] == (
        "UTF8CodeUnitOffsetFromLineStart"
    )
    normalized_sha256 = hashlib.sha256(
        json.dumps(
            scip,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert lifted["provenance"]["source_artifact"]["sha256"] == normalized_sha256
    invalid_s1 = copy.deepcopy(document)
    invalid_s1_record = next(
        record
        for record in invalid_s1["records"]
        if record["adapter"]["id"] == "rust-scip-structure"
    )
    invalid_s1_record["source"]["range"].pop("position_encoding")
    assert not jsonschema.Draft7Validator(language_schema).is_valid(invalid_s1)


@pytest.mark.parametrize(
    "mutation",
    [
        "authority",
        "status",
        "index_sha256",
        "record_count",
        "position_encoding",
        "repository_commit",
        "requires_language_benchmark",
    ],
)
def test_rust_scip_s1_requires_complete_normalized_binding(tmp_path, mutation):
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text("fn run() {}\n", encoding="utf-8")
    scip = copy.deepcopy(_normalized_scip_artifact())
    if mutation == "authority":
        scip["authority"] = "runtime_observation"
    elif mutation == "status":
        scip["status"] = "unknown"
    elif mutation == "index_sha256":
        scip["source"]["index_sha256"] = "invalid"
    elif mutation == "record_count":
        scip["record_count"] = 2
    elif mutation == "position_encoding":
        scip["records"][0]["source"]["range"].pop("position_encoding")
    elif mutation == "repository_commit":
        scip["source"]["repository_commit"] = "d" * 40
    else:
        scip["consumer_enablement"]["requires_language_benchmark"] = False

    result = scan_rust_repository(tmp_path, scip_artifact=scip, **_kwargs())

    assert not [
        record for record in result["records"] if record["evidence"]["level"] == "S1"
    ]
    assert any(
        item["reason"] in {"scip_contract_invalid", "scip_repository_commit_mismatch"}
        for item in result["degradations"]
    )


def test_mixed_evidence_budget_preserves_provenance_ranges_and_uncertainty(tmp_path):
    (tmp_path / "x.sh").write_text("#!/bin/bash\nrun() { :; }\n", encoding="utf-8")
    (tmp_path / "x.rs").write_text("fn run() {}\n", encoding="utf-8")
    document = build_language_structure_document(
        tmp_path,
        run_id="fixture",
        **_kwargs(),
    )

    composed = compose_language_structure_evidence(
        document,
        max_bytes=20_000,
        bundle_manifest_sha256="d" * 64,
    )

    languages = {record["language"] for record in composed["evidence"]["records"]}
    assert languages == {"bash", "rust"}
    for record in composed["evidence"]["records"]:
        assert record["source"]["range"]["start_line"] >= 1
        assert record["provenance"]["bundle_manifest_sha256"] == "d" * 64
        assert "uncertainty" in record
        assert "confidence" in record["evidence"]
    assert composed["budget"]["used_bytes"] <= composed["budget"]["hard_limit_bytes"]

    fair = compose_language_structure_evidence(
        document,
        max_bytes=20_000,
        max_items=2,
        bundle_manifest_sha256="d" * 64,
    )
    assert {item["language"] for item in fair["evidence"]["records"]} == {
        "bash",
        "rust",
    }


def test_specific_symbol_match_precedes_generic_language_matches() -> None:
    records = [
        _selection_record(
            language="rust",
            symbol=f"alpha_{index:02d}",
            source_path=f"src/{index:02d}.rs",
        )
        for index in range(12)
    ]
    records.append(
        _selection_record(
            language="rust",
            symbol="helper",
            source_path="src/zz_helper.rs",
        )
    )

    selected = select_language_structure_evidence(
        {"status": "available", "records": records, "degradations": []},
        terms=["rust", "helper"],
        max_items=3,
    )

    assert selected["records"][0]["symbol"] == "helper"
    assert any(record["symbol"] == "helper" for record in selected["records"])
    assert selected["truncated"] is True


@pytest.mark.parametrize("specific_field", ["target", "path", "relation"])
def test_specific_explicit_field_matches_precede_generic_language_match(
    specific_field: str,
) -> None:
    generic = _selection_record(
        language="rust",
        symbol="generic",
        source_path="src/a.rs",
    )
    kwargs = {
        "language": "rust",
        "symbol": "owner",
        "source_path": "src/z.rs",
    }
    query = "needle"
    if specific_field == "target":
        kwargs["target_symbol"] = "needle"
        kwargs["relation"] = "call"
    elif specific_field == "path":
        kwargs["source_path"] = "src/needle.rs"
    else:
        kwargs["relation"] = "call"
        query = "call"
    specific = _selection_record(**kwargs)

    selected = select_language_structure_evidence(
        {
            "status": "available",
            "records": [generic, specific],
            "degradations": [],
        },
        terms=["rust", query],
        max_items=1,
    )

    assert selected["records"] == [specific]


def test_relevance_ties_have_input_order_independent_tiebreaks() -> None:
    records = [
        _selection_record(
            language="rust",
            symbol="helper",
            source_path=path,
        )
        for path in ("src/z.rs", "src/a.rs", "src/m.rs")
    ]

    first = select_language_structure_evidence(
        {"status": "available", "records": records, "degradations": []},
        terms=["helper"],
        max_items=3,
    )
    second = select_language_structure_evidence(
        {
            "status": "available",
            "records": list(reversed(records)),
            "degradations": [],
        },
        terms=["helper"],
        max_items=3,
    )

    first_paths = [record["source"]["path"] for record in first["records"]]
    second_paths = [record["source"]["path"] for record in second["records"]]
    assert first_paths == ["src/a.rs", "src/m.rs", "src/z.rs"]
    assert second_paths == first_paths


def test_relevance_ties_interleave_languages_before_item_limit() -> None:
    records = [
        _selection_record(
            language=language,
            symbol="helper",
            source_path=f"{language}/{index:02d}.{'sh' if language == 'bash' else 'rs'}",
        )
        for language in ("bash", "rust")
        for index in range(4)
    ]

    selected = select_language_structure_evidence(
        {"status": "available", "records": records, "degradations": []},
        terms=["helper"],
        max_items=4,
    )

    assert [record["language"] for record in selected["records"]] == [
        "bash",
        "rust",
        "bash",
        "rust",
    ]


def test_common_record_contract_rejects_nonfinite_confidence():
    with pytest.raises(ValueError, match="confidence"):
        make_record(
            language="bash",
            adapter_id="bash-static-structure",
            adapter_version="1.0",
            record_type="symbol",
            relation="definition",
            symbol="run",
            source_path="run.sh",
            source_range_value=source_range(line=1, start_character=0, end_character=3),
            evidence_level="S0",
            confidence=float("nan"),
            basis="test",
            **_kwargs(),
        )


def test_goldset_metrics_and_true_nulls_count_duplicate_false_positives():
    actual = Counter({("duplicate",): 2})
    expected = Counter({("duplicate",): 1})

    metric = _metric(actual, expected)
    null_observation = _true_null_observation([{}, {}])

    assert metric["true_positive"] == 1
    assert metric["false_positive"] == 1
    assert metric["actual"] == 2
    assert null_observation == {"pass": False, "false_positive_records": 2}


def test_doctor_sees_new_adapters_without_making_them_required():
    checks = doctor.check_optional_adapters()
    by_id = {check["id"]: check for check in checks}

    assert by_id["adapter:rust_structure"]["status"] == "available"
    assert by_id["adapter:bash_structure"]["status"] == "available"
    assert by_id["adapter:rust_structure"]["optional"] is True
    assert by_id["adapter:bash_structure"]["optional"] is True


def test_doctor_contains_unexpected_optional_import_failure(monkeypatch):
    rust_module = "merger.repoground.core.rust_structure_adapter"
    monkeypatch.setattr(
        doctor, "_module_available", lambda module: module == rust_module
    )

    def broken_import(_module):
        raise OSError("broken optional loader")

    monkeypatch.setattr(doctor.importlib, "import_module", broken_import)
    checks = doctor.check_optional_adapters()
    rust = next(item for item in checks if item["id"] == "adapter:rust_structure")
    bash = next(item for item in checks if item["id"] == "adapter:bash_structure")
    assert rust["status"] == "blocked"
    assert rust["evidence"]["error_type"] == "OSError"
    assert bash["status"] == "degraded"
    assert all(item["optional"] for item in checks)


def test_doctor_blocks_unexpected_optional_discovery_failure(monkeypatch):
    rust_module = "merger.repoground.core.rust_structure_adapter"

    def broken_discovery(module):
        if module == rust_module:
            raise OSError("broken optional finder")
        return False

    monkeypatch.setattr(doctor, "_module_available", broken_discovery)
    checks = doctor.check_optional_adapters()
    rust = next(item for item in checks if item["id"] == "adapter:rust_structure")

    assert rust["status"] == "blocked"
    assert rust["cause"] == "adapter_discovery_failed"
    assert rust["evidence"]["error_type"] == "OSError"
    assert rust["optional"] is True
    assert doctor._overall_status(checks) == "available"


def _git(repo, *args):
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def test_benchmark_separates_quality_null_cost_and_fail_closed_promotion(tmp_path):
    fixtures = {
        "bash-positive/main.sh": "#!/bin/bash\nrun() { :; }\nrun\n",
        "bash-positive-2/main.sh": "#!/bin/bash\nrun() { :; }\nrun\n",
        "bash-ambiguous/main.sh": (
            "#!/bin/bash\nchoose() { :; }\nchoose() { :; }\nchoose\n"
        ),
        "bash-dynamic/main.sh": '#!/bin/bash\nrun() { :; }\neval "$ACTION"\n',
        "bash-null/README.txt": "no shell\n",
        "rust-positive/main.rs": "fn helper() {}\npub fn run() {\n helper();\n}\n",
        "rust-ambiguous/main.rs": (
            "fn choose() {}\nfn choose() {}\npub fn run() {\n choose();\n}\n"
        ),
        "rust-dynamic/main.rs": 'pub fn run() {\n println!("x");\n}\n',
        "rust-null/README.txt": "no rust\n",
    }
    for relative, content in fixtures.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    cases = [
        {
            "id": "bash-positive",
            "language": "bash",
            "size_class": "small",
            "case_class": "positive",
            "fixture_root": "bash-positive",
            "expected_records": [
                {
                    "language": "bash",
                    "relation": "definition",
                    "symbol": "run",
                    "target_symbol": None,
                    "path": "main.sh",
                    "start_line": 2,
                    "end_line": 2,
                    "start_character": 0,
                    "end_character": 3,
                },
                {
                    "language": "bash",
                    "relation": "call",
                    "symbol": "main.sh",
                    "target_symbol": "run",
                    "path": "main.sh",
                    "start_line": 3,
                    "end_line": 3,
                    "start_character": 0,
                    "end_character": 3,
                },
            ],
            "expected_degradation_reasons": [],
        },
        {
            "id": "bash-positive-2",
            "language": "bash",
            "size_class": "small",
            "case_class": "positive",
            "fixture_root": "bash-positive-2",
            "expected_records": [
                {
                    "language": "bash",
                    "relation": "definition",
                    "symbol": "run",
                    "target_symbol": None,
                    "path": "main.sh",
                    "start_line": 2,
                    "end_line": 2,
                    "start_character": 0,
                    "end_character": 3,
                },
                {
                    "language": "bash",
                    "relation": "call",
                    "symbol": "main.sh",
                    "target_symbol": "run",
                    "path": "main.sh",
                    "start_line": 3,
                    "end_line": 3,
                    "start_character": 0,
                    "end_character": 3,
                },
            ],
            "expected_degradation_reasons": [],
        },
        {
            "id": "bash-ambiguous",
            "language": "bash",
            "size_class": "small",
            "case_class": "ambiguous",
            "fixture_root": "bash-ambiguous",
            "expected_records": [
                {
                    "language": "bash",
                    "relation": "definition",
                    "symbol": "choose",
                    "target_symbol": None,
                    "path": "main.sh",
                    "start_line": 2,
                    "end_line": 2,
                    "start_character": 0,
                    "end_character": 6,
                },
                {
                    "language": "bash",
                    "relation": "definition",
                    "symbol": "choose",
                    "target_symbol": None,
                    "path": "main.sh",
                    "start_line": 3,
                    "end_line": 3,
                    "start_character": 0,
                    "end_character": 6,
                },
            ],
            "expected_degradation_reasons": [
                "duplicate_function_definition",
                "ambiguous_function_call_target",
            ],
        },
        {
            "id": "bash-dynamic",
            "language": "bash",
            "size_class": "small",
            "case_class": "dynamic",
            "fixture_root": "bash-dynamic",
            "expected_records": [
                {
                    "language": "bash",
                    "relation": "definition",
                    "symbol": "run",
                    "target_symbol": None,
                    "path": "main.sh",
                    "start_line": 2,
                    "end_line": 2,
                    "start_character": 0,
                    "end_character": 3,
                }
            ],
            "expected_degradation_reasons": ["eval_not_resolved"],
        },
        {
            "id": "bash-null",
            "language": "bash",
            "size_class": "small",
            "case_class": "null",
            "fixture_root": "bash-null",
            "expected_records": [],
            "expected_degradation_reasons": [],
        },
        {
            "id": "rust-positive",
            "language": "rust",
            "size_class": "small",
            "case_class": "positive",
            "fixture_root": "rust-positive",
            "expected_records": [
                {
                    "language": "rust",
                    "relation": "definition",
                    "symbol": "helper",
                    "target_symbol": None,
                    "path": "main.rs",
                    "start_line": 1,
                    "end_line": 1,
                    "start_character": 3,
                    "end_character": 9,
                },
                {
                    "language": "rust",
                    "relation": "definition",
                    "symbol": "run",
                    "target_symbol": None,
                    "path": "main.rs",
                    "start_line": 2,
                    "end_line": 2,
                    "start_character": 7,
                    "end_character": 10,
                },
                {
                    "language": "rust",
                    "relation": "call",
                    "symbol": "main.rs",
                    "target_symbol": "helper",
                    "path": "main.rs",
                    "start_line": 3,
                    "end_line": 3,
                    "start_character": 1,
                    "end_character": 7,
                },
            ],
            "expected_degradation_reasons": ["scip_evidence_not_supplied"],
        },
        {
            "id": "rust-ambiguous",
            "language": "rust",
            "size_class": "small",
            "case_class": "ambiguous",
            "fixture_root": "rust-ambiguous",
            "expected_records": [
                {
                    "language": "rust",
                    "relation": "definition",
                    "symbol": "choose",
                    "target_symbol": None,
                    "path": "main.rs",
                    "start_line": 1,
                    "end_line": 1,
                    "start_character": 3,
                    "end_character": 9,
                },
                {
                    "language": "rust",
                    "relation": "definition",
                    "symbol": "choose",
                    "target_symbol": None,
                    "path": "main.rs",
                    "start_line": 2,
                    "end_line": 2,
                    "start_character": 3,
                    "end_character": 9,
                },
                {
                    "language": "rust",
                    "relation": "definition",
                    "symbol": "run",
                    "target_symbol": None,
                    "path": "main.rs",
                    "start_line": 3,
                    "end_line": 3,
                    "start_character": 7,
                    "end_character": 10,
                },
            ],
            "expected_degradation_reasons": [
                "duplicate_function_definition",
                "ambiguous_function_call_target",
                "scip_evidence_not_supplied",
            ],
        },
        {
            "id": "rust-dynamic",
            "language": "rust",
            "size_class": "small",
            "case_class": "dynamic",
            "fixture_root": "rust-dynamic",
            "expected_records": [
                {
                    "language": "rust",
                    "relation": "definition",
                    "symbol": "run",
                    "target_symbol": None,
                    "path": "main.rs",
                    "start_line": 1,
                    "end_line": 1,
                    "start_character": 7,
                    "end_character": 10,
                }
            ],
            "expected_degradation_reasons": [
                "macro_invocation_not_expanded",
                "scip_evidence_not_supplied",
            ],
        },
        {
            "id": "rust-null",
            "language": "rust",
            "size_class": "small",
            "case_class": "null",
            "fixture_root": "rust-null",
            "expected_records": [],
            "expected_degradation_reasons": [],
        },
    ]
    goldset = {
        "kind": "repoground.language_structure_goldset",
        "version": "1.0",
        "id": "unit",
        "cases": cases,
    }
    goldset_path = tmp_path / "goldset.json"
    goldset_path.write_text(json.dumps(goldset), encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(
        tmp_path,
        "-c",
        "user.name=RepoGround Test",
        "-c",
        "user.email=repoground@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    revision = _git(tmp_path, "rev-parse", "HEAD")
    loaded = load_language_goldset(goldset_path)
    with pytest.raises(ValueError, match="does not equal repository HEAD"):
        evaluate_language_structure_goldset(
            loaded,
            repo_root=tmp_path,
            source_revision="a" * 40,
        )
    dirty_marker = tmp_path / "untracked.txt"
    dirty_marker.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dirty or contains untracked"):
        evaluate_language_structure_goldset(
            loaded,
            repo_root=tmp_path,
            source_revision=revision,
        )
    dirty_marker.unlink()
    report = evaluate_language_structure_goldset(
        loaded, repo_root=tmp_path, source_revision=revision
    )
    jsonschema.validate(
        report,
        json.loads(
            (CONTRACTS / "language-structure-benchmark.v1.schema.json").read_text(
                encoding="utf-8"
            )
        ),
    )

    assert report["metrics"]["aggregate"]["symbol"]["true_positive"] == 11
    assert report["metrics"]["aggregate"]["relations"]["true_positive"] == 3
    assert report["metrics"]["aggregate"]["ranges"]["recall"] == 1.0
    assert report["true_nulls"] == {
        "case_count": 2,
        "pass_count": 2,
        "false_positive_records": 0,
    }
    assert report["promotion"]["status"] == "keep_optional"
    assert set(report["costs"]["per_language"]) == {"bash", "rust"}
    assert report["costs"]["runtime_environment"]["python_version"]
    assert report["degradation_expectations"] == {
        "all_expected_present": True,
        "no_unexpected": True,
        "exact_match": True,
    }
    case_ids = [item["id"] for item in report["case_results"]]
    fallback_failure_count = max(1, (len(case_ids) + 9) // 10)
    treatment_sha256 = "9" * 64
    comparison = {
        "same_model": True,
        "same_prompt": True,
        "same_budget": True,
        "same_source_revision": True,
        "same_grader": True,
        "model_identity_sha256": "1" * 64,
        "harness_identity_sha256": "2" * 64,
        "environment_identity_sha256": "3" * 64,
        "grader_identity_sha256": "4" * 64,
        "grader_rubric_sha256": "5" * 64,
    }

    def paired_result(
        case_id: str,
        task_sha256: str,
        route: str,
        treatment_artifact_sha256: str | None,
        *,
        success: bool,
    ) -> dict:
        runner = {
            "kind": "repoground.language_structure_agent_run_receipt",
            "version": "1.0",
            "source_revision": revision,
            "goldset_sha256": report["goldset_sha256"],
            "task_sha256": task_sha256,
            "route": route,
            "model_identity_sha256": comparison["model_identity_sha256"],
            "harness_identity_sha256": comparison["harness_identity_sha256"],
            "environment_identity_sha256": comparison["environment_identity_sha256"],
            "prompt_sha256": hashlib.sha256(
                f"prompt:{case_id}".encode("utf-8")
            ).hexdigest(),
            "budget_sha256": "6" * 64,
            "control_context_sha256": hashlib.sha256(
                f"control:{case_id}".encode("utf-8")
            ).hexdigest(),
            "treatment_artifact_sha256": treatment_artifact_sha256,
            "output_sha256": hashlib.sha256(
                f"output:{case_id}:{route}".encode("utf-8")
            ).hexdigest(),
            "completed": True,
        }
        grader = {
            "kind": "repoground.language_structure_agent_grader_receipt",
            "version": "1.0",
            "source_revision": revision,
            "goldset_sha256": report["goldset_sha256"],
            "task_sha256": task_sha256,
            "route": route,
            "runner_receipt_sha256": receipt_sha256(runner),
            "output_sha256": runner["output_sha256"],
            "grader_identity_sha256": comparison["grader_identity_sha256"],
            "grader_rubric_sha256": comparison["grader_rubric_sha256"],
            "verdict": "pass" if success else "fail",
        }
        return {"runner_receipt": runner, "grader_receipt": grader}

    pair_document = {
        "kind": "repoground.language_structure_agent_benefit_pairs",
        "version": "1.0",
        "measurement_id": "unit-paired-benefit",
        "source_revision": revision,
        "goldset_sha256": report["goldset_sha256"],
        "fallback_route": "text_fallback",
        "candidate_route": "language_structure_v1",
        "comparison": comparison,
        "treatment": {
            "variable": "language_structure_json",
            "fallback_excludes": True,
            "candidate_includes": True,
            "candidate_artifact_sha256": treatment_sha256,
        },
        "cases": [],
        "does_not_establish": [
            "default_activation",
            "causal_generalization_beyond_bound_cases",
            "receipt_hashes_do_not_attest_runner_or_grader_honesty",
        ],
    }
    for index, case_id in enumerate(case_ids):
        task_sha256 = hashlib.sha256(case_id.encode("utf-8")).hexdigest()
        pair_document["cases"].append(
            {
                "id": case_id,
                "task_sha256": task_sha256,
                "fallback": paired_result(
                    case_id,
                    task_sha256,
                    "text_fallback",
                    None,
                    success=index >= fallback_failure_count,
                ),
                "candidate": paired_result(
                    case_id,
                    task_sha256,
                    "language_structure_v1",
                    treatment_sha256,
                    success=True,
                ),
            }
        )
    benefit = build_language_structure_agent_benefit(
        pair_document,
        source_revision=revision,
        goldset_sha256=report["goldset_sha256"],
        expected_case_ids=case_ids,
    )
    legacy_aggregate_only = {
        "kind": "repoground.language_structure_agent_benefit",
        "version": "1.0",
        "source_revision": revision,
        "goldset_sha256": report["goldset_sha256"],
        "sample_count": report["case_count"],
        "fallback_route": "text_fallback",
        "candidate_route": "language_structure_v1",
        "fallback_success_rate": 0.0,
        "candidate_success_rate": 1.0,
    }
    legacy_decision = decide_language_adapter_promotion(
        report, agent_benefit=legacy_aggregate_only
    )
    assert legacy_decision["status"] == "keep_optional"
    assert legacy_decision["reason"] == "agent_benefit_binding_invalid"

    decision = decide_language_adapter_promotion(report, agent_benefit=benefit)
    assert decision["status"] == "eligible_for_explicit_promotion_review"
    assert decision["broad_activation_eligible"] is True
    assert decision["default_promoted"] is False

    unexpected_degradation = json.loads(json.dumps(report))
    unexpected_degradation["degradation_expectations"]["no_unexpected"] = False
    unexpected_degradation["degradation_expectations"]["exact_match"] = False
    assert (
        decide_language_adapter_promotion(
            unexpected_degradation, agent_benefit=benefit
        )["status"]
        == "keep_optional"
    )

    nonfinite_report = json.loads(json.dumps(report))
    nonfinite_report["metrics"]["aggregate"]["relations"]["precision"] = float("inf")
    assert (
        decide_language_adapter_promotion(nonfinite_report, agent_benefit=benefit)[
            "status"
        ]
        == "keep_optional"
    )

    nonfinite_symbol_precision = json.loads(json.dumps(report))
    nonfinite_symbol_precision["metrics"]["aggregate"]["symbol"]["precision"] = float(
        "nan"
    )
    assert (
        decide_language_adapter_promotion(
            nonfinite_symbol_precision, agent_benefit=benefit
        )["status"]
        == "keep_optional"
    )

    nonfinite_case_cost = json.loads(json.dumps(report))
    nonfinite_case_cost["case_results"][0]["costs"]["latency_ms"] = float("inf")
    assert (
        decide_language_adapter_promotion(nonfinite_case_cost, agent_benefit=benefit)[
            "status"
        ]
        == "keep_optional"
    )

    inconsistent_counts = json.loads(json.dumps(report))
    inconsistent_counts["metrics"]["aggregate"]["ranges"]["actual"] += 1
    assert (
        decide_language_adapter_promotion(inconsistent_counts, agent_benefit=benefit)[
            "status"
        ]
        == "keep_optional"
    )

    malformed_report = json.loads(json.dumps(report))
    malformed_report["goldset_sha256"] = "z" * 64
    malformed_benefit = dict(benefit, goldset_sha256="z" * 64)
    assert (
        decide_language_adapter_promotion(
            malformed_report, agent_benefit=malformed_benefit
        )["status"]
        == "keep_optional"
    )

    benefit["summary"]["candidate_success_rate"] = float("nan")
    assert (
        decide_language_adapter_promotion(report, agent_benefit=benefit)["status"]
        == "keep_optional"
    )


def test_checked_in_goldset_is_schema_valid_and_covers_required_classes():
    path = ROOT / "docs" / "retrieval" / "repoground_agent_utility_t021_goldset.v1.json"
    goldset = load_language_goldset(path)
    jsonschema.validate(
        goldset,
        json.loads(
            (CONTRACTS / "language-structure-goldset.v1.schema.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    assert {case["case_class"] for case in goldset["cases"]} == {
        "positive",
        "ambiguous",
        "dynamic",
        "null",
    }
    for language in ("bash", "rust"):
        assert {
            case["case_class"]
            for case in goldset["cases"]
            if case["language"] == language
        } == {"positive", "ambiguous", "dynamic", "null"}
