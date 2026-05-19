import json
import jsonschema
from pathlib import Path
from merger.lenskit.architecture.entrypoints import extract_entrypoints_with_stats, generate_entrypoints_document

def test_extract_entrypoints():
    repo_root = Path(__file__).parent / "fixtures" / "entrypoints_test_project"

    eps, skipped_count, skipped_errors = extract_entrypoints_with_stats(repo_root)

    # Assert deterministic sort order by id
    # Note that module_main_src_module___main___py is no longer double-counted as cli.
    assert [e["id"] for e in eps] == [
        "cli_cli_py",
        "module_main_src_module___main___py",
    ]

    # Check that invalid.py is recorded as skipped
    assert skipped_count == 1
    assert any("invalid.py" in e for e in skipped_errors)

    cli_py = next((e for e in eps if e["id"] == "cli_cli_py"), None)
    assert cli_py is not None
    assert cli_py["type"] == "cli"
    assert cli_py["path"] == "cli.py"
    assert cli_py["evidence_level"] == "S1"
    assert "start_line" in cli_py["evidence"]

    module_main = next((e for e in eps if e["id"] == "module_main_src_module___main___py"), None)
    assert module_main is not None
    assert module_main["type"] == "module_main"
    assert module_main["path"] == "src/module/__main__.py"
    assert module_main["evidence_level"] == "S0"


def test_entrypoints_document_matches_schema():
    repo_root = Path(__file__).parent / "fixtures" / "entrypoints_test_project"

    doc = generate_entrypoints_document(repo_root, "test_run", "0" * 64)

    schema_path = Path(__file__).parent.parent / "contracts" / "entrypoints.v1.schema.json"
    with schema_path.open() as f:
        schema = json.load(f)

    jsonschema.validate(instance=doc, schema=schema)

    assert doc["kind"] == "lenskit.entrypoints"
    assert len(doc["entrypoints"]) == 2
    assert doc["skipped_files_count"] == 1
