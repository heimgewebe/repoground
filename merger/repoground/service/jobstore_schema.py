from __future__ import annotations

import ast
import hashlib
import inspect
import io
import json
import textwrap
import tokenize
from typing import Any, Callable

from pydantic import BaseModel

# The persisted state contract is intentionally tied to the exact validation
# semantics shipped when JobStore v2 was introduced. These fingerprints were
# produced with the repository-pinned Pydantic 2.13.4 runtime. A model-schema
# change must introduce an explicit state migration/version instead of silently
# reinterpreting old bytes under new Pydantic semantics.
_FROZEN_MODEL_FINGERPRINTS = {
    "JobRequest": "36fefe1150a042be4063c602082073a630b1db99974ed481b3c7ca4a2a6851b1",
    "Job": "029357f703fd9070477788474ecb4cc975502de1e3af8983f845ae0e32f9d911",
    "Artifact": "20b6999a70176b5ea3ab3e008e847026ca2e75f374b6f89f072d00470164b806",
}
_SEMANTIC_CONFIG_KEYS = frozenset(
    {
        "extra",
        "strict",
        "populate_by_name",
        "validate_by_alias",
        "validate_by_name",
        "use_enum_values",
        "coerce_numbers_to_str",
        "regex_engine",
    }
)
_VALIDATOR_GROUPS = (
    "validators",
    "field_validators",
    "root_validators",
    "model_validators",
)
_PROJECT_VALIDATOR_PREFIX = "merger.repoground.service"
_SCHEMA_NOISE_KEYS = frozenset({"title", "description"})


def _strip_schema_noise(value: Any) -> Any:
    """Drop presentation-only JSON-Schema text while retaining semantics."""
    if isinstance(value, dict):
        return {
            key: _strip_schema_noise(item)
            for key, item in sorted(value.items())
            if key not in _SCHEMA_NOISE_KEYS
        }
    if isinstance(value, list):
        return [_strip_schema_noise(item) for item in value]
    return value


def _docstring_lines(source: str) -> set[int]:
    tree = ast.parse(source)
    lines: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            continue
        lines.update(range(first.lineno, getattr(first, "end_lineno", first.lineno) + 1))
    return lines


def _normalized_source_tokens(obj: Callable[..., Any] | type) -> list[tuple[str, str]]:
    """Fingerprint callable semantics without comments, docstrings or formatting."""
    target = obj.__func__ if inspect.ismethod(obj) else obj
    try:
        source = textwrap.dedent(inspect.getsource(target))
    except (OSError, TypeError) as exc:
        raise ValueError(f"cannot inspect persisted-state validator: {target!r}") from exc

    doc_lines = _docstring_lines(source)
    tokens: list[tuple[str, str]] = []
    replace_definition_name = False
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.start[0] in doc_lines:
            continue
        if token.type in {
            tokenize.ENDMARKER,
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.COMMENT,
            tokenize.ENCODING,
        }:
            continue
        if token.type == tokenize.INDENT:
            tokens.append(("INDENT", ""))
            continue
        if token.type == tokenize.DEDENT:
            tokens.append(("DEDENT", ""))
            continue
        if token.type == tokenize.NAME and token.string in {"def", "class"}:
            tokens.append(("NAME", token.string))
            replace_definition_name = True
            continue
        if replace_definition_name and token.type == tokenize.NAME:
            # A pure helper/validator rename is not persisted-state semantics.
            tokens.append(("NAME", "<callable>"))
            replace_definition_name = False
            continue
        tokens.append((tokenize.tok_name[token.type], token.string))
    return tokens


def _callable_graph(
    obj: Callable[..., Any] | type,
    *,
    seen: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    target = obj.__func__ if inspect.ismethod(obj) else obj
    identity = id(target)
    if identity in seen:
        return {"recursive": True}

    next_seen = seen | {identity}
    graph: dict[str, Any] = {
        "tokens": _normalized_source_tokens(target),
        "dependencies": [],
    }
    code = getattr(target, "__code__", None)
    globals_map = getattr(target, "__globals__", {})
    if code is None:
        return graph

    dependencies = []
    for name in sorted(set(code.co_names)):
        dependency = globals_map.get(name)
        dependency_target = (
            dependency.__func__ if inspect.ismethod(dependency) else dependency
        )
        if not (inspect.isfunction(dependency_target) or inspect.isclass(dependency_target)):
            continue
        if not str(getattr(dependency_target, "__module__", "")).startswith(
            _PROJECT_VALIDATOR_PREFIX
        ):
            continue
        dependencies.append(_callable_graph(dependency_target, seen=next_seen))
    graph["dependencies"] = dependencies
    return graph


def _validator_graphs(model: type[BaseModel]) -> list[dict[str, Any]]:
    decorators = model.__pydantic_decorators__
    graphs: list[dict[str, Any]] = []
    for group_name in _VALIDATOR_GROUPS:
        group = getattr(decorators, group_name)
        for _name, decorator in sorted(group.items()):
            graphs.append(
                {
                    "group": group_name,
                    "info": repr(decorator.info),
                    "source": _callable_graph(decorator.func),
                }
            )
    return graphs


def model_schema_fingerprint(model: type[BaseModel]) -> str:
    """Return a deterministic persisted-state validation fingerprint."""
    semantic_config = {
        key: model.model_config[key]
        for key in sorted(model.model_config)
        if key in _SEMANTIC_CONFIG_KEYS
    }
    payload = {
        "schema": _strip_schema_noise(model.model_json_schema(mode="validation")),
        "config": semantic_config,
        "validators": _validator_graphs(model),
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
    """Fail closed when live model semantics no longer match JobStore v1/v2."""
    expected = _FROZEN_MODEL_FINGERPRINTS.get(model.__name__)
    if expected is None:
        raise ValueError(f"unsupported persisted-state model: {model.__name__}")
    actual = model_schema_fingerprint(model)
    if actual != expected:
        raise ValueError(
            f"{model.__name__} schema fingerprint changed; explicit JobStore "
            f"state migration required (expected {expected}, got {actual})"
        )
