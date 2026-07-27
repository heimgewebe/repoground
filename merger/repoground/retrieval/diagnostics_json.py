"""Strict JSON decoding shared by the optional diagnostics input paths."""

from __future__ import annotations

import json
from typing import Any, NoReturn


def strict_json_loads(document: str, *, source: str) -> Any:
    """Decode standards-compliant JSON and bound excessive nesting as input error."""

    def reject_non_finite_constant(value: str) -> NoReturn:
        raise ValueError(
            f"{source} contains non-finite JSON constant {value!r}, which is not permitted"
        )

    try:
        return json.loads(document, parse_constant=reject_non_finite_constant)
    except RecursionError as exc:
        raise ValueError(f"{source} exceeds the supported JSON nesting depth") from exc
