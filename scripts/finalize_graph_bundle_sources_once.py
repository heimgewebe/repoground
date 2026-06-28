from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}")
    write(path, content.replace(old, new, 1))


def patch_merge() -> None:
    path = "merger/lenskit/core/merge.py"
    content = read(path)

    registry_anchor = (
        '    ArtifactRole.GRAPH_INDEX_JSON: {"id": "architecture.graph_index", "version": "v1"},\n'
    )
    registry_addition = (
        '    ArtifactRole.ARCHITECTURE_GRAPH_JSON: {"id": "architecture.graph", "version": "v1"},\n'
        '    ArtifactRole.ENTRYPOINTS_JSON: {"id": "entrypoints", "version": "v1"},\n'
    )
    if registry_addition not in content:
        if content.count(registry_anchor) != 1:
            raise RuntimeError("contract registry anchor changed")
        content = content.replace(
            registry_anchor,
            registry_addition + registry_anchor,
            1,
        )

    authority_anchor = "    ArtifactRole.GRAPH_INDEX_JSON: {\n"
    source_authority = '''    ArtifactRole.ARCHITECTURE_GRAPH_JSON: {
        "authority": "diagnostic_signal",
        "canonicality": "diagnostic",
        "risk_class": "diagnostic",
        "regenerable": True,
        "staleness_sensitive": True,
    },
    ArtifactRole.ENTRYPOINTS_JSON: {
        "authority": "diagnostic_signal",
        "canonicality": "diagnostic",
        "risk_class": "diagnostic",
        "regenerable": True,
        "staleness_sensitive": True,
    },
'''
    if source_authority not in content:
        if content.count(authority_anchor) != 1:
            raise RuntimeError("authority registry anchor changed")
        content = content.replace(authority_anchor, source_authority + authority_anchor, 1)

    signature_old = (
        "def build_derived_artifacts(dump_index_path, chunk_path, base_name_func, "
        "run_id, hub_path, generator_info, repo_names, debug) -> List[Path]:"
    )
    signature_new = (
        "def build_derived_artifacts(dump_index_path, chunk_path, base_name_func, "
        "run_id, hub_path, generator_info, repo_names, debug, repo_summaries=None) -> List[Path]:"
    )
    if signature_new not in content:
        if content.count(signature_old) != 1:
            raise RuntimeError("build_derived_artifacts signature changed")
        content = content.replace(signature_old, signature_new, 1)

    graph_start = content.index("    # Generate Graph Index Artifact\n")
    graph_end = content.index("    # Write Derived Manifest\n", graph_start)
    graph_block = '''    # Generate bundle-bound Graph source artifacts and compile the Graph Index.
    architecture_graph_path = None
    entrypoints_path = None
    graph_index_path = None
    try:
        from ..architecture.bundle_sources import ensure_bundle_graph_sources
        from ..architecture.graph_index import (
            GraphIndexCompilationError,
            compile_graph_index,
        )

        base_path = base_name_func(part_suffix="")
        dump_sha256 = _compute_file_sha256(dump_index_path)
        source_result = ensure_bundle_graph_sources(
            base_path=base_path,
            repo_summaries=repo_summaries,
            run_id=run_id,
            canonical_dump_index_sha256=dump_sha256,
            generated_at=clock.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        architecture_graph_path = source_result.graph_path
        entrypoints_path = source_result.entrypoints_path

        for source_path in (architecture_graph_path, entrypoints_path):
            if source_path.exists() and source_path not in derived_paths:
                derived_paths.append(source_path)

        if architecture_graph_path.exists() or entrypoints_path.exists():
            graph_index_data = compile_graph_index(
                architecture_graph_path,
                entrypoints_path,
                expected_run_id=run_id,
                expected_canonical_sha256=dump_sha256,
            )
            graph_index_path = base_path.with_suffix(".graph_index.json")
            graph_index_path.write_text(
                json.dumps(graph_index_data, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            derived_paths.append(graph_index_path)
    except ImportError as e:
        if debug:
            print(
                f"Skipping graph artifacts: architecture modules not available ({e})",
                file=sys.stderr,
            )
    except GraphIndexCompilationError:
        raise
    except Exception as e:
        if debug:
            print(f"Error producing graph artifacts: {e}", file=sys.stderr)

'''
    content = content[:graph_start] + graph_block + content[graph_end:]

    map_anchor = "    if graph_index_path and graph_index_path.exists():\n        derived_map[ArtifactRole.GRAPH_INDEX_JSON.value] = graph_index_path\n"
    map_addition = '''    if architecture_graph_path and architecture_graph_path.exists():
        derived_map[ArtifactRole.ARCHITECTURE_GRAPH_JSON.value] = architecture_graph_path
    if entrypoints_path and entrypoints_path.exists():
        derived_map[ArtifactRole.ENTRYPOINTS_JSON.value] = entrypoints_path
'''
    if map_addition not in content:
        if content.count(map_anchor) != 1:
            raise RuntimeError("derived map anchor changed")
        content = content.replace(map_anchor, map_addition + map_anchor, 1)

    unified_old = (
        "                dump_index_path, chunk_path, base_name_func, run_id, hub, "
        "generator_info, repo_names, debug\n"
    )
    unified_new = (
        "                dump_index_path, chunk_path, base_name_func, run_id, hub, "
        "generator_info, repo_names, debug, repo_summaries=repo_summaries\n"
    )
    if unified_new not in content:
        if content.count(unified_old) != 1:
            raise RuntimeError("unified derived call anchor changed")
        content = content.replace(unified_old, unified_new, 1)

    per_repo_old = (
        "                    dump_index_path, chunk_path, base_name_func, repo_run_id, "
        "hub, generator_info, [s_name], debug\n"
    )
    per_repo_new = (
        "                    dump_index_path, chunk_path, base_name_func, repo_run_id, "
        "hub, generator_info, [s_name], debug, repo_summaries=[s]\n"
    )
    if per_repo_new not in content:
        if content.count(per_repo_old) != 1:
            raise RuntimeError("per-repo derived call anchor changed")
        content = content.replace(per_repo_old, per_repo_new, 1)

    json_filter_anchor = (
        '        and not p.name.endswith(".retrieval_eval.json")\n'
    )
    json_filter_addition = (
        '        and not p.name.endswith(".architecture_graph.json")\n'
        '        and not p.name.endswith(".entrypoints.json")\n'
    )
    if json_filter_addition not in content:
        if content.count(json_filter_anchor) != 1:
            raise RuntimeError("JSON path filter anchor changed")
        content = content.replace(
            json_filter_anchor,
            json_filter_anchor + json_filter_addition,
            1,
        )

    graph_list_anchor = (
        '    graph_indices = sorted([p for p in out_paths if p.name.endswith(".graph_index.json")], key=lambda p: p.name)\n'
    )
    source_lists = (
        '    architecture_graphs = sorted([p for p in out_paths if p.name.endswith(".architecture_graph.json")], key=lambda p: p.name)\n'
        '    entrypoint_documents = sorted([p for p in out_paths if p.name.endswith(".entrypoints.json")], key=lambda p: p.name)\n'
    )
    if source_lists not in content:
        if content.count(graph_list_anchor) != 1:
            raise RuntimeError("graph artifact list anchor changed")
        content = content.replace(graph_list_anchor, source_lists + graph_list_anchor, 1)

    add_anchor = (
        "    if graph_indices:\n"
        "        _add_artifact(graph_indices[-1], ArtifactRole.GRAPH_INDEX_JSON, \"application/json\")\n"
    )
    add_sources = '''    if architecture_graphs:
        _add_artifact(
            architecture_graphs[-1],
            ArtifactRole.ARCHITECTURE_GRAPH_JSON,
            "application/json",
        )
    if entrypoint_documents:
        _add_artifact(
            entrypoint_documents[-1],
            ArtifactRole.ENTRYPOINTS_JSON,
            "application/json",
        )
'''
    if add_sources not in content:
        if content.count(add_anchor) != 1:
            raise RuntimeError("bundle artifact registration anchor changed")
        content = content.replace(add_anchor, add_sources + add_anchor, 1)

    write(path, content)


def patch_bundle_schema() -> None:
    path = "merger/lenskit/contracts/bundle-manifest.v1.schema.json"
    data = json.loads(read(path))
    artifact = data["properties"]["artifacts"]["items"]
    roles = artifact["properties"]["role"]["enum"]
    for role in ("architecture_graph_json", "entrypoints_json"):
        if role not in roles:
            roles.insert(roles.index("graph_index_json"), role)

    all_of = artifact["allOf"]
    contract_roles = all_of[2]["if"]["properties"]["role"]["enum"]
    for role in ("architecture_graph_json", "entrypoints_json"):
        if role not in contract_roles:
            contract_roles.insert(contract_roles.index("graph_index_json"), role)

    marker = "lenskit.graph-source-roles"
    if not any(item.get("$comment") == marker for item in all_of):
        graph_index_pos = next(
            index
            for index, item in enumerate(all_of)
            if item.get("if", {}).get("properties", {}).get("role", {}).get("const")
            == "graph_index_json"
        )
        all_of.insert(
            graph_index_pos,
            {
                "$comment": marker,
                "if": {
                    "properties": {
                        "role": {
                            "enum": [
                                "architecture_graph_json",
                                "entrypoints_json",
                            ]
                        }
                    },
                    "required": ["role"],
                },
                "then": {
                    "properties": {
                        "authority": {"const": "diagnostic_signal"},
                        "canonicality": {"const": "diagnostic"},
                        "risk_class": {"const": "diagnostic"},
                    }
                },
            },
        )
    write(path, json.dumps(data, indent=2, ensure_ascii=False))


def patch_bundle_test() -> None:
    path = "merger/lenskit/tests/test_graph_bundle_integration.py"
    content = read(path)
    test = '''


def test_graph_bundle_auto_produces_bound_sources_for_single_repo(tmp_path):
    base, dump_sha, args = _setup(tmp_path)
    base.with_suffix(".architecture_graph.json").unlink()
    base.with_suffix(".entrypoints.json").unlink()
    repo_root = tmp_path / "repo1"
    repo_root.mkdir()
    (repo_root / "main.py").write_text(
        "if __name__ == '__main__':\n    print('hello')\n",
        encoding="utf-8",
    )
    args["repo_summaries"] = [{"root": repo_root, "name": "repo1"}]

    derived_paths = build_derived_artifacts(**args)

    graph_source = base.with_suffix(".architecture_graph.json")
    entrypoint_source = base.with_suffix(".entrypoints.json")
    graph_index = base.with_suffix(".graph_index.json")
    assert graph_source in derived_paths
    assert entrypoint_source in derived_paths
    assert graph_index in derived_paths
    graph = json.loads(graph_source.read_text(encoding="utf-8"))
    entrypoints = json.loads(entrypoint_source.read_text(encoding="utf-8"))
    assert graph["run_id"] == entrypoints["run_id"] == "test_run"
    assert graph["canonical_dump_index_sha256"] == dump_sha
    assert entrypoints["canonical_dump_index_sha256"] == dump_sha
    assert graph["nodes"][0]["repo"] == "repo1"
    compiled = json.loads(graph_index.read_text(encoding="utf-8"))
    assert compiled["distances"]["file:main.py"] == 0
    derived = json.loads(
        base.with_suffix(".derived_index.json").read_text(encoding="utf-8")
    )
    assert ArtifactRole.ARCHITECTURE_GRAPH_JSON.value in derived["artifacts"]
    assert ArtifactRole.ENTRYPOINTS_JSON.value in derived["artifacts"]
'''
    if "test_graph_bundle_auto_produces_bound_sources_for_single_repo" not in content:
        content = content.rstrip() + test + "\n"
    write(path, content)


def patch_workflow() -> None:
    path = ".github/workflows/graph-model.yml"
    content = read(path)
    path_anchor = '      - "merger/lenskit/architecture/graph_index.py"\n'
    path_addition = (
        '      - "merger/lenskit/architecture/bundle_sources.py"\n'
        '      - "merger/lenskit/architecture/import_graph.py"\n'
        '      - "merger/lenskit/architecture/entrypoints.py"\n'
        '      - "merger/lenskit/contracts/bundle-manifest.v1.schema.json"\n'
        '      - "merger/lenskit/core/constants.py"\n'
        '      - "merger/lenskit/tests/test_graph_bundle_sources.py"\n'
        '      - "docs/proofs/graph-bundle-source-production-proof.md"\n'
    )
    if path_addition not in content:
        if content.count(path_anchor) != 2:
            raise RuntimeError("graph workflow path anchor changed")
        content = content.replace(path_anchor, path_anchor + path_addition)

    slash = "\\"
    pytest_anchor = (
        "            merger/lenskit/tests/test_graph_index.py " + slash + "\n"
    )
    pytest_addition = (
        "            merger/lenskit/tests/test_graph_bundle_sources.py "
        + slash
        + "\n"
    )
    if pytest_addition not in content:
        if content.count(pytest_anchor) != 1:
            raise RuntimeError("graph workflow pytest anchor changed")
        content = content.replace(pytest_anchor, pytest_anchor + pytest_addition, 1)

    ruff_anchor = (
        "            merger/lenskit/architecture/graph_index.py " + slash + "\n"
    )
    ruff_addition = (
        "            merger/lenskit/architecture/bundle_sources.py " + slash + "\n"
        "            merger/lenskit/tests/test_graph_bundle_sources.py " + slash + "\n"
    )
    if ruff_addition not in content:
        if content.count(ruff_anchor) != 1:
            raise RuntimeError("graph workflow Ruff anchor changed")
        content = content.replace(ruff_anchor, ruff_anchor + ruff_addition, 1)
    write(path, content)


def patch_docs() -> None:
    proof_path = ROOT / "docs/proofs/graph-bundle-source-production-proof.md"
    if not proof_path.exists():
        proof_path.write_text(
            """# Single-Repo Bundle-Bound Graph Source Production Proof

## Status

This implements the first safe G3 slice from the Graph Current-State Audit.

## Implemented boundary

For retrieval or dual output, the ordinary merge pipeline now creates
`architecture.graph.v1` and `entrypoints.v1` source artifacts when the output
contains exactly one repository and neither source already exists. Both sources
receive the actual bundle run ID and finalized dump-index SHA-256. The graph's
`generated_at` is replaced with the merge clock value, and file nodes carry the
repository name.

Existing source pairs remain supported. Partial pairs are not silently repaired;
the provenance-coherent compiler fails closed. Multi-repository automatic
production is explicitly skipped because the current Graph Index identity uses
`file:<path>` without a repository discriminator.

The source documents are registered as diagnostic, derived, regenerable,
staleness-sensitive artifacts. They are inputs to the retrieval Graph Index, not
canonical repository truth and not runtime observations.

## Verification

Tests cover deterministic single-repository production, actual bundle provenance,
repository labels, Graph Index compilation, derived-manifest registration,
partial-pair preservation, and explicit multi-repository non-production.

## Non-claims

This does not establish graph completeness, import correctness, runtime causality,
change impact, retrieval benefit, or multi-repository graph identity. It does not
auto-enable graph ranking.
""",
            encoding="utf-8",
        )

    task_id = "TASK-GRAPH-BUNDLE-SOURCES-001"
    board_path = "docs/tasks/board.md"
    board = read(board_path)
    if task_id not in board:
        row = (
            "| TASK-GRAPH-BUNDLE-SOURCES-001 | Single-Repo Bundle-Bound Graph Sources | done | "
            "`merger/lenskit/architecture/bundle_sources.py`, `merger/lenskit/core/merge.py`, "
            "`merger/lenskit/tests/test_graph_bundle_sources.py`, "
            "`merger/lenskit/tests/test_graph_bundle_integration.py`, "
            "`docs/proofs/graph-bundle-source-production-proof.md` | "
            "Produces Graph and Entrypoints sources with current bundle provenance for unambiguous "
            "single-repo outputs; preserves fail-closed partial pairs and explicitly leaves "
            "multi-repo identity out of scope. |\n"
        )
        write(board_path, board.rstrip() + "\n" + row)

    index_path = ROOT / "docs/tasks/index.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))
    if not any(task.get("id") == task_id for task in data["tasks"]):
        data["tasks"].append(
            {
                "id": task_id,
                "title": "Single-Repo Bundle-Bound Graph Sources",
                "status": "done",
                "description": (
                    "Produces architecture graph and entrypoint source artifacts with "
                    "the current bundle identity for single-repository outputs."
                ),
                "evidence": [
                    "merger/lenskit/architecture/bundle_sources.py",
                    "merger/lenskit/core/merge.py",
                    "merger/lenskit/tests/test_graph_bundle_sources.py",
                    "merger/lenskit/tests/test_graph_bundle_integration.py",
                    "docs/proofs/graph-bundle-source-production-proof.md",
                ],
                "missing_evidence": [
                    "Multi-repository graph identity and aggregation remain out of scope.",
                    "No graph completeness, runtime causality, retrieval benefit, or default-ranking claim is established.",
                ],
            }
        )
        index_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def main() -> None:
    patch_merge()
    patch_bundle_schema()
    patch_bundle_test()
    patch_workflow()
    patch_docs()


if __name__ == "__main__":
    main()
