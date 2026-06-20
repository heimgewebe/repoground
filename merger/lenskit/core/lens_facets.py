from __future__ import annotations

import re
from collections import Counter
from pathlib import PurePosixPath
from typing import Any, Iterable

KIND = "lenskit.lens_facet_report"
VERSION = "1.0"

# Shared lens-family negative-semantics baseline. Identical to the Primary Lens
# Audit baseline (docs/architecture/lens-model.md section 15): a facet is derived
# navigation and establishes none of these. Emitted in this exact, fixed order;
# the v1 contract pins both the values and the order.
DOES_NOT_ESTABLISH = (
    "truth",
    "correctness",
    "completeness",
    "runtime_behavior",
    "test_sufficiency",
    "regression_absence",
    "semantic_importance",
    "review_priority",
    "change_impact",
)

# Controlled v1 facet vocabulary. Additive navigation axes only. Deliberately
# small: each facet is derived from a single controlled path/suffix rule with
# clear positive and negative examples. Candidates such as artifact_surface,
# diagnostic, claim_boundary, security and uncertainty are intentionally
# deferred (see docs/proofs/facet-model-v1-proof.md).
FACET_IDS = ("contract", "test", "retrieval")

# General lens-model derivation vocabulary (docs/architecture/lens-model.md
# section 5). Future, structurally derived facet rules may use derived/heuristic.
# This describes HOW an assignment was produced, not its confidence/quality, and
# carries no implicit ordering.
DERIVATION_TYPES = ("direct", "derived", "heuristic")

# Facet Model v1 only ever emits — and its contract only permits — this single
# derivation type. No synthetic derived/heuristic assignments are produced.
V1_DERIVATION_TYPE = "direct"

# Controlled source-rule vocabulary. Exactly one rule per facet in v1, so a
# (path, facet) pair can never be produced by two competing rules; rule
# collisions are therefore structurally impossible in this slice.
SOURCE_RULES = (
    "contract_schema_suffix",
    "test_module_marker",
    "retrieval_surface_path",
)

# Bound facet -> its single v1 source rule.
FACET_SOURCE_RULES = {
    "contract": "contract_schema_suffix",
    "test": "test_module_marker",
    "retrieval": "retrieval_surface_path",
}

# Controlled test-MODULE markers, intentionally narrower than the broad "guards"
# Primary Lens (which also absorbs validation, CI and guard surfaces).
# - test_*.py and test_*.js are real, frequent repo conventions.
# - *_test.py, *.test.ts and *.spec.ts mirror the existing infer_lens markers.
_TEST_PREFIX_EXTENSIONS = (".py", ".js")
_TEST_FILENAME_SUFFIXES = ("_test.py", ".test.ts", ".spec.ts")

# A path segment that, when present, marks fixture data: such files are never the
# `test` facet even if their filename matches a test marker. Exact segment match
# only — never a free substring like "fixture".
_FIXTURE_SEGMENT = "fixtures"

# Controlled path segment for the retrieval subsystem surface. v1 treats every
# file on a controlled retrieval surface as `retrieval`, including retrieval
# fixtures; the facet asserts a retrieval-related surface, not production status.
_RETRIEVAL_SEGMENT = "retrieval"

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _normalize_path(path: str | PurePosixPath) -> str:
    """Return the host-independent canonical repo-relative POSIX path.

    Accepts only ``str`` or ``PurePosixPath``. String inputs are lexically strict
    and never silently normalized (non-canonical inputs like ``./a``, ``a/./b``,
    ``a//b``, backslashes, or Windows drive prefixes are rejected rather than
    rewritten). Native ``Path`` on POSIX hosts is accepted merely due to its
    type relationship to ``PurePosixPath``; it carries no portable cross-platform
    guarantee. Any other type — notably ``PureWindowsPath`` — raises ``TypeError``
    rather than being silently coerced.
    """
    if isinstance(path, str):
        raw = path
    elif isinstance(path, PurePosixPath):
        raw = path.as_posix()
    else:
        raise TypeError(
            "lens facet path must be str or PurePosixPath, "
            f"got {type(path).__name__}"
        )

    if not raw.strip():
        raise ValueError("lens facet path must not be empty")
    if "\\" in raw:
        raise ValueError("lens facet path must use POSIX separators")
    if _WINDOWS_DRIVE_RE.match(raw):
        raise ValueError("lens facet path must not carry a Windows drive prefix")
    if raw.startswith("/"):
        raise ValueError("lens facet path must be repo-relative")
    if raw.endswith("/"):
        raise ValueError("lens facet path must not end with a slash")

    for component in raw.split("/"):
        if component == "":
            raise ValueError("lens facet path must not contain empty components")
        if component in {".", ".."}:
            raise ValueError(
                "lens facet path must not contain '.' or '..' components"
            )

    return raw


def _is_contract_schema(posix: str) -> bool:
    """contract: the path carries the controlled `.schema.json` file extension."""
    return posix.endswith(".schema.json")


def _is_test_module(name: str, parts: tuple[str, ...]) -> bool:
    """test: the path is itself a test module by controlled filename marker.

    Files under a `fixtures` path segment are excluded: a fixture that merely
    happens to be named test_*.py is data, not a test module.
    """
    if _FIXTURE_SEGMENT in parts:
        return False
    if name.startswith("test_") and name.endswith(_TEST_PREFIX_EXTENSIONS):
        return True
    return name.endswith(_TEST_FILENAME_SUFFIXES)


def _is_retrieval_surface(parts: tuple[str, ...]) -> bool:
    """retrieval: the path lives on a controlled `retrieval` surface.

    Includes retrieval fixtures (Variant A): the facet marks a retrieval-related
    surface and does not claim production status.
    """
    return _RETRIEVAL_SEGMENT in parts


def _facet_item(posix: str, facet: str) -> dict[str, Any]:
    return {
        "path": posix,
        "facet": facet,
        "source_rule": FACET_SOURCE_RULES[facet],
        "derivation_type": V1_DERIVATION_TYPE,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _infer_facets_normalized(posix: str) -> list[dict[str, Any]]:
    """Facet assignments for an already-normalized canonical POSIX path.

    POSIX components are derived directly from the canonical string (no
    ``pathlib`` re-parsing), so classification is host-independent.
    """
    parts = tuple(posix.split("/"))
    name = parts[-1]
    items: list[dict[str, Any]] = []

    if _is_contract_schema(posix):
        items.append(_facet_item(posix, "contract"))
    if _is_test_module(name, parts):
        items.append(_facet_item(posix, "test"))
    if _is_retrieval_surface(parts):
        items.append(_facet_item(posix, "retrieval"))

    return items


def infer_facets(path: str | PurePosixPath) -> list[dict[str, Any]]:
    """Return the deterministic facet assignments for a single repo path.

    The result is a list of (path, facet) assignment dicts and may be empty: a
    path that matches no controlled rule simply carries no facet. There is no
    synthetic ``unknown``/``other`` facet. A path may carry several distinct
    facets (cardinality 0..n). This function performs no I/O, reads no file
    content, and does not consult the environment, git or the network.
    """
    return _infer_facets_normalized(_normalize_path(path))


def produce_facet_report(paths: Iterable[str | PurePosixPath]) -> dict[str, Any]:
    """Aggregate deterministic facet assignments over many repo paths.

    This is an *assignment* report, not an evaluation/coverage report: only
    actually produced (path, facet) assignments appear in ``items``. A checked
    path that carries no facet does not appear and is indistinguishable from a
    path that was never passed in. ``target_count`` counts only distinct paths
    that carry at least one facet.

    Assignments are identified by ``(path, facet)``: duplicate inputs and
    repeated runs produce identical output. Items are stably sorted by
    ``(path, facet)``; the order carries no semantic priority.
    """
    seen: set[tuple[str, str]] = set()
    items: list[dict[str, Any]] = []
    for path in paths:
        for item in infer_facets(path):
            key = (item["path"], item["facet"])
            if key in seen:
                continue
            seen.add(key)
            items.append(item)

    items.sort(key=lambda item: (item["path"], item["facet"]))

    facet_counts: Counter[str] = Counter(item["facet"] for item in items)
    target_count = len({item["path"] for item in items})

    return {
        "kind": KIND,
        "version": VERSION,
        "items": items,
        "summary": {
            "item_count": len(items),
            "target_count": target_count,
            "facet_counts": {
                facet: facet_counts[facet] for facet in sorted(facet_counts)
            },
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
