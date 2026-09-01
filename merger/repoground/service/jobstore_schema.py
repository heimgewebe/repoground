from __future__ import annotations

import ast
import enum
import functools
import hashlib
import inspect
import json
import re
import textwrap
import types
from collections.abc import Mapping
from functools import lru_cache
from typing import Any, Callable

import pydantic
from pydantic import BaseModel

# Frozen under the repository-pinned Pydantic 2.13.4 runtime. The fingerprint is
# deliberately based on pydantic-core's *actual validation schema* plus the full
# model_config and project-validator dependency graph. Changing validation
# semantics requires an explicit JobStore migration/version instead of silently
# reinterpreting old bytes.
_FROZEN_MODEL_FINGERPRINTS = {
    "JobRequest": "649a27a1aa9f14984373faae53013a338301abb4220cd140b55a6af5e0075ae2",
    "Job": "f0992e03ffc1b56aecbed0afb2ce5ca5911566813c908077d2cfab8240d1369b",
    "Artifact": "9a35d00c0c76d20883366f0612b058a32a95030fed4e6e54598527b16b77eea0",
}
_PROJECT_PREFIX = "merger.repoground.service"
_REF_RE = re.compile(r"^(?:.+\.)?([A-Za-z_][\w]*):\d+$")
_ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]+")
_UNHANDLED = object()


class _NormalizeAst(ast.NodeTransformer):
    """Remove non-semantic source noise while retaining executable structure."""

    @staticmethod
    def _drop_docstring(node: ast.AST) -> None:
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            return
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node.body = body[1:]  # type: ignore[attr-defined]

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        self.generic_visit(node)
        node.name = "<callable>"
        node.decorator_list = []
        node.returns = None
        node.type_comment = None
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            arg.annotation = None
            arg.type_comment = None
        if node.args.vararg is not None:
            node.args.vararg.annotation = None
        if node.args.kwarg is not None:
            node.args.kwarg.annotation = None
        self._drop_docstring(node)
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        self.generic_visit(node)
        node.name = "<class>"
        node.decorator_list = []
        self._drop_docstring(node)
        return node


def _target(obj: Callable[..., Any] | type) -> Callable[..., Any] | type:
    return obj.__func__ if inspect.ismethod(obj) else obj


def _normalized_ast(obj: Callable[..., Any] | type) -> str:
    target = _target(obj)
    try:
        source = textwrap.dedent(inspect.getsource(target))
    except (OSError, TypeError) as exc:
        raise ValueError(f"cannot inspect persisted-state validator: {target!r}") from exc
    tree = _NormalizeAst().visit(ast.parse(source))
    ast.fix_missing_locations(tree)
    return ast.dump(tree, include_attributes=False)


def _qualified_name(obj: Any) -> str:
    return (
        f"{getattr(obj, '__module__', '')}:"
        f"{getattr(obj, '__qualname__', getattr(obj, '__name__', type(obj).__name__))}"
    )


def _is_project_object(obj: Any) -> bool:
    return str(getattr(obj, "__module__", "")).startswith(_PROJECT_PREFIX)


def _attribute_chain(node: ast.Attribute) -> tuple[str, list[str]] | None:
    attrs: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        attrs.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    return current.id, list(reversed(attrs))


def _module_attribute_dependencies(
    target: Callable[..., Any],
    globals_map: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve module-qualified globals actually referenced by a validator."""
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(target)))
    except (OSError, TypeError) as exc:
        raise ValueError(f"cannot inspect persisted-state validator: {target!r}") from exc

    dependencies: dict[str, Any] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        chain = _attribute_chain(node)
        if chain is None:
            continue
        root, attrs = chain
        value = globals_map.get(root)
        if not isinstance(value, types.ModuleType):
            continue
        current: Any = value
        resolved = True
        for attr in attrs:
            if not hasattr(current, attr):
                resolved = False
                break
            current = getattr(current, attr)
        if resolved:
            dependencies[f"{root}.{'.'.join(attrs)}"] = current
    return dependencies


def _normalize_ref(value: str) -> str:
    match = _REF_RE.match(value)
    return f"<model>:{match.group(1)}" if match else value


def _stable_float(value: float) -> Any:
    if value != value:
        return {"float": "nan"}
    if value == float("inf"):
        return {"float": "inf"}
    if value == float("-inf"):
        return {"float": "-inf"}
    return value


def _stable_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return _stable_float(value)
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, enum.Enum):
        return {"enum": _qualified_name(type(value)), "value": _stable_value(value.value)}
    if isinstance(value, re.Pattern):
        return {"regex": value.pattern, "flags": value.flags}
    return _UNHANDLED


def _stable_container(value: Any, *, seen: frozenset[int]) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _stable_value(item, seen=seen)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_stable_value(item, seen=seen) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_stable_value(item, seen=seen) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if isinstance(value, types.ModuleType):
        return {"module": value.__name__}
    return _UNHANDLED


def _stable_type(value: type) -> Any:
    if issubclass(value, BaseModel):
        return {"model_class": value.__name__}
    if _is_project_object(value):
        return {"project_class": _normalized_ast(value)}
    return {"type": _qualified_name(value)}


def _stable_callable(value: Any, *, seen: frozenset[int]) -> Any:
    if isinstance(value, type):
        return _stable_type(value)
    if inspect.isfunction(value) or inspect.ismethod(value):
        target = _target(value)
        if _is_project_object(target):
            return {"project_callable": _callable_graph(target, seen=seen)}
        return {"callable": _qualified_name(target)}
    if isinstance(value, functools.partial):
        return {
            "partial": _stable_value(value.func, seen=seen),
            "args": _stable_value(value.args, seen=seen),
            "keywords": _stable_value(value.keywords or {}, seen=seen),
        }
    return _UNHANDLED


def _stable_value(
    value: Any,
    *,
    seen: frozenset[int] = frozenset(),
) -> Any:
    scalar = _stable_scalar(value)
    if scalar is not _UNHANDLED:
        return scalar
    container = _stable_container(value, seen=seen)
    if container is not _UNHANDLED:
        return container
    callable_value = _stable_callable(value, seen=seen)
    if callable_value is not _UNHANDLED:
        return callable_value

    return {
        "object": f"{type(value).__module__}:{type(value).__qualname__}",
        "repr": _ADDRESS_RE.sub("<addr>", repr(value)),
    }


def _callable_graph(
    obj: Callable[..., Any],
    *,
    seen: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    target = _target(obj)
    identity = id(target)
    if identity in seen:
        return {"recursive": True}
    if not inspect.isfunction(target):
        raise ValueError(f"persisted-state validator is not inspectable: {target!r}")

    next_seen = seen | {identity}
    closure = inspect.getclosurevars(target)
    dependencies: dict[str, Any] = {}
    for name, value in sorted(closure.globals.items()):
        dependencies[name] = _stable_value(value, seen=next_seen)
    for name, value in sorted(closure.nonlocals.items()):
        dependencies[f"nonlocal:{name}"] = _stable_value(value, seen=next_seen)
    for name, value in sorted(
        _module_attribute_dependencies(target, closure.globals).items()
    ):
        dependencies[f"module_attr:{name}"] = _stable_value(value, seen=next_seen)

    return {
        "ast": _normalized_ast(target),
        "deps": dependencies,
        "defaults": _stable_value(target.__defaults__, seen=next_seen),
        "kwdefaults": _stable_value(target.__kwdefaults__, seen=next_seen),
    }


def _canonical_core_schema(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for child_key, child in sorted(value.items()):
            if child_key == "metadata":
                # CoreSchema metadata feeds JSON-schema/annotations and is not
                # consumed by pydantic-core's input validation.
                continue
            if child_key in {"ref", "schema_ref"} and isinstance(child, str):
                result[child_key] = _normalize_ref(child)
                continue
            if child_key == "config" and isinstance(child, dict):
                # Core validation config is complete here; only `title` is a
                # presentation label and does not participate in validation.
                result[child_key] = {
                    config_key: _canonical_core_schema(config_value, key=config_key)
                    for config_key, config_value in sorted(child.items())
                    if config_key != "title"
                }
                continue
            result[child_key] = _canonical_core_schema(child, key=child_key)
        return result
    if isinstance(value, (list, tuple)):
        return [_canonical_core_schema(item, key=key) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_canonical_core_schema(item, key=key) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if key in {"ref", "schema_ref"} and isinstance(value, str):
        return _normalize_ref(value)
    return _stable_value(value)


@lru_cache(maxsize=None)
def model_schema_fingerprint(model: type[BaseModel]) -> str:
    """Return the deterministic persisted-state validation fingerprint."""
    payload = {
        "pydantic_version": pydantic.__version__,
        "core_schema": _canonical_core_schema(model.__pydantic_core_schema__),
        # Use the complete model_config, not a hand-maintained allowlist: options
        # such as str_strip_whitespace/validate_default affect input semantics.
        "model_config": _stable_value(dict(model.model_config)),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def assert_frozen_model_schema(model: type[BaseModel]) -> None:
    """Fail closed when live semantics no longer match JobStore v1/v2."""
    expected = _FROZEN_MODEL_FINGERPRINTS.get(model.__name__)
    if expected is None:
        raise ValueError(f"unsupported persisted-state model: {model.__name__}")
    actual = model_schema_fingerprint(model)
    if actual != expected:
        raise ValueError(
            f"{model.__name__} schema fingerprint changed; explicit JobStore "
            f"state migration required (expected {expected}, got {actual})"
        )
