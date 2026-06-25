#!/usr/bin/env python3
"""Derive and verify the fixed-snapshot validates_schema flow manifest."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
import subprocess
from collections import Counter
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

AUDIT = "guard-relation-cards-v1b-validates-schema-audit.json"


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


@dataclass(frozen=True)
class Flow:
    source_path: str
    relation_owner_symbol: str
    relation_call_line: int
    engine_owner_symbol: str
    engine_call_line: int
    schema_path: str
    schema_fragment: str | None
    activation_condition: str
    target_scope: str
    schema_binding_origin: str
    resolved_engine: str
    validator_draft: str
    format_checker_mode: str
    dependency_requirement: str
    missing_dependency_outcome: str
    schema_requirement: str
    missing_schema_outcome: str
    meta_guard_present: bool
    schema_path_definition_line: int | None
    schema_load_line: int | None


@dataclass(frozen=True)
class MetaFlow:
    source_path: str
    engine_owner_symbol: str
    engine_call_line: int
    schema_path: str
    followed_by_instance_validation: bool
    schema_binding_verification: str


def typed_value(name: str, value: str) -> Any:
    if name in {
        "relation_call_line",
        "engine_call_line",
        "schema_path_definition_line",
        "schema_load_line",
    }:
        return int(value) if value else None
    if name in {"meta_guard_present", "followed_by_instance_validation"}:
        return value == "1"
    if name == "schema_fragment":
        return value or None
    return value


def parse_rows(names: list[str], rows: list[str], kind: type) -> tuple:
    require(names == [item.name for item in fields(kind)], f"field mismatch: {names}")
    records = []
    for number, row in enumerate(rows):
        values = row.split("|")
        require(len(values) == len(names), f"row {number}: {len(values)} fields")
        records.append(
            kind(**{
                name: typed_value(name, value)
                for name, value in zip(names, values, strict=True)
            })
        )
    return tuple(records)


def direct(flow: Flow) -> bool:
    return (
        flow.relation_owner_symbol == flow.engine_owner_symbol
        and flow.relation_call_line == flow.engine_call_line
    )


def semantic_key(flow: Flow) -> tuple[str, ...]:
    return (
        flow.source_path,
        flow.relation_owner_symbol,
        flow.engine_owner_symbol,
        flow.schema_path,
        flow.schema_fragment or "",
        flow.activation_condition,
        flow.target_scope,
    )


def snapshot_key(flow: Flow) -> tuple[str, ...]:
    return (
        flow.source_path,
        flow.relation_owner_symbol,
        str(flow.relation_call_line),
        flow.engine_owner_symbol,
        str(flow.engine_call_line),
        flow.schema_path,
        flow.schema_fragment or "",
        flow.activation_condition,
        flow.target_scope,
    )


def flow_id(base: str, flow: Flow) -> str:
    payload = "|".join((base, *snapshot_key(flow)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def axis(flows: tuple[Flow, ...], name: str) -> dict[str, int]:
    return dict(sorted(Counter(str(getattr(flow, name)) for flow in flows).items()))


def git(repo: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", repo, *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def inventory_sha(paths: list[str]) -> str:
    payload = "\n".join(sorted(set(paths))) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def scan_calls(source: str, path: str) -> tuple[set[tuple[str, int]], set[tuple[str, int]]]:
    tree = ast.parse(source, filename=path)
    engines: set[tuple[str, int]] = set()
    metas: set[tuple[str, int]] = set()
    stack: list[str] = []
    validate_aliases: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
            if node.module == "jsonschema":
                for item in node.names:
                    if item.name == "validate":
                        validate_aliases.add(item.asname or item.name)
            self.generic_visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            owner = stack[-1] if stack else "<module>"
            func = node.func
            if isinstance(func, ast.Name) and func.id in validate_aliases:
                engines.add((owner, node.lineno))
            elif isinstance(func, ast.Attribute):
                if func.attr in {"validate", "iter_errors"}:
                    engines.add((owner, node.lineno))
                elif func.attr == "check_schema":
                    metas.add((owner, node.lineno))
            self.generic_visit(node)

    Visitor().visit(tree)
    return engines, metas


def has_test_facet(infer_facets: Any, path: str) -> bool:
    return any(item.get("facet") == "test" for item in infer_facets(path))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo")
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest")
    args = parser.parse_args()
    manifest_path = Path(args.manifest) if args.manifest else (
        Path(__file__).resolve().parent.parent / AUDIT
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(args.base_sha == manifest["base"], "base mismatch")
    require(args.repo is not None, "--repo is required for the callsite gate")
    paths = sorted(set(git(args.repo, "ls-tree", "-r", "--name-only", args.base_sha).splitlines()))
    require(paths == sorted(paths), "inventory ordering")
    sys.path.insert(0, str(Path(args.repo).resolve()))
    from merger.lenskit.core.lens_facets import infer_facets
    require([len(paths), inventory_sha(paths)] == manifest["inv"], "inventory mismatch")
    flows = parse_rows(manifest["fields"], manifest["flows"], Flow)
    meta = parse_rows(manifest["meta_fields"], manifest["meta"], MetaFlow)
    accepted = tuple(flow for flow in flows if flow.target_scope == "in_repo")
    external = tuple(flow for flow in flows if flow.target_scope != "in_repo")

    discovered: set[tuple[str, str, int]] = set()
    discovered_meta: set[tuple[str, str, int]] = set()
    test_files: set[str] = set()
    text_files: set[str] = set()
    parse_failures: set[str] = set()
    for path in (item for item in paths if item.endswith(".py")):
        source = git(args.repo, "show", f"{args.base_sha}:{path}")
        if "jsonschema" in source:
            text_files.add(path)
        try:
            engines, metas = scan_calls(source, path)
        except SyntaxError:
            parse_failures.add(path)
            continue
        if has_test_facet(infer_facets, path):
            if engines:
                test_files.add(path)
            continue
        discovered.update((path, owner, line) for owner, line in engines)
        discovered_meta.update((path, owner, line) for owner, line in metas)
    require(
        parse_failures == {"merger/lenskit/tests/fixtures/entrypoints_test_project/invalid.py"},
        f"parse failures: {sorted(parse_failures)}",
    )
    reviewed = {
        (flow.source_path, flow.engine_owner_symbol, flow.engine_call_line)
        for flow in flows
    }
    require(
        discovered == reviewed,
        f"callsite mismatch: only_ast={sorted(discovered-reviewed)} "
        f"only_review={sorted(reviewed-discovered)}",
    )
    reviewed_meta = {
        (flow.source_path, flow.engine_owner_symbol, flow.engine_call_line)
        for flow in meta
    }
    require(discovered_meta == reviewed_meta, "meta callsite mismatch")
    non_test_text = {path for path in text_files if not has_test_facet(infer_facets, path)}
    engine_files = {path for path, _, _ in discovered}
    require(
        non_test_text - engine_files == set(manifest["text_only"]),
        "text-only candidate mismatch",
    )
    require(len(test_files) == manifest["summary"]["test_files"], "test file count")

    axes = {
        "engine_invocation": dict(sorted(Counter(
            "direct" if direct(flow) else "delegated" for flow in accepted
        ).items())),
        **{
            name: axis(accepted, name)
            for name in (
                "activation_condition",
                "dependency_requirement",
                "format_checker_mode",
                "missing_dependency_outcome",
                "missing_schema_outcome",
                "resolved_engine",
                "schema_binding_origin",
                "schema_requirement",
                "target_scope",
                "validator_draft",
            )
        },
    }
    summary = {
        "accepted_flows": len(accepted),
        "engine_callsites": len({
            (flow.source_path, flow.engine_owner_symbol, flow.engine_call_line)
            for flow in flows
        }),
        "external_flows": len(external),
        "meta_callsites": len({
            (flow.source_path, flow.engine_owner_symbol, flow.engine_call_line)
            for flow in meta
        }),
        "meta_flows": len(meta),
        "module_schema_targets": len({
            (flow.source_path, flow.schema_path) for flow in accepted
        }),
        "modules": len({flow.source_path for flow in accepted}),
        "schema_files": 54,
        "schema_targets": len({flow.schema_path for flow in accepted}),
        "schemas_without_relation": 36,
        "semantic_keys": len({semantic_key(flow) for flow in accepted}),
        "test_files": 45,
    }
    require(summary == manifest["summary"], f"summary mismatch: {summary}")
    require(axes["engine_invocation"] == {"delegated": 2, "direct": 22}, "invocation")
    require(axes["schema_requirement"] == {"optional": 3, "required": 21}, "schema")
    require(len({snapshot_key(flow) for flow in accepted}) == 24, "snapshot keys")
    require(len({flow_id(args.base_sha, flow) for flow in accepted}) == 24, "flow ids")
    require(
        all(
            flow.schema_fragment is None or flow.schema_fragment.startswith("#/")
            for flow in flows
        ),
        "schema fragment",
    )

    Path(args.output).write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(f"OK wrote {args.output} ({len(accepted)} accepted flows)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
