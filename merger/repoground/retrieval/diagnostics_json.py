"""Strict JSON decoding shared by the optional diagnostics input paths."""

from __future__ import annotations

import json
from typing import Any, NoReturn


MAX_JSON_NESTING_DEPTH = 256


def _check_json_nesting_depth(document: str, *, source: str) -> None:
    nesting_depth = 0
    in_string = False
    escaped = False

    for character in document:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character in "[{":
            nesting_depth += 1
            if nesting_depth > MAX_JSON_NESTING_DEPTH:
                raise ValueError(
                    f"{source} exceeds the supported JSON nesting depth"
                )
        elif character in "]}":
            nesting_depth = max(0, nesting_depth - 1)


def strict_json_loads(document: str, *, source: str) -> Any:
    """Decode standards-compliant JSON and bound excessive nesting as input error."""

    def reject_non_finite_constant(value: str) -> NoReturn:
        raise ValueError(
            f"{source} contains non-finite JSON constant {value!r}, which is not permitted"
        )

    _check_json_nesting_depth(document, source=source)
    try:
        return json.loads(document, parse_constant=reject_non_finite_constant)
    except RecursionError as exc:
        raise ValueError(f"{source} exceeds the supported JSON nesting depth") from exc
