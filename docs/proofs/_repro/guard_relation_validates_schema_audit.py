#!/usr/bin/env python3
"""Reproduce the diagnosis-only ``validates_schema`` audit for one fixed Git base.

AST equality verifies reviewed engine callsites and delegated relation calls.
Schema bindings and qualitative outcome labels remain manually reviewed.
"""
from __future__ import annotations
import argparse, ast, hashlib, json, subprocess, types

BASE="05bbd0d608afa8faf581887a455d4dcf6fa15ae9"
INV_SHA="19ccdd599e32d683b97d71a86b05594b825440bda1b900d32a756517f637b50a"
FIELDS=("source_path","relation_owner_symbol","relation_call_line","engine_owner_symbol",
"engine_call_line","schema_path","schema_fragment","activation_condition","target_scope")
APIS={"validate","iter_errors"}
ACCEPTED=json.loads('["merger/lenskit/architecture/graph_index.py|load_graph_index|39|load_graph_index|39|merger/lenskit/contracts/architecture.graph_index.v1.schema.json|null|unconditional|in_repo","merger/lenskit/cli/policy_loader.py|load_and_validate_embedding_policy|45|load_and_validate_embedding_policy|45|merger/lenskit/contracts/embedding-policy.v1.schema.json|null|unconditional|in_repo","merger/lenskit/cli/pr_schau_verify.py|verify_basic|80|verify_basic|80|merger/lenskit/contracts/pr-schau.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/agent_export_gate.py|_validate_post_health_schema|262|_validate_post_health_schema|262|merger/lenskit/contracts/post-emit-health.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/doc_freshness.py|validate_registry|668|validate_registry|668|merger/lenskit/contracts/doc-freshness-registry.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/federation.py|init_federation|59|init_federation|59|merger/lenskit/contracts/federation-index.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/federation.py|validate_federation|87|validate_federation|87|merger/lenskit/contracts/federation-index.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/federation.py|add_bundle|156|add_bundle|156|merger/lenskit/contracts/federation-index.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/federation.py|add_bundle|187|add_bundle|187|merger/lenskit/contracts/federation-index.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/forensic_preflight.py|_validate_claim_map_schema|119|_validate_claim_map_schema|119|merger/lenskit/contracts/claim-evidence-map.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/lens_card_validate.py|validate_lens_card|136|validate_lens_card|136|merger/lenskit/contracts/lens-card.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/parity_state.py|_validate_citation_map|349|_validate_citation_map|349|merger/lenskit/contracts/citation-map.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/post_emit_health.py|_validate_claim_evidence_map_schema|331|_validate_claim_evidence_map_schema|331|merger/lenskit/contracts/claim-evidence-map.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/post_emit_health.py|_validate_manifest_schema|404|_validate_manifest_schema|404|merger/lenskit/contracts/bundle-manifest.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/pr_delta_card_validate.py|validate_pr_delta_card|135|validate_pr_delta_card|135|merger/lenskit/contracts/pr-delta-card.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/pr_delta_cards.py|_validate_source_delta|105|_validate_source_delta|105|merger/lenskit/contracts/pr-schau-delta.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/pr_schau_bundle.py|load_pr_schau_bundle|130|load_pr_schau_bundle|130|merger/lenskit/contracts/pr-schau.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/range_resolver.py|resolve_range_ref|193|resolve_range_ref|193|merger/lenskit/contracts/range-ref.v1.schema.json|null|range_ref_version != \\"2\\"|in_repo","merger/lenskit/core/range_resolver.py|resolve_range_ref|193|resolve_range_ref|193|merger/lenskit/contracts/range-ref.v2.schema.json|null|range_ref_version == \\"2\\"|in_repo","merger/lenskit/core/relation_cards.py|_validate_source_graph|137|_validate_source_graph|137|merger/lenskit/contracts/architecture.graph.v1.schema.json|null|unconditional|in_repo","merger/lenskit/validate_merge_meta.py|validate_report_meta|95|validate_report_meta|95|merger/lenskit/contracts/repolens-report.schema.json|#/properties/merge|unconditional|in_repo","merger/lenskit/validate_merge_meta.py|validate_report_meta|114|validate_report_meta|114|merger/lenskit/contracts/repolens-delta.schema.json|null|unconditional|in_repo","merger/lenskit/core/relation_card_validate.py|validate_relation_card|226|_schema_check|159|merger/lenskit/contracts/relation-card.v1.schema.json|null|unconditional|in_repo","merger/lenskit/core/relation_card_validate.py|validate_relation_card|235|_schema_check|159|merger/lenskit/contracts/architecture.graph.v1.schema.json|null|unconditional|in_repo"]')
EXTERNAL=json.loads('["merger/lenskit/adapters/sources.py|refresh|299|_validate_snapshot|178|metarepo/contracts/fleet/fleet.snapshot.schema.json|null|unconditional|external_static_relative"]')
AXES=json.loads('{"activation_condition":{"range_ref_version != \\"2\\"":1,"range_ref_version == \\"2\\"":1,"unconditional":22},"dependency_requirement":{"dynamic_runtime_import":7,"optional_module_import":15,"required_at_module_import":2},"engine_invocation":{"delegated":2,"direct":22},"format_checker_mode":{"FormatChecker":1,"custom_date_time_checker":1,"none":22},"missing_dependency_outcome":{"module_import_failure":2,"raises_domain_error":4,"raises_runtime_error":6,"returns_blocked":1,"returns_environment_error":2,"returns_failed_check_skipped_unavailable":4,"silent_skip":2,"structural_fallback":1,"warn_and_continue":2},"missing_schema_outcome":{"raises_domain_error":2,"raises_runtime_error":11,"returns_blocked":6,"returns_environment_error":2,"silent_skip":2,"warn_and_continue":1},"resolved_engine":{"Draft202012Validator.iter_errors":3,"Draft7Validator.iter_errors":6,"jsonschema.validate":15},"schema_binding_origin":{"caller_parameter":2,"same_module_constant":2,"same_module_loader":11,"same_symbol_literal":9},"schema_requirement":{"optional":3,"required":21},"target_scope":{"in_repo":24},"validator_draft":{"auto-selected":15,"draft2020-12":3,"draft7":6}}')
META=json.loads('[["merger/lenskit/core/lens_card_validate.py","validate_lens_card",134,"merger/lenskit/contracts/lens-card.v1.schema.json"],["merger/lenskit/core/pr_delta_card_validate.py","validate_pr_delta_card",133,"merger/lenskit/contracts/pr-delta-card.v1.schema.json"],["merger/lenskit/core/pr_delta_cards.py","_validate_source_delta",99,"merger/lenskit/contracts/pr-schau-delta.v1.schema.json"],["merger/lenskit/core/relation_cards.py","_validate_source_graph",135,"merger/lenskit/contracts/architecture.graph.v1.schema.json"],["merger/lenskit/core/relation_card_validate.py","_schema_check",157,"merger/lenskit/contracts/relation-card.v1.schema.json"],["merger/lenskit/core/relation_card_validate.py","_schema_check",157,"merger/lenskit/contracts/architecture.graph.v1.schema.json"]]')
TEXT_ONLY=json.loads('{"merger/lenskit/core/bundle_surface_validate.py":"structural validator; jsonschema appears only in a validation-mode literal","merger/lenskit/core/dependency_diagnostics.py":"dependency status reporter only; no instance-validation API","merger/lenskit/core/output_health.py":"imports dependency diagnostics only; no instance-validation API","merger/lenskit/tests/conftest.py":"dependency-degradation fixture; no instance-validation API and no test facet","scripts/docmeta/check_planning_registration.py":"comment references schema validation tests; no instance-validation API"}')

def git(repo,*args):
    return subprocess.run(["git","-C",repo,*args],check=True,capture_output=True,text=True).stdout

def show(repo,base,path):
    return git(repo,"show",f"{base}:{path}")

def tree(repo,base):
    return sorted(set(git(repo,"ls-tree","-r","--name-only",base).splitlines()))

def facets(repo,base):
    m=types.ModuleType("lens_facets_base")
    exec(compile(show(repo,base,"merger/lenskit/core/lens_facets.py"),
                 "lens_facets.py@base","exec"),m.__dict__)  # noqa: S102
    return m.infer_facets

def is_test(infer,path):
    return any(x.get("facet")=="test" for x in infer(path))

def callee(node):
    return node.id if isinstance(node,ast.Name) else node.attr if isinstance(node,ast.Attribute) else None

def scan(src,path):
    spans={}; calls=[]; engines=[]; metas=[]; owners=[]
    class V(ast.NodeVisitor):
        def visit_FunctionDef(self,n):  # noqa: N802
            owners.append(n.name)
            spans.setdefault(n.name,[]).append((n.lineno,getattr(n,"end_lineno",n.lineno)))
            self.generic_visit(n); owners.pop()
        visit_AsyncFunctionDef=visit_FunctionDef
        def visit_Call(self,n):  # noqa: N802
            item=(owners[-1] if owners else "<module>",n.lineno,callee(n.func))
            calls.append(item)
            if isinstance(n.func,ast.Attribute) and n.func.attr in APIS: engines.append(item)
            if isinstance(n.func,ast.Attribute) and n.func.attr=="check_schema": metas.append(item)
            self.generic_visit(n)
    V().visit(ast.parse(src,filename=path))
    return spans,calls,engines,metas

def parse(rel):
    vals=rel.split("|"); assert len(vals)==len(FIELDS)
    d=dict(zip(FIELDS,vals,strict=True))
    d["relation_call_line"]=int(d["relation_call_line"])
    d["engine_call_line"]=int(d["engine_call_line"])
    d["schema_fragment"]=None if d["schema_fragment"]=="null" else d["schema_fragment"]
    d["relation_flow_id"]=rel
    return d

def digest(items):
    return hashlib.sha256(("\n".join("|".join(str(x) for x in row)
                                      for row in sorted(items))+"\n").encode()).hexdigest()

def contains(a,owner,line):
    return any(lo<=line<=hi for lo,hi in a[0].get(owner,[]))

def verify(analyses,flows):
    for f in flows:
        a=analyses[f["source_path"]]
        engine=(f["engine_owner_symbol"],f["engine_call_line"])
        assert engine in {(o,n) for o,n,_ in a[2]}
        assert contains(a,*engine)
        assert contains(a,f["relation_owner_symbol"],f["relation_call_line"])
        direct=(f["relation_owner_symbol"]==f["engine_owner_symbol"] and
                f["relation_call_line"]==f["engine_call_line"])
        if not direct:
            assert (f["relation_owner_symbol"],f["relation_call_line"],
                    f["engine_owner_symbol"]) in set(a[1])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo",required=True); p.add_argument("--base-sha",required=True)
    p.add_argument("--output",required=True); a=p.parse_args()
    assert a.base_sha==BASE
    inventory=tree(a.repo,a.base_sha)
    inventory_sha=hashlib.sha256(("\n".join(inventory)+"\n").encode()).hexdigest()
    assert inventory_sha==INV_SHA
    infer=facets(a.repo,a.base_sha); analyses={}; failures=[]; token_files=set()
    for path in sorted(x for x in inventory if x.endswith(".py")):
        src=show(a.repo,a.base_sha,path)
        if "jsonschema" in src: token_files.add(path)
        try: analyses[path]=scan(src,path)
        except SyntaxError as e:
            failures.append({"path":path,"lineno":e.lineno,"message":e.msg,
                             "is_test_facet":is_test(infer,path)})
    failures.sort(key=lambda x:x["path"])
    assert {x["path"] for x in failures}=={
        "merger/lenskit/tests/fixtures/entrypoints_test_project/invalid.py"}

    accepted=[parse(x) for x in ACCEPTED]; external=[parse(x) for x in EXTERNAL]
    reviewed=accepted+external; verify(analyses,reviewed)
    found=set(); test_files=set()
    for path in sorted(token_files):
        if path not in analyses: continue
        for owner,line,_ in analyses[path][2]:
            if is_test(infer,path): test_files.add(path)
            else: found.add((path,owner,line))
    expected={(f["source_path"],f["engine_owner_symbol"],f["engine_call_line"])
              for f in reviewed}
    assert found==expected

    found_meta={(path,o,n) for path in token_files if path in analyses
                and not is_test(infer,path) for o,n,_ in analyses[path][3]}
    expected_meta={(path,o,n) for path,o,n,_ in META}
    assert found_meta==expected_meta
    non_test_tokens={x for x in token_files if not is_test(infer,x)}
    engine_files={x for x,_,_ in found}
    assert non_test_tokens-engine_files==set(TEXT_ONLY)
    assert len(test_files)==44

    schemas=sorted(x for x in inventory if x.endswith(".schema.json"))
    targets={f["schema_path"] for f in accepted}
    assert targets<=set(inventory) and len(schemas)==54 and len(targets)==18
    assert all(f["target_scope"]=="in_repo" for f in accepted)
    assert all(f["target_scope"]!="in_repo" for f in external)
    assert len(set(ACCEPTED))==24
    assert all(sum(v.values())==24 for v in AXES.values())
    assert AXES["schema_requirement"]=={"optional":3,"required":21}
    assert AXES["activation_condition"]=={
        'range_ref_version != "2"':1,'range_ref_version == "2"':1,"unconditional":22}

    symbols={(f["source_path"],f["relation_owner_symbol"],f["schema_path"]) for f in accepted}
    modules={(f["source_path"],f["schema_path"]) for f in accepted}
    direct=sum(f["relation_owner_symbol"]==f["engine_owner_symbol"] and
               f["relation_call_line"]==f["engine_call_line"] for f in accepted)
    assert (direct,24-direct)==(22,2)
    meta_sites={(path,n) for path,_,n,_ in META}
    report={
      "base_sha":BASE,"inventory_sha256":inventory_sha,"inventory_path_count":len(inventory),
      "relation_identity":{"fields":list(FIELDS)},"relation_ids":sorted(ACCEPTED),
      "relation_counts":{"callsite_flows":24,"unique_symbol_schema_targets":len(symbols),
       "unique_module_schema_targets":len(modules),
       "accepted_modules":len({f["source_path"] for f in accepted}),
       "accepted_schema_targets":len(targets),"external_or_not_accepted_flows":1,
       "unique_instance_engine_callsites_including_external":len(expected)},
      "axis_counts":AXES,
      "callsite_gate":{"count":len(expected),"ast_sha256":digest(found),
       "reviewed_sha256":digest(expected),"equal":True},
      "meta_validation":{"engine_callsite_count":len(meta_sites),"schema_flow_count":len(META),
       "ast_sha256":digest(found_meta),"reviewed_sha256":digest(expected_meta),"equal":True},
      "schema_coverage":{"total_schema_files":54,"with_accepted_in_repo_relation":18,
       "without_accepted_in_repo_relation":36,
       "with_relation_sha256":digest({(x,) for x in targets})},
      "test_inventory":{"classification":"lens_facets.infer_facets (facet == 'test')",
       "test_files_with_validation_api_count":44,
       "test_files_sha256":digest({(x,) for x in test_files})},
      "parse_failures":failures,
      "candidate_discovery":{
       "classification_boundary":"non_test_facet does not establish production status",
       "ast_non_test_facet_validation_file_count":len(engine_files),
       "text_non_test_facet_jsonschema_file_count":len(non_test_tokens),
       "text_only_non_validator_files":{x:TEXT_ONLY[x] for x in sorted(TEXT_ONLY)}},
      "external_relation_ids":sorted(EXTERNAL),
      "limitations":[
       "Schema bindings and qualitative outcome labels are manually reviewed.",
       "AST equality proves engine-callsite coverage, not schema-binding correctness.",
       "Only in-repo *.schema.json targets are accepted.",
       "Inline, dynamic, and non-jsonschema validators are outside this audit.",
       "load_only and path_reference_only callsites are not inventoried.",
       "Static code chains do not prove runtime execution or consumer need."]}
    with open(a.output,"w",encoding="utf-8") as f:
        f.write(json.dumps(report,indent=2,ensure_ascii=True)+"\n")
    print(f"OK wrote {a.output} (24 flows, {len(expected)} engine callsites)")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
