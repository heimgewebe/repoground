"""Observed Call Overlay v1: run-bound S2 relations as a separate artifact.

The overlay joins raw trace observations (:mod:`observed_call_trace`) to the
static Python Symbol Index namespace, so an agent can ask "which of these edges
did I actually see run" without the answer ever being mistaken for a static
resolution. Three properties are enforced by construction:

* every relation carries the observation identity (command, environment, run
  identity, source revision) it was recorded under;
* every relation is ``evidence_level: "S2"`` in its own record shape and is
  never written into the static graph's ``calls`` array;
* the document states in ``absence_semantics`` and ``does_not_establish`` that
  an unobserved relation is not thereby dead or unreachable.

Runtime code objects are bound to symbols by *exact anchor equality*, not by
range containment: CPython reports a decorated definition's ``co_firstlineno``
at its first decorator, so the anchor is computed the same way here. Anything
that does not match exactly one definition stays unbound and keeps its raw
runtime coordinates.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .observed_call_overlay_contract import (
    ABSENCE_SEMANTICS,
    BINDING_STATUSES,
    MAX_RELATIONS,
    MAX_SKIPPED_ERRORS,
    OBSERVED_EVIDENCE_LEVEL,
    OVERLAY_KIND,
    OVERLAY_VERSION,
    PRODUCER_NONCLAIMS,
    RELATION_TYPES,
)
from .observed_call_trace import (
    MODULE_FRAME_NAME,
    ObservedEdgeKey,
    TraceResult,
)
from .symbol_index import EXCLUDED_DIRS, _module_name, _symbol_id

_ANCHOR_KINDS = {
    ast.FunctionDef: "function",
    ast.AsyncFunctionDef: "async_function",
    ast.ClassDef: "class",
}


class _AnchorVisitor(ast.NodeVisitor):
    """Collect ``(name, code_first_line) -> symbol`` anchors for one file.

    The qualified-name stack and the id scheme are the ones the Python Symbol
    Index uses, so an overlay relation and a static call-graph relation address
    the same symbol namespace.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.module = _module_name(path)
        self.stack: list[str] = []
        self.anchors: dict[tuple[str, int], list[dict[str, Any]]] = {}

    def _record(self, node: ast.AST, name: str, kind: str) -> None:
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None) or start
        if not isinstance(start, int) or not isinstance(end, int):
            return
        decorators = [
            item.lineno
            for item in getattr(node, "decorator_list", [])
            if isinstance(getattr(item, "lineno", None), int)
        ]
        # CPython anchors a decorated definition's code object at its first
        # decorator line; an undecorated one at its ``def``/``class`` line.
        code_first_line = min([start, *decorators])
        qualified_name = ".".join([*self.stack, name])
        self.anchors.setdefault((name, code_first_line), []).append(
            {
                "id": _symbol_id(self.path, qualified_name, kind),
                "kind": kind,
                "name": name,
                "qualified_name": qualified_name,
                "module": self.module,
                "path": self.path,
                "start_line": start,
                "end_line": end,
            }
        )

    def _visit_scoped(self, node: ast.AST, name: str, kind: str) -> None:
        self._record(node, name, kind)
        self.stack.append(name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self._visit_scoped(node, node.name, "class")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._visit_scoped(node, node.name, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._visit_scoped(node, node.name, "async_function")


def _observed_paths(edges: Iterable[ObservedEdgeKey]) -> set[str]:
    """Return the repo-relative files the trace actually touched."""

    paths: set[str] = set()
    for key in edges:
        paths.add(key.callee_path)
        if key.caller_path is not None:
            paths.add(key.caller_path)
    return paths


def _repository_python_files(repo_root: Path) -> list[str]:
    files: list[str] = []
    for root, dirs, names in os.walk(repo_root, topdown=True):
        dirs[:] = sorted(item for item in dirs if item not in EXCLUDED_DIRS)
        for file_name in sorted(names):
            if file_name.endswith(".py"):
                files.append((Path(root) / file_name).relative_to(repo_root).as_posix())
    return files


def build_symbol_anchors(
    repo_root: Path,
    observed_paths: Iterable[str] | None = None,
) -> tuple[dict[str, dict[tuple[str, int], list[dict[str, Any]]]], int, list[str]]:
    """Return per-file runtime anchors for the files that need one.

    ``observed_paths`` restricts parsing to the files a trace actually touched.
    A trace over three files in a large repository has no reason to parse the
    whole tree, and the parse diagnostics then describe exactly the files whose
    anchors the overlay depends on. Passing ``None`` parses every Python file.
    """

    if observed_paths is None:
        candidates = _repository_python_files(repo_root)
    else:
        candidates = sorted(observed_paths)
    anchors: dict[str, dict[tuple[str, int], list[dict[str, Any]]]] = {}
    skipped_files_count = 0
    skipped_errors: list[str] = []
    for rel_path in candidates:
        path = repo_root / rel_path
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            skipped_files_count += 1
            if len(skipped_errors) < MAX_SKIPPED_ERRORS:
                skipped_errors.append(
                    f"Failed to parse {rel_path}: {type(exc).__name__} - {exc}"
                )
            continue
        visitor = _AnchorVisitor(rel_path)
        visitor.visit(tree)
        anchors[rel_path] = visitor.anchors
    return anchors, skipped_files_count, skipped_errors


def _endpoint(
    anchors: Mapping[str, Mapping[tuple[str, int], list[dict[str, Any]]]],
    *,
    path: str | None,
    name: str,
    first_line: int,
    prefix: str,
) -> dict[str, Any]:
    """Resolve one runtime code object to at most one repository symbol."""

    endpoint: dict[str, Any] = {
        f"{prefix}_path": path,
        f"{prefix}_runtime_name": name,
        f"{prefix}_runtime_first_line": first_line,
        f"{prefix}_symbol_id": None,
        f"{prefix}_qualified_name": None,
        f"{prefix}_kind": None,
        f"{prefix}_start_line": None,
        f"{prefix}_end_line": None,
    }
    if path is None:
        endpoint[f"{prefix}_binding_status"] = "unbound"
        endpoint[f"{prefix}_binding_reason"] = "path_outside_repository"
        return endpoint
    if name == MODULE_FRAME_NAME:
        endpoint[f"{prefix}_binding_status"] = "module_scope"
        endpoint[f"{prefix}_binding_reason"] = "module_frame"
        endpoint[f"{prefix}_kind"] = "module"
        return endpoint
    matches = anchors.get(path, {}).get((name, first_line), [])
    if len(matches) != 1:
        endpoint[f"{prefix}_binding_status"] = "unbound"
        endpoint[f"{prefix}_binding_reason"] = (
            "ambiguous_symbol_containment" if matches else "no_matching_symbol"
        )
        return endpoint
    symbol = matches[0]
    endpoint.update(
        {
            f"{prefix}_symbol_id": symbol["id"],
            f"{prefix}_qualified_name": symbol["qualified_name"],
            f"{prefix}_kind": symbol["kind"],
            f"{prefix}_start_line": symbol["start_line"],
            f"{prefix}_end_line": symbol["end_line"],
            f"{prefix}_binding_status": "bound",
            f"{prefix}_binding_reason": "unique_symbol_containment",
        }
    )
    return endpoint


def _relation(
    key: ObservedEdgeKey,
    observed_call_count: int,
    anchors: Mapping[str, Mapping[tuple[str, int], list[dict[str, Any]]]],
    observation_run_id: str,
) -> dict[str, Any]:
    caller = _endpoint(
        anchors,
        path=key.caller_path,
        name=key.caller_name,
        first_line=key.caller_first_line,
        prefix="caller",
    )
    callee = _endpoint(
        anchors,
        path=key.callee_path,
        name=key.callee_name,
        first_line=key.callee_first_line,
        prefix="callee",
    )
    # A line number without a repository file is not addressable evidence, so
    # a call site is only reported when the calling frame is repo-local.
    has_call_site = key.caller_path is not None and key.call_line >= 1
    return {
        "relation_type": "observed_calls",
        "evidence_level": OBSERVED_EVIDENCE_LEVEL,
        "observation_run_id": observation_run_id,
        "observed_call_count": observed_call_count,
        "call_site_line": key.call_line if has_call_site else None,
        "call_site_range_ref": (
            f"file:{key.caller_path}#L{key.call_line}-L{key.call_line}"
            if has_call_site
            else None
        ),
        **caller,
        **callee,
    }


def _counts(relations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Derive every counter in one pass over the relations."""

    binding_counts = {status: 0 for status in BINDING_STATUSES}
    observed_call_total = 0
    fully_bound_relation_count = 0
    for relation in relations:
        callee_status = relation["callee_binding_status"]
        binding_counts[callee_status] += 1
        observed_call_total += int(relation["observed_call_count"])
        if callee_status == "bound" and relation["caller_binding_status"] in (
            "bound",
            "module_scope",
        ):
            fully_bound_relation_count += 1
    return {
        "relation_count": len(relations),
        "observed_call_total": observed_call_total,
        "callee_binding_counts": binding_counts,
        "fully_bound_relation_count": fully_bound_relation_count,
    }


def build_observed_call_overlay_document(
    *,
    repo_root: Path,
    run_id: str,
    canonical_dump_index_sha256: str,
    observation: Mapping[str, Any],
    trace: TraceResult,
) -> dict[str, Any]:
    """Assemble one Observed Call Overlay v1 document from one trace."""

    repo_root = repo_root.resolve()
    anchors, skipped_files_count, anchor_errors = build_symbol_anchors(
        repo_root, _observed_paths(trace.edges)
    )
    observation_run_id = observation["observation_run_id"]
    # Select by frequency, emit in structural order: truncation must not drop
    # the hot edges an agent is most likely to be asking about, and the emitted
    # order must stay deterministic regardless of counts.
    selected = sorted(
        trace.edges,
        key=lambda key: (-trace.edges[key], key.sort_key()),
    )[:MAX_RELATIONS]
    relations = [
        _relation(key, trace.edges[key], anchors, observation_run_id)
        for key in sorted(selected, key=ObservedEdgeKey.sort_key)
    ]
    skipped_errors = [*trace.skipped_errors, *anchor_errors][:MAX_SKIPPED_ERRORS]
    # ``anchor_errors`` is capped; ``skipped_files_count`` is not. Using the
    # capped list here would understate how many files failed to parse.
    skipped_errors_total_count = trace.skipped_errors_total_count + skipped_files_count
    return {
        "kind": OVERLAY_KIND,
        "version": OVERLAY_VERSION,
        "run_id": run_id,
        "canonical_dump_index_sha256": canonical_dump_index_sha256,
        "language": "python",
        "evidence_model": {
            "S2": (
                "relation observed while one named command executed in one named "
                "environment at one named source revision"
            )
        },
        "relation_types": list(RELATION_TYPES),
        "binding_statuses": list(BINDING_STATUSES),
        "observation": dict(observation),
        "execution_outcome": {
            "exit_status": trace.exit_status,
            "exit_code": trace.exit_code,
            "observed_frame_event_count": trace.frame_event_count,
        },
        **_counts(relations),
        "relations": relations,
        "relations_truncated": len(trace.edges) > MAX_RELATIONS,
        "observed_relation_total_count": len(trace.edges),
        "skipped_files_count": skipped_files_count,
        "skipped_errors": skipped_errors,
        "skipped_errors_total_count": skipped_errors_total_count,
        "skipped_errors_truncated": skipped_errors_total_count > len(skipped_errors),
        "absence_semantics": ABSENCE_SEMANTICS,
        "does_not_establish": list(PRODUCER_NONCLAIMS),
    }


def generate_observed_call_overlay_document(
    repo_root: Path,
    run_id: str,
    canonical_sha256: str,
    command: Sequence[str],
    *,
    observed_at: str | None = None,
    observation_run_id: str | None = None,
    revision: Mapping[str, Any] | None = None,
    environment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Trace ``command`` and return its Observed Call Overlay v1 document.

    ``revision`` and ``environment`` are injectable so the overlay can be built
    from an already-established identity; by default both are read from the
    live checkout and interpreter. A revision that cannot be established is
    refused rather than recorded as unknown, because a relation that cannot
    name its source revision is not S2 evidence.
    """

    from .observed_call_trace import (
        environment_identity,
        observation_identity,
        source_revision,
        trace_command,
    )

    repo_root = repo_root.resolve()
    resolved_revision = dict(revision) if revision is not None else source_revision(repo_root)
    if resolved_revision.get("status") == "unavailable":
        raise ValueError(
            "observed call overlay requires a resolvable source revision; "
            f"git could not describe {repo_root}"
        )
    resolved_environment = (
        dict(environment) if environment is not None else environment_identity()
    )
    trace = trace_command(repo_root, command)
    observation = observation_identity(
        command=command,
        environment=resolved_environment,
        revision=resolved_revision,
        observed_at=observed_at,
        observation_run_id=observation_run_id,
    )
    return build_observed_call_overlay_document(
        repo_root=repo_root,
        run_id=run_id,
        canonical_dump_index_sha256=canonical_sha256,
        observation=observation,
        trace=trace,
    )


def observed_relation_keys(relations: Iterable[Mapping[str, Any]]) -> set[tuple[str, str]]:
    """Return ``(caller_symbol_id, callee_symbol_id)`` pairs of bound relations."""

    keys: set[tuple[str, str]] = set()
    for relation in relations:
        caller = relation.get("caller_symbol_id")
        callee = relation.get("callee_symbol_id")
        if isinstance(caller, str) and isinstance(callee, str):
            keys.add((caller, callee))
    return keys
