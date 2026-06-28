from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}")
    write(path, content.replace(old, new, 1))


def patch_graph_index() -> None:
    path = "merger/lenskit/architecture/graph_index.py"
    content = read(path)
    content = content.replace("import hashlib\n", "", 1)

    start = content.index("def _sibling_dump_index(")
    end = content.index("def compile_graph_index(", start)
    content = content[:start] + content[end:]

    inference = """    if expected_run_id is None and expected_canonical_sha256 is None:\n        expected_run_id, expected_canonical_sha256 = _infer_bundle_provenance(\n            graph_path,\n            entrypoints_path,\n        )\n"""
    if inference not in content:
        raise RuntimeError("graph_index.py: implicit provenance inference block missing")
    content = content.replace(inference, "", 1)
    write(path, content)


def patch_merge() -> None:
    path = "merger/lenskit/core/merge.py"
    replace_once(
        path,
        "        from ..architecture.graph_index import compile_graph_index\n",
        """        from ..architecture.graph_index import (\n            GraphIndexCompilationError,\n            compile_graph_index,\n        )\n""",
    )
    replace_once(
        path,
        "            graph_index_data = compile_graph_index(arch_graph_path, entrypoints_path)\n",
        """            graph_index_data = compile_graph_index(\n                arch_graph_path,\n                entrypoints_path,\n                expected_run_id=run_id,\n                expected_canonical_sha256=_compute_file_sha256(dump_index_path),\n            )\n""",
    )
    replace_once(
        path,
        """    except ImportError as e:\n        if debug:\n            print(f\"Skipping graph index artifact: architecture module not available ({e})\", file=sys.stderr)\n    except Exception as e:\n""",
        """    except ImportError as e:\n        if debug:\n            print(f\"Skipping graph index artifact: architecture module not available ({e})\", file=sys.stderr)\n    except GraphIndexCompilationError:\n        raise\n    except Exception as e:\n""",
    )


def patch_tests() -> None:
    replace_once(
        "merger/lenskit/tests/test_graph_bundle_integration.py",
        '    assert caught.value.code == "provenance_mismatch"\n',
        '    assert caught.value.code == "bundle_provenance_mismatch"\n',
    )

    manifest_path = "merger/lenskit/tests/test_graph_bundle_manifest_provenance.py"
    content = read(manifest_path)
    marker = '    assert graph_entry["staleness_sensitive"] is True\n'
    addition = """

    eval_entries = [
        artifact
        for artifact in manifest["artifacts"]
        if artifact.get("role") == ArtifactRole.RETRIEVAL_EVAL_JSON.value
    ]
    assert len(eval_entries) == 1
    eval_entry = eval_entries[0]
    assert eval_entry["contract"] == {"id": "retrieval-eval", "version": "v1"}
    assert eval_entry["authority"] == "diagnostic_signal"
    assert eval_entry["canonicality"] == "diagnostic"
    assert eval_entry["regenerable"] is True
    assert eval_entry["staleness_sensitive"] is True
"""
    if addition.strip() not in content:
        if content.count(marker) != 1:
            raise RuntimeError("manifest provenance test marker missing")
        content = content.replace(marker, marker + addition, 1)
        write(manifest_path, content)

    audit_path = "merger/lenskit/tests/test_graph_current_state_audit.py"
    audit = read(audit_path)
    audit = audit.replace(
        '    compiler = _read("merger/lenskit/architecture/graph_index.py")\n'
        '    validation = _read("merger/lenskit/architecture/graph_source_validation.py")\n',
        '    compiler = _read("merger/lenskit/architecture/graph_index.py")\n'
        '    validation = _read("merger/lenskit/architecture/graph_source_validation.py")\n'
        '    merge_source = _read("merger/lenskit/core/merge.py")\n',
        1,
    )
    old = """    assert "_infer_bundle_provenance(" in compiler\n    assert '\".dump_index.json\"' in compiler\n    assert "hashlib.sha256" in compiler\n"""
    new = """    assert "expected_run_id=run_id" in merge_source\n    assert (\n        "expected_canonical_sha256=_compute_file_sha256(dump_index_path)"\n        in merge_source\n    )\n    assert "except GraphIndexCompilationError:" in merge_source\n"""
    if old not in audit:
        raise RuntimeError("audit test implicit-binding assertions missing")
    write(audit_path, audit.replace(old, new, 1))


def patch_proof() -> None:
    path = "docs/proofs/graph-provenance-coherent-compilation-proof.md"
    content = read(path)
    content = content.replace(
        "6. For the bundle naming convention, resolve the sibling dump-index document and require the source run ID and source hash to match that current dump index.\n"
        "7. Preserve explicit `expected_run_id` and `expected_canonical_sha256` arguments for callers that bind provenance without the bundle file layout.\n",
        "6. When the bundle pipeline invokes the compiler, pass the current bundle `run_id` and the actual SHA-256 of its finalized dump index as explicit expected provenance.\n"
        "7. Propagate structured provenance failures instead of silently omitting the Graph Index.\n",
        1,
    )
    content = content.replace(
        "- If both sources are valid and bound to the sibling current run and dump index, the derived Graph Index is emitted and registered as a derived retrieval index.\n",
        "- If both sources are valid and explicitly bound to the current run and dump index, the derived Graph Index is emitted and registered as a derived retrieval index.\n",
        1,
    )
    write(path, content)


def patch_tasks() -> None:
    task_id = "TASK-GRAPH-PROVENANCE-COHERENCE-001"
    board_path = "docs/tasks/board.md"
    board = read(board_path)
    if task_id not in board:
        row = (
            "| TASK-GRAPH-PROVENANCE-COHERENCE-001 | Graph Provenance-Coherent Compilation | done | "
            "`merger/lenskit/architecture/graph_source_validation.py`, "
            "`merger/lenskit/architecture/graph_index.py`, `merger/lenskit/core/merge.py`, "
            "`merger/lenskit/cli/cmd_architecture.py`, `merger/lenskit/tests/test_graph_index.py`, "
            "`merger/lenskit/tests/test_graph_bundle_integration.py`, "
            "`merger/lenskit/tests/test_graph_bundle_manifest_provenance.py`, "
            "`merger/lenskit/tests/test_cli_architecture_graph_index.py`, "
            "`docs/proofs/graph-provenance-coherent-compilation-proof.md` | "
            "Beide Compiler-Quellen werden vor der Distanzberechnung gegen Draft-07 validiert; "
            "gleiche nichtleere Run-ID und gleicher Dump-Index-Hash sind Pflicht. Der Bundlepfad bindet "
            "explizit an aktuellen Lauf und finalisierten Dump-Index und propagiert strukturierte Fehler. "
            "Automatische Source-Erzeugung, Default-Ranking-Nutzung, Graph-Vollständigkeit und "
            "Runtime-Kausalität bleiben Nicht-Ziele. |\n"
        )
        write(board_path, board.rstrip() + "\n" + row)

    index_path = ROOT / "docs/tasks/index.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))
    if not any(task.get("id") == task_id for task in data["tasks"]):
        data["tasks"].append(
            {
                "id": task_id,
                "title": "Graph Provenance-Coherent Compilation",
                "status": "done",
                "description": (
                    "Validates both Graph Index source documents before distance calculation, "
                    "requires source/source run and dump-hash equality, binds bundle compilation "
                    "to the current run and finalized dump index, and propagates structured "
                    "fail-closed diagnostics."
                ),
                "evidence": [
                    "merger/lenskit/architecture/graph_source_validation.py",
                    "merger/lenskit/architecture/graph_index.py",
                    "merger/lenskit/core/merge.py",
                    "merger/lenskit/cli/cmd_architecture.py",
                    "merger/lenskit/tests/test_graph_index.py",
                    "merger/lenskit/tests/test_graph_bundle_integration.py",
                    "merger/lenskit/tests/test_graph_bundle_manifest_provenance.py",
                    "merger/lenskit/tests/test_cli_architecture_graph_index.py",
                    "docs/proofs/graph-provenance-coherent-compilation-proof.md",
                ],
                "missing_evidence": [
                    "Automatic Graph and Entrypoints source production remains a separate G3 slice.",
                    "No graph completeness, runtime causality, retrieval benefit, test sufficiency, or default-ranking claim is established.",
                ],
            }
        )
        index_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def patch_lens_workflow() -> None:
    path = ".github/workflows/lens-model.yml"
    content = read(path)
    trigger_anchor = '      - "merger/lenskit/architecture/import_graph.py"\n'
    trigger_addition = """      - "merger/lenskit/architecture/graph_index.py"
      - "merger/lenskit/architecture/graph_source_validation.py"
      - "merger/lenskit/cli/cmd_architecture.py"
      - "merger/lenskit/core/merge.py"
      - "merger/lenskit/contracts/architecture.graph_index.v1.schema.json"
      - "merger/lenskit/contracts/entrypoints.v1.schema.json"
      - "merger/lenskit/tests/test_graph_index.py"
      - "merger/lenskit/tests/test_graph_bundle_integration.py"
      - "merger/lenskit/tests/test_graph_bundle_manifest_provenance.py"
      - "merger/lenskit/tests/test_cli_architecture_graph_index.py"
      - "merger/lenskit/tests/test_graph_current_state_audit.py"
      - "merger/lenskit/tests/test_graph_e2e.py"
      - "docs/proofs/graph-provenance-coherent-compilation-proof.md"
      - "docs/tasks/board.md"
      - "docs/tasks/index.json"
"""
    if trigger_addition.strip() not in content:
        if content.count(trigger_anchor) != 2:
            raise RuntimeError("lens-model trigger anchor count changed")
        content = content.replace(
            trigger_anchor,
            trigger_anchor + trigger_addition,
        )

    schema_anchor = '              Path("merger/lenskit/contracts/relation-card.v1.schema.json"),\n'
    schema_addition = (
        '              Path("merger/lenskit/contracts/architecture.graph.v1.schema.json"),\n'
        '              Path("merger/lenskit/contracts/architecture.graph_index.v1.schema.json"),\n'
        '              Path("merger/lenskit/contracts/entrypoints.v1.schema.json"),\n'
    )
    if schema_addition.strip() not in content:
        if content.count(schema_anchor) != 1:
            raise RuntimeError("schema validation anchor changed")
        content = content.replace(schema_anchor, schema_anchor + schema_addition, 1)

    test_anchor = "            merger/lenskit/tests/test_architecture_import_graph.py \\\n"
    test_addition = """            merger/lenskit/tests/test_graph_index.py \\
            merger/lenskit/tests/test_graph_bundle_integration.py \\
            merger/lenskit/tests/test_graph_bundle_manifest_provenance.py \\
            merger/lenskit/tests/test_cli_architecture_graph_index.py \\
            merger/lenskit/tests/test_graph_current_state_audit.py \\
            merger/lenskit/tests/test_graph_e2e.py \\
"""
    if test_addition.strip() not in content:
        if content.count(test_anchor) != 1:
            raise RuntimeError("lens-model pytest anchor changed")
        content = content.replace(test_anchor, test_anchor + test_addition, 1)

    ruff_anchor = "            merger/lenskit/architecture/import_graph.py \\\n"
    ruff_addition = """            merger/lenskit/architecture/graph_index.py \\
            merger/lenskit/architecture/graph_source_validation.py \\
            merger/lenskit/cli/cmd_architecture.py \\
            merger/lenskit/tests/test_graph_index.py \\
            merger/lenskit/tests/test_graph_bundle_integration.py \\
            merger/lenskit/tests/test_graph_bundle_manifest_provenance.py \\
            merger/lenskit/tests/test_cli_architecture_graph_index.py \\
            merger/lenskit/tests/test_graph_current_state_audit.py \\
            merger/lenskit/tests/test_graph_e2e.py \\
"""
    if ruff_addition.strip() not in content:
        if content.count(ruff_anchor) != 1:
            raise RuntimeError("lens-model ruff anchor changed")
        content = content.replace(ruff_anchor, ruff_anchor + ruff_addition, 1)

    write(path, content)


def main() -> None:
    patch_graph_index()
    patch_merge()
    patch_tests()
    patch_proof()
    patch_tasks()
    patch_lens_workflow()


if __name__ == "__main__":
    main()
