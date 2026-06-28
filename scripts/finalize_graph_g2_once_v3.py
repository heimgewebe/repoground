from __future__ import annotations

import finalize_graph_g2_once as finalizer


def _insert_after_occurrence(
    lines: list[str],
    needle: str,
    additions: list[str],
    *,
    occurrence: int = 0,
) -> list[str]:
    indexes = [index for index, line in enumerate(lines) if line.strip().startswith(needle)]
    if occurrence >= len(indexes):
        raise RuntimeError(
            f"expected occurrence {occurrence} of line starting with {needle!r}; "
            f"found {len(indexes)}"
        )
    index = indexes[occurrence]
    local_window = {
        line.strip().rstrip("\\").strip()
        for line in lines[index + 1 : index + 1 + len(additions) + 8]
    }
    missing = [item for item in additions if item not in local_window]
    if not missing:
        return lines
    slash = "\\"
    rendered = [f"            {item} {slash}\n" for item in missing]
    return lines[: index + 1] + rendered + lines[index + 1 :]


def patch_lens_workflow() -> None:
    path = ".github/workflows/lens-model.yml"
    content = finalizer.read(path)

    trigger_anchor = '      - "merger/lenskit/architecture/import_graph.py"\n'
    trigger_paths = [
        "merger/lenskit/architecture/graph_index.py",
        "merger/lenskit/architecture/graph_source_validation.py",
        "merger/lenskit/cli/cmd_architecture.py",
        "merger/lenskit/core/merge.py",
        "merger/lenskit/contracts/architecture.graph_index.v1.schema.json",
        "merger/lenskit/contracts/entrypoints.v1.schema.json",
        "merger/lenskit/tests/test_graph_index.py",
        "merger/lenskit/tests/test_graph_bundle_integration.py",
        "merger/lenskit/tests/test_graph_bundle_manifest_provenance.py",
        "merger/lenskit/tests/test_cli_architecture_graph_index.py",
        "merger/lenskit/tests/test_graph_current_state_audit.py",
        "merger/lenskit/tests/test_graph_e2e.py",
        "docs/proofs/graph-provenance-coherent-compilation-proof.md",
        "docs/tasks/board.md",
        "docs/tasks/index.json",
    ]
    trigger_addition = "".join(f'      - "{item}"\n' for item in trigger_paths)
    if trigger_addition.strip() not in content:
        if content.count(trigger_anchor) != 2:
            raise RuntimeError("lens-model trigger anchor count changed")
        content = content.replace(trigger_anchor, trigger_anchor + trigger_addition)

    schema_anchor = (
        '              Path("merger/lenskit/contracts/relation-card.v1.schema.json"),\n'
    )
    schema_addition = (
        '              Path("merger/lenskit/contracts/architecture.graph.v1.schema.json"),\n'
        '              Path("merger/lenskit/contracts/architecture.graph_index.v1.schema.json"),\n'
        '              Path("merger/lenskit/contracts/entrypoints.v1.schema.json"),\n'
    )
    if schema_addition.strip() not in content:
        if content.count(schema_anchor) != 1:
            raise RuntimeError("schema validation anchor changed")
        content = content.replace(schema_anchor, schema_anchor + schema_addition, 1)

    lines = content.splitlines(keepends=True)
    lines = _insert_after_occurrence(
        lines,
        "merger/lenskit/tests/test_architecture_import_graph.py",
        [
            "merger/lenskit/tests/test_graph_index.py",
            "merger/lenskit/tests/test_graph_bundle_integration.py",
            "merger/lenskit/tests/test_graph_bundle_manifest_provenance.py",
            "merger/lenskit/tests/test_cli_architecture_graph_index.py",
            "merger/lenskit/tests/test_graph_current_state_audit.py",
            "merger/lenskit/tests/test_graph_e2e.py",
        ],
        occurrence=0,
    )
    lines = _insert_after_occurrence(
        lines,
        "merger/lenskit/architecture/import_graph.py",
        [
            "merger/lenskit/architecture/graph_index.py",
            "merger/lenskit/architecture/graph_source_validation.py",
            "merger/lenskit/cli/cmd_architecture.py",
            "merger/lenskit/tests/test_graph_index.py",
            "merger/lenskit/tests/test_graph_bundle_integration.py",
            "merger/lenskit/tests/test_graph_bundle_manifest_provenance.py",
            "merger/lenskit/tests/test_cli_architecture_graph_index.py",
            "merger/lenskit/tests/test_graph_current_state_audit.py",
            "merger/lenskit/tests/test_graph_e2e.py",
        ],
        occurrence=0,
    )
    finalizer.write(path, "".join(lines))


finalizer.patch_lens_workflow = patch_lens_workflow
finalizer.main()
