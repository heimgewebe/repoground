from __future__ import annotations

import builtins
import importlib
import symtable
from pathlib import Path


MIXIN_MODULES = (
    "merger.repoground.frontends.pythonista.merger_ui_prescan",
    "merger.repoground.frontends.pythonista.merger_ui_browser",
    "merger.repoground.frontends.pythonista.merger_ui_merge_run",
)


def _external_class_globals(module) -> set[str]:
    source = Path(module.__file__).read_text(encoding="utf-8")
    table = symtable.symtable(source, module.__file__, "exec")
    class_table = next(child for child in table.get_children() if child.get_type() == "class")
    module_bound = {
        symbol.get_name()
        for symbol in table.get_symbols()
        if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()
    }
    referenced: set[str] = set()

    def collect(scope) -> None:
        referenced.update(
            symbol.get_name()
            for symbol in scope.get_symbols()
            if symbol.is_global() and symbol.is_referenced()
        )
        for child in scope.get_children():
            collect(child)

    collect(class_table)
    return referenced - module_bound - set(dir(builtins))


def test_mixin_build_global_contract_is_exact() -> None:
    for module_name in MIXIN_MODULES:
        module = importlib.import_module(module_name)
        assert set(module.BUILD_GLOBAL_NAMES) == _external_class_globals(module)


def test_build_wires_declared_mixin_globals() -> None:
    build = importlib.import_module("merger.repoground.frontends.pythonista.build")
    for module_name in MIXIN_MODULES:
        module = importlib.import_module(module_name)
        for name in module.BUILD_GLOBAL_NAMES:
            assert getattr(module, name) is getattr(build, name)
