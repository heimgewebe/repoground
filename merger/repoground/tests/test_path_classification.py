from merger.repoground.architecture.path_classification import (
    infer_architecture_layer,
    is_test_path,
    path_projection,
)


def test_path_projection_separates_product_test_fixture_and_script() -> None:
    assert path_projection("merger/repoground/core/model.py") == "product"
    assert path_projection("merger/repoground/tests/test_model.py") == "test"
    assert path_projection("merger/repoground/tests/fixtures/demo/cli.py") == "fixture"
    assert path_projection("scripts/ci/check.py") == "script"
    assert path_projection("scripts/tests/test_check.py") == "test"


def test_architecture_layers_identify_lenskit_product_areas() -> None:
    assert infer_architecture_layer("merger/repoground/architecture/import_graph.py") == "architecture"
    assert infer_architecture_layer("merger/repoground/retrieval/query_core.py") == "retrieval"
    assert infer_architecture_layer("merger/repoground/service/app.py") == "service"
    assert infer_architecture_layer("merger/repoground/adapters/atlas.py") == "adapter"
    assert infer_architecture_layer("merger/repoground/frontends/pythonista/build.py") == "frontend"
    assert infer_architecture_layer("benchmark_sse.py") == "benchmark"
    assert infer_architecture_layer("merger/repomerger/repomerger.py") == "product"
    assert infer_architecture_layer("cli/main.py") == "cli"
    assert infer_architecture_layer("core/service.py") == "core"
    assert infer_architecture_layer("tools/core/worker.py") == "core"
    assert infer_architecture_layer("scripts/worker.py") == "infra"


def test_generic_unmatched_product_path_remains_unknown() -> None:
    assert infer_architecture_layer("src/domain.py") == "unknown"


def test_cross_language_test_filenames_are_recognized() -> None:
    assert is_test_path("apps/web/src/lib/map/nodes.test.ts")
    assert is_test_path("apps/web/src/lib/map/nodes.spec.ts")
    assert is_test_path("apps/api/src/store_test.rs")
    assert is_test_path("apps/api/tests/store.rs")
    assert not is_test_path("apps/web/src/lib/map/nodes.ts")
