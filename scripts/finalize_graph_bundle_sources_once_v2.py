from __future__ import annotations

import finalize_graph_bundle_sources_once as finalizer


def patch_workflow() -> None:
    path = ".github/workflows/graph-model.yml"
    lines = finalizer.read(path).splitlines(keepends=True)

    path_indexes = [
        i
        for i, line in enumerate(lines)
        if line.strip() == '- "merger/lenskit/architecture/graph_index.py"'
    ]
    if len(path_indexes) != 2:
        raise RuntimeError(f"expected two path anchors, found {len(path_indexes)}")
    path_additions = [
        '      - "merger/lenskit/architecture/bundle_sources.py"\n',
        '      - "merger/lenskit/architecture/import_graph.py"\n',
        '      - "merger/lenskit/architecture/entrypoints.py"\n',
        '      - "merger/lenskit/contracts/bundle-manifest.v1.schema.json"\n',
        '      - "merger/lenskit/core/constants.py"\n',
        '      - "merger/lenskit/tests/test_graph_bundle_sources.py"\n',
        '      - "docs/proofs/graph-bundle-source-production-proof.md"\n',
    ]
    for index in reversed(path_indexes):
        lines[index + 1 : index + 1] = path_additions

    test_indexes = [
        i
        for i, line in enumerate(lines)
        if line.strip().startswith("merger/lenskit/tests/test_graph_index.py")
    ]
    if len(test_indexes) != 2:
        raise RuntimeError(
            f"expected Pytest and Ruff test anchors, found {len(test_indexes)}"
        )
    slash = "\\"
    test_line = (
        "            merger/lenskit/tests/test_graph_bundle_sources.py "
        + slash
        + "\n"
    )
    lines[test_indexes[0] + 1 : test_indexes[0] + 1] = [test_line]

    ruff_indexes = [
        i
        for i, line in enumerate(lines)
        if line.strip().startswith("merger/lenskit/architecture/graph_index.py")
        and not line.lstrip().startswith("-")
    ]
    if len(ruff_indexes) != 1:
        raise RuntimeError(f"expected one Ruff anchor, found {len(ruff_indexes)}")
    ruff_lines = [
        "            merger/lenskit/architecture/bundle_sources.py "
        + slash
        + "\n",
        "            merger/lenskit/tests/test_graph_bundle_sources.py "
        + slash
        + "\n",
    ]
    lines[ruff_indexes[0] + 1 : ruff_indexes[0] + 1] = ruff_lines
    finalizer.write(path, "".join(lines))


finalizer.patch_workflow = patch_workflow
finalizer.main()
