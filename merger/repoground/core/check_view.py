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
from copy import deepcopy
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


def compact_check_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return a compact by-name compatibility projection for ``report["checks"]``.

    The projection is a consumer-side convenience view. It does **not** modify
    producer shapes, schemas, contracts, or CLI output. It keeps the
    ``output_health`` mapping shape useful for existing by-name consumers while
    giving list-shaped check logs the same by-name lookup surface:

    - mapping-shaped checks keep their emitted value, deep-copied;
    - list-shaped checks become compact ``{"status": ..., "detail": ...,
      "validation": ...}`` dicts with absent fields omitted;
    - duplicate names deterministically keep the last emitted entry, matching
      :func:`checks_by_name`.

    This is not a truth, completeness, runtime, or test-sufficiency signal. It
    is only a shape bridge for read-only consumers that need a small stable
    lookup projection.
    """
    result: dict[str, Any] = {}
    for view in iter_check_views(report):
        if view.container_shape == "mapping":
            result[view.name] = deepcopy(view.value)
            continue

        projected: dict[str, Any] = {}
        if view.status is not None:
            projected["status"] = view.status
        if view.detail is not None:
            projected["detail"] = view.detail
        if view.validation is not None:
            projected["validation"] = deepcopy(dict(view.validation))
        result[view.name] = projected
    return result
