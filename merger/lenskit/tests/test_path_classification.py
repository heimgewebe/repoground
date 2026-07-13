from merger.lenskit.architecture.path_classification import (
    infer_architecture_layer,
    path_projection,
)


def test_path_projection_separates_product_test_fixture_and_script() -> None:
    assert path_projection("merger/lenskit/core/model.py") == "product"
    assert path_projection("merger/lenskit/tests/test_model.py") == "test"
    assert path_projection("merger/lenskit/tests/fixtures/demo/cli.py") == "fixture"
    assert path_projection("scripts/ci/check.py") == "script"
    assert path_projection("scripts/tests/test_check.py") == "test"


def test_architecture_layers_identify_lenskit_product_areas() -> None:
    assert infer_architecture_layer("merger/lenskit/architecture/import_graph.py") == "architecture"
    assert infer_architecture_layer("merger/lenskit/retrieval/query_core.py") == "retrieval"
    assert infer_architecture_layer("merger/lenskit/service/app.py") == "service"
    assert infer_architecture_layer("merger/lenskit/adapters/atlas.py") == "adapter"
    assert infer_architecture_layer("merger/lenskit/frontends/pythonista/repolens.py") == "frontend"
    assert infer_architecture_layer("benchmark_sse.py") == "benchmark"
    assert infer_architecture_layer("merger/repomerger/repomerger.py") == "product"
    assert infer_architecture_layer("cli/main.py") == "cli"
    assert infer_architecture_layer("core/service.py") == "core"
    assert infer_architecture_layer("tools/core/worker.py") == "core"
    assert infer_architecture_layer("scripts/worker.py") == "infra"


def test_generic_unmatched_product_path_remains_unknown() -> None:
    assert infer_architecture_layer("src/domain.py") == "unknown"
