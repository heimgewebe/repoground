#!/usr/bin/env python3
"""Reproducible diagnosis audit for the ``validates_schema`` guard-relation target proof.

This is **diagnosis-only** tooling. It is NOT production code, NOT a producer,
NOT a runtime validator and NOT part of any contract. It reads a fixed Git base
snapshot (never the working tree), classifies JSON-Schema instance-validation
relations into a stable callsite-flow identity, cross-checks the candidate
surface and emits a deterministic, byte-stable JSON report.

Design constraints (see the target proof, section 37):
  * standard library only, plus the repo's own ``infer_facets`` for test
    classification (loaded from the base snapshot, stdlib-only itself);
  * reads file contents via ``git show <base>:<path>`` and ``git ls-tree``;
  * no timestamps, no absolute local paths, no network, no repo mutation;
  * deterministic ordering -> two runs are byte-identical;
  * exits non-zero on any unexplained candidate or failed assertion.

Limitations (intentional):
  * The accepted relation table is *manually reviewed* and embedded here; the
    AST/text sweeps only act as a completeness gate for the candidate surface,
    not as proof of the individual schema flows.
  * Only validation against ``*.schema.json`` files is modelled. Validation
    against inline or non-repo schemas is reported as external / not accepted.
  * ``load_only`` / ``path_reference_only`` callsites are NOT inventoried.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import types

EXPECTED_BASE_SHA = "05bbd0d608afa8faf581887a455d4dcf6fa15ae9"
EXPECTED_INVENTORY_SHA256 = (
    "19ccdd599e32d683b97d71a86b05594b825440bda1b900d32a756517f637b50a"
)

CONTRACTS = "merger/lenskit/contracts/"

IDENTITY_FIELDS = (
    "source_path",
    "relation_owner_symbol",
    "engine_owner_symbol",
    "engine_call_line",
    "schema_path",
    "schema_fragment",
    "activation_condition",
    "target_scope",
)

VALID_TARGET_SCOPES = {"in_repo", "external_static_relative", "unresolved_dynamic"}
VALID_ENGINE_INVOCATION = {"direct", "delegated"}
VALID_BINDING = {
    "same_symbol_literal",
    "same_module_constant",
    "same_module_loader",
    "caller_parameter",
    "runtime_external_root",
}
VALID_DEP_REQ = {
    "required_at_module_import",
    "optional_module_import",
    "dynamic_runtime_import",
    "dependency_injected",
    "unknown",
}
VALID_DEP_OUT = {
    "module_import_failure",
    "raises_runtime_error",
    "raises_domain_error",
    "returns_blocked",
    "returns_environment_error",
    "returns_failed_check_skipped_unavailable",
    "warn_and_continue",
    "silent_skip",
    "structural_fallback",
    "not_applicable",
    "unknown",
}
VALID_SCHEMA_REQ = {"required", "optional", "external_optional", "unknown"}
VALID_SCHEMA_OUT = {
    "raises_runtime_error",
    "raises_domain_error",
    "returns_blocked",
    "returns_environment_error",
    "warn_and_continue",
    "silent_skip",
    "structural_fallback",
    "not_applicable",
    "unknown",
}


# ---------------------------------------------------------------------------
# Git helpers (read-only, base-snapshot bound)
# ---------------------------------------------------------------------------
def _git(repo: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", repo, *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def list_tree(repo: str, base_sha: str) -> list[str]:
    out = _git(repo, "ls-tree", "-r", "--name-only", base_sha)
    paths = [line for line in out.splitlines() if line]
    return sorted(set(paths))


def show(repo: str, base_sha: str, path: str) -> str:
    return _git(repo, "show", f"{base_sha}:{path}")


def inventory_sha256(paths: list[str]) -> str:
    blob = ("\n".join(sorted(set(paths))) + "\n").encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# infer_facets loaded from the base snapshot (stdlib-only module)
# ---------------------------------------------------------------------------
def load_infer_facets(repo: str, base_sha: str):
    src = show(repo, base_sha, "merger/lenskit/core/lens_facets.py")
    module = types.ModuleType("lens_facets_base")
    exec(compile(src, "lens_facets.py@base", "exec"), module.__dict__)  # noqa: S102
    return module.infer_facets


def has_test_facet(infer_facets, path: str) -> bool:
    return any(item.get("facet") == "test" for item in infer_facets(path))


# ---------------------------------------------------------------------------
# AST candidate generator
# ---------------------------------------------------------------------------
INSTANCE_APIS = {"validate", "iter_errors"}
META_API = "check_schema"


def scan(src: str, path: str):
    """Return (instance_calls, meta_calls) or raise SyntaxError."""
    tree = ast.parse(src, filename=path)
    instance_calls: list[int] = []
    meta_calls: list[int] = []

    class V(ast.NodeVisitor):
        def visit_Call(self, node):  # noqa: N802
            f = node.func
            if isinstance(f, ast.Attribute):
                if f.attr in INSTANCE_APIS:
                    instance_calls.append(node.lineno)
                elif f.attr == META_API:
                    meta_calls.append(node.lineno)
            self.generic_visit(node)

    V().visit(tree)
    return instance_calls, meta_calls


# ---------------------------------------------------------------------------
# Reviewed relation table (each entry manually verified against the source).
# ---------------------------------------------------------------------------
def F(
    source_path,
    relation_owner_symbol,
    engine_owner_symbol,
    engine_call_line,
    schema_path,
    validator_draft,
    format_checker_mode,
    dependency_requirement,
    missing_dependency_outcome,
    schema_requirement,
    missing_schema_outcome,
    schema_binding_origin,
    resolved_engine,
    schema_path_definition_line,
    schema_load_line,
    instance_flow_summary,
    schema_flow_summary,
    schema_fragment=None,
    activation_condition="unconditional",
    target_scope="in_repo",
    engine_invocation="direct",
    meta_guard_present=False,
):
    item = {
        "source_path": source_path,
        "relation_owner_symbol": relation_owner_symbol,
        "engine_owner_symbol": engine_owner_symbol,
        "engine_call_line": engine_call_line,
        "schema_path": schema_path,
        "schema_fragment": schema_fragment,
        "activation_condition": activation_condition,
        "target_scope": target_scope,
        "engine_invocation": engine_invocation,
        "schema_binding_origin": schema_binding_origin,
        "resolved_engine": resolved_engine,
        "validator_draft": validator_draft,
        "format_checker_mode": format_checker_mode,
        "dependency_requirement": dependency_requirement,
        "missing_dependency_outcome": missing_dependency_outcome,
        "schema_requirement": schema_requirement,
        "missing_schema_outcome": missing_schema_outcome,
        "meta_guard_present": meta_guard_present,
        "evidence": {
            "schema_path_definition_line": schema_path_definition_line,
            "schema_load_line": schema_load_line,
            "engine_call_line": engine_call_line,
            "instance_flow_summary": instance_flow_summary,
            "schema_flow_summary": schema_flow_summary,
        },
    }
    item["relation_flow_id"] = "|".join(str(item[k]) for k in IDENTITY_FIELDS)
    return item


def build_accepted_flows() -> list[dict]:
    A = "merger/lenskit/"
    flows = [
        F(A + "architecture/graph_index.py", "load_graph_index", "load_graph_index", 39,
          CONTRACTS + "architecture.graph_index.v1.schema.json", "auto-selected", "none",
          "optional_module_import", "warn_and_continue", "optional", "silent_skip",
          "same_symbol_literal", "jsonschema.validate", 31, 38,
          "graph-index document parsed from disk", "local literal schema_path, json.load"),
        F(A + "cli/policy_loader.py", "load_and_validate_embedding_policy",
          "load_and_validate_embedding_policy", 45,
          CONTRACTS + "embedding-policy.v1.schema.json", "auto-selected", "none",
          "optional_module_import", "raises_domain_error", "required", "raises_domain_error",
          "same_symbol_literal", "jsonschema.validate", 29, 35,
          "policy instance parsed from disk", "local literal schema_path, json.load"),
        F(A + "cli/pr_schau_verify.py", "verify_basic", "verify_basic", 80,
          CONTRACTS + "pr-schau.v1.schema.json", "auto-selected", "none",
          "optional_module_import", "warn_and_continue", "required", "raises_runtime_error",
          "caller_parameter", "jsonschema.validate", 36, 71,
          "bundle data passed in by caller", "module SCHEMA_PATH loaded by load_schema(), passed in"),
        F(A + "core/agent_export_gate.py", "_validate_post_health_schema",
          "_validate_post_health_schema", 262,
          CONTRACTS + "post-emit-health.v1.schema.json", "auto-selected", "none",
          "optional_module_import", "silent_skip", "required", "returns_blocked",
          "same_symbol_literal", "jsonschema.validate", 255, 261,
          "post_emit_health doc passed in", "local literal schema_path, json.load"),
        F(A + "core/doc_freshness.py", "validate_registry", "validate_registry", 668,
          CONTRACTS + "doc-freshness-registry.v1.schema.json", "draft7", "none",
          "dynamic_runtime_import", "structural_fallback", "required", "raises_runtime_error",
          "caller_parameter", "Draft7Validator.iter_errors", 468, 665,
          "registry data passed in", "schema_path parameter (default_schema_path literal), json.loads"),
        F(A + "core/federation.py", "init_federation", "init_federation", 59,
          CONTRACTS + "federation-index.v1.schema.json", "auto-selected", "none",
          "optional_module_import", "raises_runtime_error", "required", "raises_runtime_error",
          "same_module_loader", "jsonschema.validate", 24, 27,
          "freshly built federation index", "load_federation_schema() module loader"),
        F(A + "core/federation.py", "validate_federation", "validate_federation", 87,
          CONTRACTS + "federation-index.v1.schema.json", "auto-selected", "none",
          "optional_module_import", "raises_runtime_error", "required", "raises_runtime_error",
          "same_module_loader", "jsonschema.validate", 24, 27,
          "federation index read from disk", "load_federation_schema() module loader"),
        F(A + "core/federation.py", "add_bundle", "add_bundle", 156,
          CONTRACTS + "federation-index.v1.schema.json", "auto-selected", "none",
          "optional_module_import", "raises_runtime_error", "required", "raises_runtime_error",
          "same_module_loader", "jsonschema.validate", 24, 27,
          "existing federation index pre-validated before mutation",
          "load_federation_schema() module loader"),
        F(A + "core/federation.py", "add_bundle", "add_bundle", 187,
          CONTRACTS + "federation-index.v1.schema.json", "auto-selected", "none",
          "optional_module_import", "raises_runtime_error", "required", "raises_runtime_error",
          "same_module_loader", "jsonschema.validate", 24, 27,
          "mutated federation index re-validated before write",
          "load_federation_schema() module loader"),
        F(A + "core/forensic_preflight.py", "_validate_claim_map_schema",
          "_validate_claim_map_schema", 119,
          CONTRACTS + "claim-evidence-map.v1.schema.json", "auto-selected", "none",
          "optional_module_import", "returns_blocked", "required", "returns_blocked",
          "same_symbol_literal", "jsonschema.validate", 114, 115,
          "claim-evidence-map document passed in", "local literal schema_path, _load_json"),
        F(A + "core/lens_card_validate.py", "validate_lens_card", "validate_lens_card", 136,
          CONTRACTS + "lens-card.v1.schema.json", "draft7", "none",
          "dynamic_runtime_import", "returns_failed_check_skipped_unavailable",
          "required", "returns_blocked",
          "same_module_loader", "Draft7Validator.iter_errors", 27, 68,
          "lens card passed in", "_load_default_schema() module loader (_SCHEMA_PATH)",
          meta_guard_present=True),
        F(A + "core/parity_state.py", "_validate_citation_map", "_validate_citation_map", 349,
          CONTRACTS + "citation-map.v1.schema.json", "auto-selected", "none",
          "optional_module_import", "raises_domain_error", "required", "raises_domain_error",
          "same_symbol_literal", "jsonschema.validate", 313, 314,
          "each citation row validated in a loop", "local literal schema_path, _read_json"),
        F(A + "core/post_emit_health.py", "_validate_claim_evidence_map_schema",
          "_validate_claim_evidence_map_schema", 331,
          CONTRACTS + "claim-evidence-map.v1.schema.json", "auto-selected", "none",
          "optional_module_import", "returns_environment_error", "required",
          "returns_environment_error",
          "same_symbol_literal", "jsonschema.validate", 324, 330,
          "claim-evidence-map document passed in", "local literal schema_path, json.load"),
        F(A + "core/post_emit_health.py", "_validate_manifest_schema",
          "_validate_manifest_schema", 404,
          CONTRACTS + "bundle-manifest.v1.schema.json", "auto-selected", "none",
          "optional_module_import", "returns_environment_error", "required",
          "returns_environment_error",
          "same_symbol_literal", "jsonschema.validate", 396, 403,
          "bundle manifest passed in", "local literal schema_path, json.load"),
        F(A + "core/pr_delta_card_validate.py", "validate_pr_delta_card",
          "validate_pr_delta_card", 135,
          CONTRACTS + "pr-delta-card.v1.schema.json", "draft7", "FormatChecker",
          "dynamic_runtime_import", "returns_failed_check_skipped_unavailable",
          "required", "returns_blocked",
          "same_module_loader", "Draft7Validator.iter_errors", 30, 71,
          "pr delta card passed in", "_load_default_schema() module loader (_SCHEMA_PATH)",
          meta_guard_present=True),
        F(A + "core/pr_delta_cards.py", "_validate_source_delta", "_validate_source_delta", 105,
          CONTRACTS + "pr-schau-delta.v1.schema.json", "draft2020-12", "custom_date_time_checker",
          "dynamic_runtime_import", "raises_domain_error", "required", "raises_runtime_error",
          "same_module_loader", "Draft202012Validator.iter_errors", 38, 58,
          "source delta passed in", "_load_source_schema() module loader (_SOURCE_SCHEMA_PATH)",
          meta_guard_present=True),
        F(A + "core/pr_schau_bundle.py", "load_pr_schau_bundle", "load_pr_schau_bundle", 130,
          CONTRACTS + "pr-schau.v1.schema.json", "auto-selected", "none",
          "optional_module_import", "silent_skip", "optional", "silent_skip",
          "same_module_loader", "jsonschema.validate", 27, 60,
          "bundle data read from disk", "module SCHEMA_PATH loaded by _load_schema()"),
        F(A + "core/range_resolver.py", "resolve_range_ref", "resolve_range_ref", 193,
          CONTRACTS + "range-ref.v1.schema.json", "auto-selected", "none",
          "optional_module_import", "raises_runtime_error", "required", "raises_runtime_error",
          "same_module_constant", "jsonschema.validate", 16, 44,
          "range_ref instance validated", "module constant _RANGE_REF_V1_SCHEMA_PATH via _load_schema",
          activation_condition='range_ref_version != "2"'),
        F(A + "core/range_resolver.py", "resolve_range_ref", "resolve_range_ref", 193,
          CONTRACTS + "range-ref.v2.schema.json", "auto-selected", "none",
          "optional_module_import", "raises_runtime_error", "required", "raises_runtime_error",
          "same_module_constant", "jsonschema.validate", 17, 44,
          "range_ref instance validated", "module constant _RANGE_REF_V2_SCHEMA_PATH via _load_schema",
          activation_condition='range_ref_version == "2"'),
        F(A + "core/relation_cards.py", "_validate_source_graph", "_validate_source_graph", 137,
          CONTRACTS + "architecture.graph.v1.schema.json", "draft7", "none",
          "dynamic_runtime_import", "raises_domain_error", "required", "raises_runtime_error",
          "same_module_loader", "Draft7Validator.iter_errors", 69, 100,
          "source graph validated before projection",
          "_load_source_schema() module loader (_SOURCE_SCHEMA_PATH)",
          meta_guard_present=True),
        F(A + "validate_merge_meta.py", "validate_report_meta", "validate_report_meta", 95,
          CONTRACTS + "repolens-report.schema.json", "draft2020-12", "none",
          "required_at_module_import", "module_import_failure", "required", "raises_runtime_error",
          "same_symbol_literal", "Draft202012Validator.iter_errors", 87, 91,
          "merge-meta block validated", "literal report schema, subschema #/properties/merge",
          schema_fragment="#/properties/merge"),
        F(A + "validate_merge_meta.py", "validate_report_meta", "validate_report_meta", 114,
          CONTRACTS + "repolens-delta.schema.json", "draft2020-12", "none",
          "required_at_module_import", "module_import_failure", "optional", "warn_and_continue",
          "same_symbol_literal", "Draft202012Validator.iter_errors", 108, 112,
          "optional delta block validated", "literal delta schema, full schema"),
        # --- delegated: validate_relation_card -> _schema_check (engine line 159) ---
        F(A + "core/relation_card_validate.py", "validate_relation_card", "_schema_check", 226,
          CONTRACTS + "relation-card.v1.schema.json", "draft7", "none",
          "dynamic_runtime_import", "returns_failed_check_skipped_unavailable",
          "required", "returns_blocked",
          "same_module_loader", "Draft7Validator.iter_errors", 47, 110,
          "relation card passed in, delegated to _schema_check (iter_errors line 159)",
          "_load_default_card_schema() module loader (_CARD_SCHEMA_PATH)",
          engine_invocation="delegated", meta_guard_present=True),
        F(A + "core/relation_card_validate.py", "validate_relation_card", "_schema_check", 235,
          CONTRACTS + "architecture.graph.v1.schema.json", "draft7", "none",
          "dynamic_runtime_import", "returns_failed_check_skipped_unavailable",
          "required", "returns_blocked",
          "same_module_loader", "Draft7Validator.iter_errors", 50, 114,
          "source graph passed in, delegated to _schema_check (iter_errors line 159)",
          "_load_default_source_schema() module loader (_SOURCE_SCHEMA_PATH)",
          engine_invocation="delegated", meta_guard_present=True),
    ]
    return flows


def build_external_flows() -> list[dict]:
    A = "merger/lenskit/"
    return [
        F(A + "adapters/sources.py", "refresh", "_validate_snapshot", 178,
          "metarepo/contracts/fleet/fleet.snapshot.schema.json", "auto-selected", "none",
          "optional_module_import", "silent_skip", "external_optional", "silent_skip",
          "runtime_external_root", "jsonschema.validate", 200, 177,
          "fleet snapshot validated against external metarepo schema",
          "schema_path = metarepo_path/contracts/fleet/fleet.snapshot.schema.json "
          "(root from runtime hub_path; not in base inventory)",
          target_scope="external_static_relative"),
    ]


def build_meta_flows() -> list[dict]:
    A = "merger/lenskit/"
    # check_schema() engine callsites and the schema flows they guard.
    return [
        {"source_path": A + "core/lens_card_validate.py",
         "engine_owner_symbol": "validate_lens_card", "engine_call_line": 134,
         "schema_path": CONTRACTS + "lens-card.v1.schema.json",
         "followed_by_instance_validation": True},
        {"source_path": A + "core/pr_delta_card_validate.py",
         "engine_owner_symbol": "validate_pr_delta_card", "engine_call_line": 133,
         "schema_path": CONTRACTS + "pr-delta-card.v1.schema.json",
         "followed_by_instance_validation": True},
        {"source_path": A + "core/pr_delta_cards.py",
         "engine_owner_symbol": "_validate_source_delta", "engine_call_line": 99,
         "schema_path": CONTRACTS + "pr-schau-delta.v1.schema.json",
         "followed_by_instance_validation": True},
        {"source_path": A + "core/relation_cards.py",
         "engine_owner_symbol": "_validate_source_graph", "engine_call_line": 135,
         "schema_path": CONTRACTS + "architecture.graph.v1.schema.json",
         "followed_by_instance_validation": True},
        {"source_path": A + "core/relation_card_validate.py",
         "engine_owner_symbol": "_schema_check", "engine_call_line": 157,
         "schema_path": CONTRACTS + "relation-card.v1.schema.json",
         "followed_by_instance_validation": True},
        {"source_path": A + "core/relation_card_validate.py",
         "engine_owner_symbol": "_schema_check", "engine_call_line": 157,
         "schema_path": CONTRACTS + "architecture.graph.v1.schema.json",
         "followed_by_instance_validation": True},
    ]


# Production files that textually reference jsonschema but perform NO instance
# validation against a *.schema.json (explained candidate-sweep difference).
NON_VALIDATOR_JSONSCHEMA_FILES = {
    "merger/lenskit/core/dependency_diagnostics.py":
        "dependency status reporter (jsonschema_dependency); no validate call",
    "merger/lenskit/core/output_health.py":
        "imports jsonschema_dependency only; no validate call",
    "merger/lenskit/core/bundle_surface_validate.py":
        "own structural validator; 'jsonschema' only in a ValidationMode Literal",
    "merger/lenskit/tests/conftest.py":
        "no_jsonschema fixture monkeypatches jsonschema absence; no validate call "
        "(conftest is not a test_* module under the facet API)",
    "scripts/docmeta/check_planning_registration.py":
        "comment defers schema validation to tests; no validate call",
}


# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo = args.repo
    base_sha = args.base_sha
    if base_sha != EXPECTED_BASE_SHA:
        print(f"STOP: base-sha {base_sha} != expected {EXPECTED_BASE_SHA}", file=sys.stderr)
        return 2

    inventory = list_tree(repo, base_sha)
    inv_set = set(inventory)
    inv_sha = inventory_sha256(inventory)
    if inv_sha != EXPECTED_INVENTORY_SHA256:
        print(f"STOP: inventory sha {inv_sha} != expected", file=sys.stderr)
        return 2

    infer_facets = load_infer_facets(repo, base_sha)

    schema_files = sorted(p for p in inventory if p.endswith(".schema.json"))
    py_files = [p for p in inventory if p.endswith(".py")]

    # --- candidate discovery over the base snapshot ---
    parse_failures: list[dict] = []
    files_with_instance_call: set[str] = set()
    files_with_jsonschema_token: set[str] = set()
    files_with_meta_call: set[str] = set()
    for path in py_files:
        src = show(repo, base_sha, path)
        if "jsonschema" in src:
            files_with_jsonschema_token.add(path)
        try:
            instance_calls, meta_calls = scan(src, path)
        except SyntaxError as exc:
            parse_failures.append({
                "path": path,
                "lineno": exc.lineno,
                "message": exc.msg,
                "is_test_facet": has_test_facet(infer_facets, path),
            })
            continue
        if instance_calls:
            files_with_instance_call.add(path)
        if meta_calls:
            files_with_meta_call.add(path)

    parse_failures.sort(key=lambda d: d["path"])
    parse_failure_paths = {d["path"] for d in parse_failures}

    def is_test(path: str) -> bool:
        return has_test_facet(infer_facets, path)

    # candidate validation files: instance call + jsonschema provenance
    candidate_validation_files = files_with_instance_call & files_with_jsonschema_token
    prod_candidate_files = {p for p in candidate_validation_files if not is_test(p)}
    test_candidate_files = {p for p in candidate_validation_files if is_test(p)}

    # text sweep (provenance): production files mentioning jsonschema
    text_prod_files = {p for p in files_with_jsonschema_token if not is_test(p)}

    accepted = build_accepted_flows()
    external = build_external_flows()
    meta_flows = build_meta_flows()

    accepted.sort(key=lambda f: f["relation_flow_id"])
    external.sort(key=lambda f: f["relation_flow_id"])

    review_prod_files = (
        {f["source_path"] for f in accepted} | {f["source_path"] for f in external}
    )

    # --- completeness gate: AST-discovered prod validation files == reviewed set
    if prod_candidate_files != review_prod_files:
        only_ast = sorted(prod_candidate_files - review_prod_files)
        only_review = sorted(review_prod_files - prod_candidate_files)
        print("STOP: candidate/review production-file mismatch", file=sys.stderr)
        print(f"  only_in_ast={only_ast}", file=sys.stderr)
        print(f"  only_in_review={only_review}", file=sys.stderr)
        return 2

    # --- text vs ast difference must be exactly the explained non-validators
    text_minus_ast = text_prod_files - prod_candidate_files
    explained = set(NON_VALIDATOR_JSONSCHEMA_FILES)
    if text_minus_ast != explained:
        print("STOP: unexplained text-only jsonschema files", file=sys.stderr)
        print(f"  unexplained={sorted(text_minus_ast - explained)}", file=sys.stderr)
        print(f"  missing_expected={sorted(explained - text_minus_ast)}", file=sys.stderr)
        return 2

    # --- counts derived from the normalized table (never hard-coded) ---
    callsite_flow_count = len(accepted)
    symbol_schema_targets = {
        (f["source_path"], f["relation_owner_symbol"], f["schema_path"]) for f in accepted
    }
    module_schema_targets = {(f["source_path"], f["schema_path"]) for f in accepted}
    accepted_modules = {f["source_path"] for f in accepted}
    accepted_schema_targets = {f["schema_path"] for f in accepted}

    meta_engine_callsites = sorted(
        {(m["source_path"], m["engine_call_line"]) for m in meta_flows}
    )
    schema_with_relation = sorted(accepted_schema_targets & inv_set)
    schema_without_relation = sorted(set(schema_files) - set(schema_with_relation))

    # --- assertions (section 24) ---
    assert accepted == sorted(accepted, key=lambda f: f["relation_flow_id"])
    assert len({f["relation_flow_id"] for f in accepted}) == len(accepted)
    assert all(f["target_scope"] == "in_repo" for f in accepted)
    assert all(f["schema_path"] in inv_set for f in accepted)
    assert all(
        f["schema_fragment"] is None or f["schema_fragment"].startswith("#/")
        for f in accepted
    )
    assert all(f["engine_invocation"] in VALID_ENGINE_INVOCATION for f in accepted)
    assert all(f["schema_binding_origin"] in VALID_BINDING for f in accepted)
    assert all(f["dependency_requirement"] in VALID_DEP_REQ for f in accepted)
    assert all(f["missing_dependency_outcome"] in VALID_DEP_OUT for f in accepted)
    assert all(f["schema_requirement"] in VALID_SCHEMA_REQ for f in accepted)
    assert all(f["missing_schema_outcome"] in VALID_SCHEMA_OUT for f in accepted)
    assert len(accepted_modules) == len({f["source_path"] for f in accepted})
    assert len(accepted_schema_targets) == len({f["schema_path"] for f in accepted})
    assert len(schema_with_relation) + len(schema_without_relation) == 54
    assert len(schema_files) == 54
    assert all(f["target_scope"] in VALID_TARGET_SCOPES for f in external)
    assert all(f["target_scope"] != "in_repo" for f in external)
    assert len(meta_engine_callsites) == 5
    assert len(meta_flows) == 6
    # test classification via the controlled facet API
    assert all(is_test(p) for p in test_candidate_files)
    assert all(not is_test(p) for p in review_prod_files)
    assert candidate_validation_files == (review_prod_files | test_candidate_files)
    # axis sums must each total the accepted relation count
    for axis in ("engine_invocation", "schema_binding_origin", "dependency_requirement",
                 "missing_dependency_outcome", "schema_requirement", "missing_schema_outcome",
                 "validator_draft", "format_checker_mode"):
        total = sum(_axis_counts(accepted, axis).values())
        assert total == len(accepted), f"axis {axis} does not sum to {len(accepted)}"
    # parse failures: exactly the one known broken fixture
    assert parse_failure_paths == {
        "merger/lenskit/tests/fixtures/entrypoints_test_project/invalid.py"
    }, f"unexpected parse failures: {sorted(parse_failure_paths)}"

    report = {
        "base_sha": base_sha,
        "inventory_sha256": inv_sha,
        "inventory_path_count": len(inventory),
        "relation_identity": {"fields": list(IDENTITY_FIELDS)},
        "relation_counts": {
            "callsite_flows": callsite_flow_count,
            "unique_symbol_schema_targets": len(symbol_schema_targets),
            "unique_module_schema_targets": len(module_schema_targets),
            "accepted_modules": len(accepted_modules),
            "accepted_schema_targets": len(accepted_schema_targets),
            "external_or_not_accepted_flows": len(external),
        },
        "axis_counts": {
            axis: _axis_counts(accepted, axis)
            for axis in (
                "engine_invocation", "schema_binding_origin", "resolved_engine",
                "validator_draft", "format_checker_mode", "dependency_requirement",
                "missing_dependency_outcome", "schema_requirement", "missing_schema_outcome",
                "target_scope", "activation_condition",
            )
        },
        "meta_validation": {
            "engine_callsites": [
                {"source_path": p, "engine_call_line": ln}
                for (p, ln) in meta_engine_callsites
            ],
            "schema_flows": sorted(
                meta_flows, key=lambda m: (m["source_path"], m["engine_call_line"], m["schema_path"])
            ),
            "engine_callsite_count": len(meta_engine_callsites),
            "schema_flow_count": len(meta_flows),
        },
        "schema_coverage": {
            "total_schema_files": len(schema_files),
            "with_accepted_production_relation": len(schema_with_relation),
            "without_accepted_production_relation": len(schema_without_relation),
            "schema_files_with_relation": schema_with_relation,
            "schema_files_without_relation": schema_without_relation,
        },
        "test_inventory": {
            "classification": "merger.lenskit.core.lens_facets.infer_facets (facet == 'test')",
            "test_files_with_validation_api": sorted(test_candidate_files),
            "test_files_with_validation_api_count": len(test_candidate_files),
        },
        "parse_failures": parse_failures,
        "candidate_discovery": {
            "ast_production_validation_files": sorted(prod_candidate_files),
            "text_production_jsonschema_files": sorted(text_prod_files),
            "text_only_non_validator_files": {
                k: NON_VALIDATOR_JSONSCHEMA_FILES[k] for k in sorted(NON_VALIDATOR_JSONSCHEMA_FILES)
            },
            "ast_equals_review": True,
        },
        "accepted_relation_flows": accepted,
        "excluded_external_flows": external,
        "module_counts": {
            "accepted_in_repo_modules": sorted(accepted_modules),
            "external_modules": sorted({f["source_path"] for f in external}),
        },
        "limitations": [
            "Accepted relation table is manually reviewed; AST/text sweeps gate the "
            "candidate surface only, not the individual schema flows.",
            "Only validation against in-repo *.schema.json is accepted; inline and "
            "non-repo schemas are reported as external / not accepted.",
            "load_only and path_reference_only callsites are not inventoried.",
            "Dynamic/config-loaded schemas and non-jsonschema validators are out of scope.",
            "Runtime execution is not proven; only static code chains in the snapshot.",
        ],
    }

    blob = json.dumps(report, indent=2, sort_keys=False, ensure_ascii=True) + "\n"
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(blob)
    print(f"OK wrote {args.output} ({len(accepted)} accepted flows, "
          f"{len(external)} external, {len(meta_flows)} meta-schema-flows)")
    return 0


def _axis_counts(flows: list[dict], axis: str) -> dict:
    counts: dict = {}
    for f in flows:
        counts[f[axis]] = counts.get(f[axis], 0) + 1
    return {k: counts[k] for k in sorted(counts)}


if __name__ == "__main__":
    raise SystemExit(main())
