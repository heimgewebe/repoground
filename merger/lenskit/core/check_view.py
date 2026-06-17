"""Read-only adapter for checks surfaces across output_health, post_emit_health,
and bundle_surface_validation.

Each producer emits ``checks`` in a different container shape:

- ``output_health["checks"]``            — mapping keyed by check name
  (values are scalars, booleans, or nested diagnostic dicts)
- ``post_emit_health["checks"]``         — ordered list of check objects
- ``bundle_surface_validation["checks"]`` — ordered list of check objects

This module provides a uniform read-only view over both shapes without modifying
any producer, schema, contract, or CLI output.  Scalars in the mapping shape are
preserved as-is with ``status=None`` so counters (e.g. ``chunk_count``) are never
silently promoted to status-bearing checks.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal

CheckContainerShape = Literal["mapping", "list"]


@dataclass(frozen=True)
class CheckView:
    """Uniform read-only view over a single check entry, regardless of container shape.

    Fields
    ------
    name
        The check key (mapping shape) or the ``name`` field (list shape).
    status
        String status extracted from the raw value when it is a nested dict
        with a string ``"status"`` key.  ``None`` for scalars (booleans,
        integers, etc.) in the mapping shape — a counter is not a status.
    detail
        String detail from the raw value's ``"detail"`` or ``"reason"`` key.
        ``None`` if absent, non-string, or the value is a scalar.
    validation
        The ``"validation"`` sub-mapping when present and actually a Mapping.
        ``None`` otherwise.
    value
        The raw entry value as emitted by the producer.  For the list shape
        this is the full check dict; for the mapping shape it is whatever the
        producer stored (scalar, bool, or nested dict).
    raw
        Alias for ``value``; kept explicit for symmetry.
    container_shape
        Whether this view was built from a mapping (``"mapping"``) or a list
        (``"list"``).
    """

    name: str
    status: str | None
    detail: str | None
    validation: Mapping[str, Any] | None
    value: Any
    raw: Any
    container_shape: CheckContainerShape


def iter_check_views(report: Mapping[str, Any]) -> Iterator[CheckView]:
    """Yield :class:`CheckView` objects for every entry in ``report["checks"]``.

    Handles both the mapping shape (output_health) and the list shape
    (post_emit_health / bundle_surface_validation) defensively:

    - Missing or ``None`` ``checks`` → yields nothing.
    - ``checks`` that is neither a Mapping nor a list (e.g. a bare string)
      → yields nothing.
    - List entries that are not Mappings → skipped.
    - List entries without a string ``"name"`` field → skipped.
    - Mapping entries whose key is not a string → skipped.

    For duplicate names in the list shape, all entries are yielded in order.
    """
    if not isinstance(report, Mapping):
        return

    checks = report.get("checks")
    if checks is None:
        return

    if isinstance(checks, Mapping):
        for name, value in checks.items():
            if not isinstance(name, str):
                continue
            if isinstance(value, Mapping):
                status_raw = value.get("status")
                status = status_raw if isinstance(status_raw, str) else None
                detail_raw = value.get("detail")
                if not isinstance(detail_raw, str):
                    detail_raw = value.get("reason")
                detail = detail_raw if isinstance(detail_raw, str) else None
                validation_raw = value.get("validation")
                validation: Mapping[str, Any] | None = (
                    validation_raw if isinstance(validation_raw, Mapping) else None
                )
            else:
                status = None
                detail = None
                validation = None
            yield CheckView(
                name=name,
                status=status,
                detail=detail,
                validation=validation,
                value=value,
                raw=value,
                container_shape="mapping",
            )
    elif isinstance(checks, list):
        for item in checks:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name")
            if not isinstance(name, str):
                continue
            status_raw = item.get("status")
            status = status_raw if isinstance(status_raw, str) else None
            detail_raw = item.get("detail")
            if not isinstance(detail_raw, str):
                detail_raw = item.get("reason")
            detail = detail_raw if isinstance(detail_raw, str) else None
            validation_raw = item.get("validation")
            validation = (
                validation_raw if isinstance(validation_raw, Mapping) else None
            )
            yield CheckView(
                name=name,
                status=status,
                detail=detail,
                validation=validation,
                value=item,
                raw=item,
                container_shape="list",
            )


def checks_by_name(report: Mapping[str, Any]) -> dict[str, CheckView]:
    """Return a ``{name: CheckView}`` dict for all entries in ``report["checks"]``.

    For duplicate names (possible in list-shaped checks with repeated entries),
    the **last** entry wins deterministically.  No exception is raised.
    """
    result: dict[str, CheckView] = {}
    for view in iter_check_views(report):
        result[view.name] = view
    return result


def check_by_name(report: Mapping[str, Any], name: str) -> CheckView | None:
    """Return the :class:`CheckView` for *name*, or ``None`` if not found.

    This convenience helper builds a temporary name index for each call. For
    multiple lookups against the same report, call :func:`checks_by_name`
    once and reuse the returned mapping.
    """
    return checks_by_name(report).get(name)
