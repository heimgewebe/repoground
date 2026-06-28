from __future__ import annotations

import finalize_graph_g2_once as finalizer


def patch_lens_workflow() -> None:
    path = ".github/workflows/lens-model.yml"
    content = finalizer.read(path)

    trigger_anchor = '      - "merger/lenskit/architecture/import_graph.py"\n'
    trigger_lines = [
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
    trigger_addition = "".join(f'      - "{line}"\n' for line in trigger_lines)
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

    slash = "\\"
    test_anchor = (
        "            merger/lenskit/tests/test_architecture_import_graph.py "
        + slash
        + "\n"
    )
    test_paths = [
        "merger/lenskit/tests/test_graph_index.py",
        "merger/lenskit/tests/test_graph_bundle_integration.py",
        "merger/lenskit/tests/test_graph_bundle_manifest_provenance.py",
        "merger/lenskit/tests/test_cli_architecture_graph_index.py",
        "merger/lenskit/tests/test_graph_current_state_audit.py",
        "merger/lenskit/tests/test_graph_e2e.py",
    ]
    test_addition = "".join(f"            {item} {slash}\n" for item in test_paths)
    if test_addition.strip() not in content:
        if content.count(test_anchor) != 1:
            raise RuntimeError("lens-model pytest anchor changed")
        content = content.replace(test_anchor, test_anchor + test_addition, 1)

    ruff_anchor = "            merger/lenskit/architecture/import_graph.py " + slash + "\n"
    ruff_paths = [
        "merger/lenskit/architecture/graph_index.py",
        "merger/lenskit/architecture/graph_source_validation.py",
        "merger/lenskit/cli/cmd_architecture.py",
        "merger/lenskit/tests/test_graph_index.py",
        "merger/lenskit/tests/test_graph_bundle_integration.py",
        "merger/lenskit/tests/test_graph_bundle_manifest_provenance.py",
        "merger/lenskit/tests/test_cli_architecture_graph_index.py",
        "merger/lenskit/tests/test_graph_current_state_audit.py",
        "merger/lenskit/tests/test_graph_e2e.py",
    ]
    ruff_addition = "".join(f"            {item} {slash}\n" for item in ruff_paths)
    if ruff_addition.strip() not in content:
        if content.count(ruff_anchor) != 1:
            raise RuntimeError("lens-model ruff anchor changed")
        content = content.replace(ruff_anchor, ruff_anchor + ruff_addition, 1)

    finalizer.write(path, content)


finalizer.patch_lens_workflow = patch_lens_workflow
finalizer.main()
