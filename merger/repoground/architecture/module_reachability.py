"""Conservative reachability evidence for production Python modules.

Static import analysis alone cannot decide whether a module is used: RepoGround
reaches modules through ``python -m`` entry points, CLI dispatch, lazy imports,
systemd units and shell wrappers. This module therefore collects *evidence of
use* from several surfaces and classifies every production module as either
``reachable`` (at least one piece of evidence) or ``unproven`` (none found).

``unproven`` is deliberately not ``dead``. The measurement is fail-closed in the
direction that matters for deletion: it can under-claim reachability, never
under-claim it in a way that would license removing live code.
"""

from __future__ import annotations

import ast
import functools
import os
import re
from pathlib import Path
from typing import Any, Iterable

from merger.repoground.architecture.path_classification import path_projection

_SKIP_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}

#: Text surfaces that can invoke a module without importing it in Python.
_RUNTIME_SUFFIXES = {
    ".cfg",
    ".ini",
    ".json",
    ".service",
    ".sh",
    ".timer",
    ".toml",
    ".yaml",
    ".yml",
}
_DOCUMENTATION_SUFFIXES = {".md", ".rst", ".txt"}

#: Directories that can actually invoke code. ``config/`` and ``docs/`` are
#: excluded on purpose: they hold policies, baselines and measurement artifacts
#: that merely *name* modules, and counting those as evidence would let a
#: recorded path masquerade as a live consumer.
_RUNTIME_DIRECTORIES = (
    ".github/",
    ".wgx/",
    "ops/",
    "scripts/",
    "tools/",
)

#: Evidence kinds that show use by a production or operational surface.
PRODUCTION_EVIDENCE = (
    "static_import_product",
    "static_import_script",
    "package_of_referenced_module",
    "package_data_reference",
    "module_main_block",
    "dynamic_string_reference",
    "runtime_surface_reference",
)

#: Evidence kinds that show use by the test suite alone. A test proves the
#: module is exercised, not that any production surface reaches it, so the two
#: classes are kept apart: a production module that only its own tests reach is
#: a distinct — and weaker — situation than one a shipped path reaches.
TEST_EVIDENCE = (
    "static_import_test",
    "package_of_test_referenced_module",
    "dynamic_string_reference_test",
)

#: Evidence kinds that show use by code rather than by prose.
NON_DOCUMENTATION_EVIDENCE = PRODUCTION_EVIDENCE + TEST_EVIDENCE


def _iter_files(repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    for root, directories, filenames in os.walk(repo_root):
        directories[:] = sorted(
            directory for directory in directories if directory not in _SKIP_DIRECTORIES
        )
        for filename in sorted(filenames):
            paths.append(Path(root) / filename)
    return paths


def _module_name(relative_path: str) -> str:
    dotted = relative_path[: -len(".py")].replace("/", ".")
    if dotted.endswith(".__init__"):
        return dotted[: -len(".__init__")]
    return dotted


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _resolve_relative(module_name: str, is_package: bool, node: ast.ImportFrom) -> str:
    """Resolve a relative import against the importing module's package."""

    parts = module_name.split(".")
    if not is_package:
        parts = parts[:-1]
    ascend = node.level - 1
    if ascend:
        parts = parts[: len(parts) - ascend] if ascend < len(parts) else []
    if node.module:
        parts = parts + node.module.split(".")
    return ".".join(parts)


def _package_name(module_name: str, is_package: bool) -> str:
    if is_package:
        return module_name
    return module_name.rpartition(".")[0]


def _resolve_local_absolute(
    imported_name: str,
    *,
    module_name: str,
    is_package: bool,
    known_modules: set[str],
) -> str:
    """Resolve script-style sibling imports only when a real module exists.

    Pythonista executes ``build.py`` with its own directory on ``sys.path``, so
    imports such as ``from build_utils import ...`` reach the sibling package
    module even though they are not written as relative imports. Guessing from
    the name alone would over-claim reachability; the qualified candidate must
    exist in the measured production-module inventory.
    """

    package = _package_name(module_name, is_package)
    candidate = f"{package}.{imported_name}" if package else imported_name
    if candidate in known_modules or any(
        name.startswith(f"{candidate}.") for name in known_modules
    ):
        return candidate
    return imported_name


def _imported_names(
    tree: ast.AST,
    module_name: str,
    is_package: bool,
    known_modules: set[str],
    *,
    allow_local_siblings: bool,
) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = alias.name
                if alias.name not in known_modules and allow_local_siblings:
                    resolved = _resolve_local_absolute(
                        alias.name,
                        module_name=module_name,
                        is_package=is_package,
                        known_modules=known_modules,
                    )
                names.add(resolved)
        elif isinstance(node, ast.ImportFrom):
            base = (
                _resolve_relative(module_name, is_package, node)
                if node.level
                else (
                    _resolve_local_absolute(
                        node.module or "",
                        module_name=module_name,
                        is_package=is_package,
                        known_modules=known_modules,
                    )
                    if allow_local_siblings
                    else (node.module or "")
                )
            )
            if not base:
                continue
            names.add(base)
            # ``from pkg import module`` is evidence for ``pkg.module`` only
            # when that exact production module exists. A function or class
            # imported from a module must not masquerade as a submodule.
            for alias in node.names:
                candidate = f"{base}.{alias.name}"
                if alias.name != "*" and candidate in known_modules:
                    names.add(candidate)
    return names


def _resource_strings(tree: ast.AST) -> set[str]:
    """Return literals that may name packaged data files, never modules."""

    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _dynamic_import_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    importlib_aliases: set[str] = set()
    import_module_names = {"__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            importlib_aliases.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "importlib"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            import_module_names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "import_module"
            )
    return importlib_aliases, import_module_names


def _literal_dynamic_import(
    node: ast.AST,
    *,
    importlib_aliases: set[str],
    import_module_names: set[str],
) -> str | None:
    if not isinstance(node, ast.Call) or not node.args:
        return None
    direct_call = isinstance(node.func, ast.Name) and node.func.id in import_module_names
    module_call = (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "import_module"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in importlib_aliases
    )
    first_argument = node.args[0]
    if not (direct_call or module_call):
        return None
    if not isinstance(first_argument, ast.Constant) or not isinstance(
        first_argument.value, str
    ):
        return None
    return first_argument.value


def _dynamic_module_strings(tree: ast.AST) -> set[str]:
    """Return literal module names passed to actual dynamic import APIs."""

    importlib_aliases, import_module_names = _dynamic_import_aliases(tree)
    return {
        value
        for node in ast.walk(tree)
        if (
            value := _literal_dynamic_import(
                node,
                importlib_aliases=importlib_aliases,
                import_module_names=import_module_names,
            )
        )
        is not None
    }


def _parse(text: str | None, path: Path) -> ast.AST | None:
    if text is None:
        return None
    try:
        return ast.parse(text, filename=str(path))
    except SyntaxError:
        return None


def _has_main_block(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        comparison = node.test
        if len(comparison.ops) != 1 or not isinstance(comparison.ops[0], ast.Eq):
            continue
        operands = [comparison.left, comparison.comparators[0]]
        has_name = any(
            isinstance(item, ast.Name) and item.id == "__name__" for item in operands
        )
        has_literal = any(
            isinstance(item, ast.Constant) and item.value == "__main__"
            for item in operands
        )
        if has_name and has_literal:
            return True
    return False


def _is_runtime_surface(relative_path: str, suffix: str) -> bool:
    """Decide whether a non-Python file can invoke a module."""

    in_runtime_directory = relative_path.startswith(_RUNTIME_DIRECTORIES)
    at_repository_root = "/" not in relative_path
    if not (in_runtime_directory or at_repository_root):
        return False
    return suffix in _RUNTIME_SUFFIXES or (not suffix and in_runtime_directory)


@functools.lru_cache(maxsize=2048)
def _token_pattern(needle: str) -> re.Pattern[str]:
    """Match ``needle`` only as a whole dotted name or path."""

    return re.compile(rf"(?<![\w./-]){re.escape(needle)}(?![\w./-])")


class _Corpus:
    """Concatenated text of one surface, searched by module name and path.

    Matching is token-exact: ``merger`` must not be credited for a mention of
    ``merger.repoground.core``. Over-claiming reachability would turn an unused
    module into a silent pass, so partial matches are rejected.
    """

    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._joined: str | None = None

    def add(self, text: str) -> None:
        self._chunks.append(text)
        self._joined = None

    def contains(self, *needles: str) -> bool:
        if self._joined is None:
            self._joined = "\n".join(self._chunks)
        return any(
            # The cheap substring test keeps the regex off the whole corpus for
            # the overwhelming majority of module names.
            needle in self._joined and _token_pattern(needle).search(self._joined)
            for needle in needles
        )


def _collect_source_evidence(
    parsed_sources: list[tuple[str, str, bool, ast.AST]],
    known_modules: set[str],
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
    imports_by_projection: dict[str, set[str]] = {
        "product": set(),
        "test": set(),
        "script": set(),
        "fixture": set(),
    }
    dynamic_strings_by_projection: dict[str, set[str]] = {}
    resource_strings_by_projection: dict[str, set[str]] = {}
    for projection, module_name, is_package, tree in parsed_sources:
        imports_by_projection.setdefault(projection, set()).update(
            _imported_names(
                tree,
                module_name,
                is_package,
                known_modules,
                allow_local_siblings=_has_main_block(tree),
            )
        )
        dynamic_strings_by_projection.setdefault(projection, set()).update(
            _dynamic_module_strings(tree)
        )
        resource_strings_by_projection.setdefault(projection, set()).update(
            _resource_strings(tree)
        )
    return (
        imports_by_projection,
        dynamic_strings_by_projection,
        resource_strings_by_projection,
    )


def measure_module_reachability(
    repo_root: Path,
    package_roots: Iterable[str] = ("merger",),
) -> dict[str, Any]:
    """Collect reachability evidence for every production module."""

    roots = tuple(package_roots)
    modules: dict[str, dict[str, Any]] = {}
    imports_by_projection: dict[str, set[str]] = {
        "product": set(),
        "test": set(),
        "script": set(),
        "fixture": set(),
    }
    dynamic_strings_by_projection: dict[str, set[str]] = {}
    resource_strings_by_projection: dict[str, set[str]] = {}
    parsed_sources: list[tuple[str, str, bool, ast.AST]] = []
    data_files: list[str] = []
    runtime_corpus = _Corpus()
    documentation_corpus = _Corpus()
    unparsed: list[str] = []
    unparsed_non_product: list[str] = []

    for path in _iter_files(repo_root):
        relative = path.relative_to(repo_root).as_posix()
        suffix = path.suffix.lower()

        if suffix == ".py":
            projection = path_projection(relative)
            text = _read_text(path)
            tree = _parse(text, path)
            if tree is None:
                # An unreadable product or script source could hide a module or
                # its imports, so it fails; deliberately invalid test fixtures
                # only under-claim evidence, which stays on the strict side.
                target = unparsed if projection in {"product", "script"} else unparsed_non_product
                target.append(relative)
                continue
            module_name = _module_name(relative)
            is_package = path.name == "__init__.py"
            parsed_sources.append((projection, module_name, is_package, tree))
            if projection == "product" and relative.startswith(
                tuple(f"{root}/" for root in roots)
            ):
                modules[module_name] = {
                    "path": relative,
                    "is_package": is_package,
                    "module_main_block": _has_main_block(tree),
                }
            continue

        data_files.append(relative)

        if _is_runtime_surface(relative, suffix):
            text = _read_text(path)
            if text is not None:
                runtime_corpus.add(text)
        elif suffix in _DOCUMENTATION_SUFFIXES:
            text = _read_text(path)
            if text is not None:
                documentation_corpus.add(text)

    (
        imports_by_projection,
        dynamic_strings_by_projection,
        resource_strings_by_projection,
    ) = _collect_source_evidence(parsed_sources, set(modules))

    # Production evidence may only be drawn from production and script sources.
    # Test sources form their own, weaker class so that a module the tests alone
    # reach cannot present itself as part of a shipped path.
    def _union(source: dict[str, set[str]], *projections: str) -> set[str]:
        return set().union(*(source.get(name, set()) for name in projections), set())

    production_imports = _union(imports_by_projection, "product", "script")
    all_imports = _union(imports_by_projection, *imports_by_projection)
    production_dynamic_strings = _union(
        dynamic_strings_by_projection, "product", "script"
    )
    test_dynamic_strings = _union(dynamic_strings_by_projection, "test", "fixture")
    production_resource_strings = _union(
        resource_strings_by_projection, "product", "script"
    )

    records = [
        _module_record(
            module_name,
            details,
            imports_by_projection=imports_by_projection,
            production_imports=production_imports,
            all_imports=all_imports,
            production_dynamic_strings=production_dynamic_strings,
            test_dynamic_strings=test_dynamic_strings,
            production_resource_strings=production_resource_strings,
            data_files=data_files,
            runtime_corpus=runtime_corpus,
            documentation_corpus=documentation_corpus,
        )
        for module_name, details in sorted(modules.items())
    ]

    unproven = [record["module"] for record in records if record["status"] == "unproven"]
    documentation_only = [
        record["module"]
        for record in records
        if record["status"] == "reachable" and not record["has_non_documentation_evidence"]
    ]
    test_only = [
        record["module"]
        for record in records
        if record["has_non_documentation_evidence"]
        and not record["has_production_evidence"]
    ]
    return {
        "kind": "repoground.module_reachability_measurement",
        "version": "1.0",
        "package_roots": list(roots),
        "module_count": len(records),
        "unproven": unproven,
        "documentation_only": documentation_only,
        "test_only": test_only,
        "unparsed_files": sorted(unparsed),
        "unparsed_non_product_files": sorted(unparsed_non_product),
        "modules": records,
        "does_not_establish": [
            "that an unproven module is dead",
            "that a reachable module is executed at runtime",
            "that a test-only module has a production consumer",
            "completeness of dynamic loader discovery",
            "that evidence surfaces are themselves used",
        ],
    }


def _referenced_data_file(
    data_file: str,
    package_directory: str,
    dynamic_strings: set[str],
) -> bool:
    """Report whether Python source names this packaged data file."""

    relative_inside_package = data_file[len(package_directory) :]
    return any(
        value == data_file
        or value == relative_inside_package
        or value.endswith(f"/{relative_inside_package}")
        for value in dynamic_strings
    )


def _package_evidence(
    module_name: str,
    relative_path: str,
    *,
    production_imports: set[str],
    all_imports: set[str],
    production_strings: set[str],
    data_files: list[str],
) -> str | None:
    """Return package-level evidence for a package with no production import."""

    prefix = f"{module_name}."
    # A package is reached whenever anything below it is imported.
    if any(name.startswith(prefix) for name in production_imports):
        return "package_of_referenced_module"
    # A package directory also ships the non-Python contract and schema files
    # that production code loads by path.
    package_directory = relative_path[: -len("__init__.py")]
    if any(
        data_file.startswith(package_directory)
        and _referenced_data_file(data_file, package_directory, production_strings)
        for data_file in data_files
    ):
        return "package_data_reference"
    if any(name.startswith(prefix) for name in all_imports):
        return "package_of_test_referenced_module"
    return None


def _names_module(module_name: str, relative_path: str, values: set[str]) -> bool:
    """Report whether any string literal names this module or its path.

    A dotted prefix match is deliberate — ``pkg.mod.attr`` references ``pkg.mod``
    — but it stops at the dot, so ``pkg.module_extra`` never credits ``pkg.module``.
    """

    prefix = f"{module_name}."
    return any(
        value == module_name or value == relative_path or value.startswith(prefix)
        for value in values
    )


def _import_evidence(
    module_name: str,
    imports_by_projection: dict[str, set[str]],
) -> list[str]:
    return [
        kind
        for projection, kind in (
            ("product", "static_import_product"),
            ("test", "static_import_test"),
            ("script", "static_import_script"),
        )
        if module_name in imports_by_projection.get(projection, set())
    ]


def _module_record(
    module_name: str,
    details: dict[str, Any],
    *,
    imports_by_projection: dict[str, set[str]],
    production_imports: set[str],
    all_imports: set[str],
    production_dynamic_strings: set[str],
    test_dynamic_strings: set[str],
    production_resource_strings: set[str],
    data_files: list[str],
    runtime_corpus: _Corpus,
    documentation_corpus: _Corpus,
) -> dict[str, Any]:
    relative_path = details["path"]
    evidence = _import_evidence(module_name, imports_by_projection)

    if details["is_package"] and not any(
        kind in PRODUCTION_EVIDENCE for kind in evidence
    ):
        package_evidence = _package_evidence(
            module_name,
            relative_path,
            production_imports=production_imports,
            all_imports=all_imports,
            production_strings=production_resource_strings,
            data_files=data_files,
        )
        if package_evidence is not None:
            evidence.append(package_evidence)

    if details["module_main_block"]:
        evidence.append("module_main_block")

    if _names_module(module_name, relative_path, production_dynamic_strings):
        evidence.append("dynamic_string_reference")
    elif _names_module(module_name, relative_path, test_dynamic_strings):
        evidence.append("dynamic_string_reference_test")

    if runtime_corpus.contains(module_name, relative_path):
        evidence.append("runtime_surface_reference")

    if documentation_corpus.contains(module_name, relative_path):
        evidence.append("documented_invocation")

    return {
        "module": module_name,
        "path": relative_path,
        "status": "reachable" if evidence else "unproven",
        "evidence": evidence,
        "has_non_documentation_evidence": any(
            kind in NON_DOCUMENTATION_EVIDENCE for kind in evidence
        ),
        "has_production_evidence": any(
            kind in PRODUCTION_EVIDENCE for kind in evidence
        ),
    }


def _declaration_findings(
    observed: list[str],
    allowed: Iterable[str],
    *,
    code: str,
    stale_code: str,
) -> list[dict[str, Any]]:
    """Require every observed module to be declared, and every declaration used."""

    declared = set(allowed)
    findings = [
        {"code": code, "module": module}
        for module in observed
        if module not in declared
    ]
    findings.extend(
        {"code": stale_code, "module": module}
        for module in sorted(declared - set(observed))
    )
    return findings


def evaluate_reachability_policy(
    measurement: dict[str, Any],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reject undeclared unproven, documentation-only and test-only modules."""

    findings = _declaration_findings(
        measurement["unproven"],
        policy.get("allowed_unproven") or [],
        code="module_reachability_unproven",
        stale_code="module_reachability_allowlist_stale",
    )

    if policy.get("require_non_documentation_evidence", True):
        findings += _declaration_findings(
            measurement["documentation_only"],
            policy.get("allowed_documentation_only") or [],
            code="module_reachability_documentation_only",
            stale_code="module_reachability_documentation_allowlist_stale",
        )

    if policy.get("require_production_evidence", True):
        # A production module that only its own tests reach is not proven to be
        # part of any production path. It is not dead either, so it is declared
        # rather than removed, and the declaration must stay accurate.
        findings += _declaration_findings(
            measurement["test_only"],
            policy.get("allowed_test_only") or [],
            code="module_reachability_test_only",
            stale_code="module_reachability_test_only_allowlist_stale",
        )

    if measurement["unparsed_files"]:
        findings.append(
            {
                "code": "module_reachability_unparsed_sources",
                "files": measurement["unparsed_files"],
            }
        )
    return findings
