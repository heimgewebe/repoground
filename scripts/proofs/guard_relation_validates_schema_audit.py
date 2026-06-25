#!/usr/bin/env python3
"""Hermetic, falsifiable audit for the ``validates_schema`` target proof.

Diagnosis-only. This is NOT a production relation contract, producer or runtime
validator. It reads a *fixed historical snapshot* (never the working tree),
re-derives an independent observation set with a deliberately narrow, declared
jsonschema grammar, and verifies the manually reviewed flow manifest against it.
Mismatches fail closed.

Design (separation of powers):

  reviewed inputs (manual)        derived observations (machine)
  - flow manifest rows       +    - base-bound infer_facets
  - meta manifest rows            - receiver-resolved engine/meta callsites
  - text-only explanations        - resolved vs. unresolved partition
          \\                       - schema-file coverage from the tree
           \\                      - test-facet inventory from the snapshot
            +--> comparison gate (require, fail-closed) --> derived report

The committed audit JSON keeps the reviewed inputs verbatim and replaces the
``derived`` section with a freshly computed one. A tampered manifest row (wrong
callsite, missing schema, foreign ``.validate``) makes a gate fail, so the
comparison is not a tautology. Gates use ``require`` / ``AuditError`` (never
``assert``) so they stay active under ``python -O``.

Grammar boundary: only jsonschema receivers reachable by intra-module static
binding are ``derived_ast``. Validators obtained through a project-local loader
(``_load_jsonschema`` / ``importlib.import_module``) are ``manual_source_review``
and listed explicitly; any *new* unresolved candidate fails the audit.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

AUDIT_FILENAME = "guard-relation-cards-v1b-validates-schema-audit.json"
# Committed audit lives in docs/proofs/; this script lives in scripts/proofs/.
DEFAULT_MANIFEST = (
    Path(__file__).resolve().parent.parent.parent
    / "docs" / "proofs" / AUDIT_FILENAME
)
LENS_FACETS_PATH = "merger/lenskit/core/lens_facets.py"
JSONSCHEMA_CONSTRUCTORS = {
    "Draft3Validator", "Draft4Validator", "Draft6Validator",
    "Draft7Validator", "Draft201909Validator", "Draft202012Validator",
}


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


# ---------------------------------------------------------------------------
# Reviewed-input typing
# ---------------------------------------------------------------------------
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
        "relation_call_line", "engine_call_line",
        "schema_path_definition_line", "schema_load_line",
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
        records.append(kind(**{
            name: typed_value(name, value)
            for name, value in zip(names, values, strict=True)
        }))
    return tuple(records)


# ---------------------------------------------------------------------------
# Snapshot access (read-only, hermetic, isolated git env)
# ---------------------------------------------------------------------------
def git(repo: str, *args: str) -> str:
    env = dict(os.environ)
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        LC_ALL="C",
    )
    return subprocess.run(
        ["git", "-C", repo, *args],
        check=True, capture_output=True, text=True, env=env,
    ).stdout


def inventory_sha(paths: list[str]) -> str:
    payload = "\n".join(sorted(set(paths))) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_base_infer_facets(repo: str, base_sha: str):
    """Load infer_facets from the BASE snapshot, never the working tree."""
    source = git(repo, "show", f"{base_sha}:{LENS_FACETS_PATH}")
    import types
    module = types.ModuleType("lens_facets_base")
    exec(compile(source, f"{LENS_FACETS_PATH}@{base_sha[:12]}", "exec"), module.__dict__)  # noqa: S102
    facets = getattr(module, "infer_facets", None)
    require(callable(facets), "base snapshot lens_facets.infer_facets missing")
    return facets


# ---------------------------------------------------------------------------
# Receiver-resolved jsonschema grammar
# ---------------------------------------------------------------------------
def analyze(source: str, path: str):
    """Return resolved engine, resolved meta, and unresolved candidate sets.

    Sets contain ``(owner_symbol, lineno)``; unresolved entries add a kind tag
    (``unresolved_engine`` / ``unresolved_meta``).
    """
    tree = ast.parse(source, filename=path)

    module_aliases: set[str] = set()       # names bound to the jsonschema module
    validate_aliases: set[str] = set()     # names bound to jsonschema.validate
    constructor_aliases: set[str] = set()  # names bound to a Draft*Validator class
    validators_modules: set[str] = set()   # names bound to jsonschema.validators

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "jsonschema":
                    module_aliases.add(alias.asname or "jsonschema")
                elif alias.name == "jsonschema.validators":
                    validators_modules.add(alias.asname or "jsonschema.validators")
        elif isinstance(node, ast.ImportFrom) and node.module == "jsonschema":
            for alias in node.names:
                if alias.name == "validate":
                    validate_aliases.add(alias.asname or alias.name)
                elif alias.name in JSONSCHEMA_CONSTRUCTORS:
                    constructor_aliases.add(alias.asname or alias.name)
                elif alias.name == "validators":
                    validators_modules.add(alias.asname or alias.name)

    def is_constructor_call(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Name) and func.id in constructor_aliases:
            return True
        if (isinstance(func, ast.Attribute) and func.attr in JSONSCHEMA_CONSTRUCTORS
                and isinstance(func.value, ast.Name) and func.value.id in module_aliases):
            return True
        if isinstance(func, ast.Call):  # validator_for(schema)(...)
            inner = func.func
            if isinstance(inner, ast.Attribute) and inner.attr == "validator_for":
                if isinstance(inner.value, ast.Name) and inner.value.id in (module_aliases | validators_modules):
                    return True
        return False

    engines: set[tuple[str, int]] = set()
    metas: set[tuple[str, int]] = set()
    unresolved: set[tuple[str, int, str]] = set()

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []
            self.validator_vars: list[set[str]] = [set()]

        def _enter(self, node):
            self.stack.append(node.name)
            current = set(self.validator_vars[-1])
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Assign) and is_constructor_call(stmt.value):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            current.add(target.id)
            self.validator_vars.append(current)
            self.generic_visit(node)
            self.validator_vars.pop()
            self.stack.pop()

        visit_FunctionDef = _enter
        visit_AsyncFunctionDef = _enter

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            owner = self.stack[-1] if self.stack else "<module>"
            func = node.func
            vvars = self.validator_vars[-1]
            kind: str | None = None
            if isinstance(func, ast.Name) and func.id in validate_aliases:
                kind = "engine"
            elif isinstance(func, ast.Attribute):
                recv = func.value
                if func.attr in {"validate", "iter_errors"}:
                    if isinstance(recv, ast.Name) and recv.id in module_aliases and func.attr == "validate":
                        kind = "engine"
                    elif isinstance(recv, ast.Name) and recv.id in vvars:
                        kind = "engine"
                    elif is_constructor_call(recv):
                        kind = "engine"
                    else:
                        kind = "unresolved_engine"
                elif func.attr == "check_schema":
                    if isinstance(recv, ast.Name) and recv.id in (module_aliases | constructor_aliases):
                        kind = "meta"
                    elif (isinstance(recv, ast.Attribute) and recv.attr in JSONSCHEMA_CONSTRUCTORS
                          and isinstance(recv.value, ast.Name) and recv.value.id in module_aliases):
                        kind = "meta"
                    elif isinstance(recv, ast.Name) and recv.id in vvars:
                        kind = "meta"
                    else:
                        kind = "unresolved_meta"
            if kind == "engine":
                engines.add((owner, node.lineno))
            elif kind == "meta":
                metas.add((owner, node.lineno))
            elif kind in {"unresolved_engine", "unresolved_meta"}:
                unresolved.add((owner, node.lineno, kind))
            self.generic_visit(node)

    Visitor().visit(tree)
    return engines, metas, unresolved


# ---------------------------------------------------------------------------
# Derived helpers
# ---------------------------------------------------------------------------
def direct(flow: Flow) -> bool:
    return (flow.relation_owner_symbol == flow.engine_owner_symbol
            and flow.relation_call_line == flow.engine_call_line)


def semantic_key(flow: Flow) -> tuple[str, ...]:
    return (flow.source_path, flow.relation_owner_symbol, flow.engine_owner_symbol,
            flow.schema_path, flow.schema_fragment or "", flow.activation_condition,
            flow.target_scope)


def snapshot_key(flow: Flow) -> tuple[str, ...]:
    return (flow.source_path, flow.relation_owner_symbol, str(flow.relation_call_line),
            flow.engine_owner_symbol, str(flow.engine_call_line), flow.schema_path,
            flow.schema_fragment or "", flow.activation_condition, flow.target_scope)


def axis(flows: tuple[Flow, ...], name: str) -> dict[str, int]:
    return dict(sorted(Counter(str(getattr(f, name)) for f in flows).items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hermetic validates_schema audit")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest")
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest) if args.manifest else DEFAULT_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(args.base_sha == manifest["base"], "base mismatch")

    tree_oid = git(args.repo, "rev-parse", f"{args.base_sha}^{{tree}}").strip()
    raw = git(args.repo, "ls-tree", "-r", "--name-only", args.base_sha).splitlines()
    paths = sorted(set(raw))
    require([len(paths), inventory_sha(paths)] == manifest["inv"], "inventory mismatch")

    infer_facets = load_base_infer_facets(args.repo, args.base_sha)

    def is_test(path: str) -> bool:
        return any(item.get("facet") == "test" for item in infer_facets(path))

    flows = parse_rows(manifest["fields"], manifest["flows"], Flow)
    meta = parse_rows(manifest["meta_fields"], manifest["meta"], MetaFlow)
    accepted = tuple(f for f in flows if f.target_scope == "in_repo")
    external = tuple(f for f in flows if f.target_scope != "in_repo")

    # ---- derive observations from the snapshot --------------------------
    resolved_engine: set[tuple[str, str, int]] = set()
    resolved_meta: set[tuple[str, str, int]] = set()
    unresolved_prod: set[tuple[str, str, int, str]] = set()
    test_resolved: set[str] = set()
    test_unresolved_only: set[str] = set()
    text_files: set[str] = set()
    parse_failures: set[str] = set()
    schema_files = sorted(p for p in paths if p.endswith(".schema.json"))

    for path in (p for p in paths if p.endswith(".py")):
        source = git(args.repo, "show", f"{args.base_sha}:{path}")
        if "jsonschema" in source:
            text_files.add(path)
        try:
            engines, metas, unresolved = analyze(source, path)
        except SyntaxError:
            parse_failures.add(path)
            continue
        if is_test(path):
            if engines:
                test_resolved.add(path)
            elif unresolved:
                test_unresolved_only.add(path)
            continue
        resolved_engine.update((path, owner, line) for owner, line in engines)
        resolved_meta.update((path, owner, line) for owner, line in metas)
        unresolved_prod.update((path, owner, line, kind) for owner, line, kind in unresolved)

    expected_parse_failures = set(manifest.get(
        "expected_parse_failures",
        ["merger/lenskit/tests/fixtures/entrypoints_test_project/invalid.py"],
    ))
    require(
        parse_failures == expected_parse_failures,
        f"parse failures: unexpected={sorted(parse_failures - expected_parse_failures)} "
        f"missing={sorted(expected_parse_failures - parse_failures)}",
    )

    # ---- reviewed callsite sets ----------------------------------------
    reviewed_engine = {(f.source_path, f.engine_owner_symbol, f.engine_call_line) for f in flows}
    reviewed_meta = {(m.source_path, m.engine_owner_symbol, m.engine_call_line) for m in meta}

    # The manual-review set is derived from the AST itself: callsites the narrow
    # grammar could not resolve (project-local loader / importlib indirection).
    # It is NOT a manifest-declared field, so it cannot be self-attested.
    manual_engine = {(p, o, ln) for p, o, ln, k in unresolved_prod if k == "unresolved_engine"}
    manual_meta = {(p, o, ln) for p, o, ln, k in unresolved_prod if k == "unresolved_meta"}

    # ---- falsifiable comparison gate -----------------------------------
    # Every reviewed engine callsite must be corroborated by the snapshot AST at
    # the exact (path, owner, line): either receiver-resolved or flagged as an
    # unresolved candidate. A wrong line, a missing row, an extra row or a *new*
    # unresolved candidate all break this exact-equality gate.
    require(
        resolved_engine | manual_engine == reviewed_engine,
        "engine callsite mismatch: "
        f"only_review={sorted(reviewed_engine - (resolved_engine | manual_engine))} "
        f"only_ast={sorted((resolved_engine | manual_engine) - reviewed_engine)}",
    )
    require(
        resolved_meta | manual_meta == reviewed_meta,
        "meta callsite mismatch: "
        f"only_review={sorted(reviewed_meta - (resolved_meta | manual_meta))} "
        f"only_ast={sorted((resolved_meta | manual_meta) - reviewed_meta)}",
    )

    # text-only candidate explanation must stay exhaustive
    engine_files = {p for p, _, _ in resolved_engine} | {p for p, _, _ in manual_engine}
    non_test_text = {p for p in text_files if not is_test(p)}
    require(
        non_test_text - engine_files == set(manifest["text_only"]),
        "text-only candidate mismatch: "
        f"{sorted((non_test_text - engine_files) ^ set(manifest['text_only']))}",
    )

    # ---- derive schema coverage (no hard-coded totals) -----------------
    in_repo_schema_targets = sorted({f.schema_path for f in accepted})
    require(all(s in set(paths) for s in in_repo_schema_targets), "schema target missing from tree")
    schemas_with_relation = sorted(set(schema_files) & set(in_repo_schema_targets))
    schemas_without_relation = sorted(set(schema_files) - set(schemas_with_relation))

    # ---- derive aggregates ---------------------------------------------
    summary = {
        "accepted_flows": len(accepted),
        "engine_callsites": len(reviewed_engine),
        "external_flows": len(external),
        "meta_callsites": len(reviewed_meta),
        "meta_flows": len(meta),
        "module_schema_targets": len({(f.source_path, f.schema_path) for f in accepted}),
        "modules": len({f.source_path for f in accepted}),
        "schema_files": len(schema_files),
        "schema_targets": len(in_repo_schema_targets),
        "schemas_without_relation": len(schemas_without_relation),
        "semantic_keys": len({semantic_key(f) for f in accepted}),
        "test_files": len(test_resolved | test_unresolved_only),
    }
    if "summary" in manifest:  # bootstrap safety vs the prior committed shape
        require(summary == manifest["summary"], f"summary mismatch: {summary}")
    require(len({snapshot_key(f) for f in accepted}) == len(accepted), "snapshot keys not unique")

    axes = {
        "engine_invocation": dict(sorted(Counter(
            "direct" if direct(f) else "delegated" for f in accepted).items())),
        **{name: axis(accepted, name) for name in (
            "activation_condition", "dependency_requirement", "format_checker_mode",
            "missing_dependency_outcome", "missing_schema_outcome", "resolved_engine",
            "schema_binding_origin", "schema_requirement", "target_scope", "validator_draft",
        )},
    }

    derived = {
        "snapshot_tree_oid": tree_oid,
        "generated_from_historical_snapshot": True,
        "current_head_not_assessed": True,
        "runtime_execution_not_proven": True,
        "provenance": {
            "engine_callsites_derived_ast": len(resolved_engine),
            "engine_callsites_manual_source_review": len(manual_engine),
            "meta_callsites_derived_ast": len(resolved_meta),
            "meta_callsites_manual_source_review": len(manual_meta),
        },
        "engine_callsites": {
            "derived_ast": sorted(f"{p}|{o}|{ln}" for p, o, ln in resolved_engine),
            "manual_source_review": sorted(f"{p}|{o}|{ln}" for p, o, ln in manual_engine),
        },
        "meta_callsites": {
            "derived_ast": sorted(f"{p}|{o}|{ln}" for p, o, ln in resolved_meta),
            "manual_source_review": sorted(f"{p}|{o}|{ln}" for p, o, ln in manual_meta),
        },
        "schema_coverage": {
            "total": len(schema_files),
            "with_accepted_relation": len(schemas_with_relation),
            "without_accepted_relation": len(schemas_without_relation),
            "with_accepted_relation_files": schemas_with_relation,
            "without_accepted_relation_files": schemas_without_relation,
        },
        "test_inventory": {
            "classification": "base-snapshot lens_facets.infer_facets (facet == 'test')",
            "resolved_engine_count": len(test_resolved),
            "unresolved_only_count": len(test_unresolved_only),
            "union_count": len(test_resolved | test_unresolved_only),
            "resolved_engine_files": sorted(test_resolved),
            "unresolved_only_files": sorted(test_unresolved_only),
        },
        "parse_failures": sorted(parse_failures),
        "axes": axes,
        "summary": summary,
        "checks": [
            "base_bound_infer_facets",
            "receiver_resolved_grammar",
            "resolved_engine_subset_of_reviewed",
            "engine_coverage_resolved_plus_manual_equals_reviewed",
            "no_new_unresolved_engine_candidate",
            "meta_coverage_resolved_plus_manual_equals_reviewed",
            "no_new_unresolved_meta_candidate",
            "text_only_exhaustive",
            "schema_targets_present_in_tree",
            "schema_coverage_closed",
            "summary_recomputed_from_flows",
            "snapshot_keys_unique",
        ],
        "limitations": [
            "Validators reached only through a project-local loader "
            "(_load_jsonschema / importlib.import_module) are manual_source_review, not derived_ast.",
            "Intermodular alias passing, dynamic wrappers and non-jsonschema validators are out of grammar.",
            "External (metarepo) schema targets are not resolved against any external snapshot.",
            "load_only / path_reference_only callsites are not inventoried.",
            "Runtime execution and current HEAD are not assessed.",
        ],
    }

    out = {k: manifest[k] for k in (
        "base", "inv", "grammar", "limits", "fields", "flows",
        "meta_fields", "meta", "text_only", "expected_parse_failures",
    ) if k in manifest}
    out["derived"] = derived

    Path(args.output).write_text(
        json.dumps(out, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"OK wrote {args.output}: {len(accepted)} in-repo flows, {len(external)} external; "
        f"engine derived {len(resolved_engine)} + manual {len(manual_engine)}; "
        f"meta derived {len(resolved_meta)} + manual {len(manual_meta)}; "
        f"tests resolved {len(test_resolved)} + unresolved-only {len(test_unresolved_only)}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
