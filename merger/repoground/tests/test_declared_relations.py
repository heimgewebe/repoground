"""Cross-language lexical edge fixtures over the existing RepoGround file graph."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from merger.repoground.architecture.declared_relations import extract_declared_relations
from merger.repoground.architecture.import_graph import generate_import_graph_document


class TestDeclaredRelations(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, relative: str, value: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def projection(self, **bounds):
        graph = generate_import_graph_document(self.root, "run-1", "a" * 64)
        return extract_declared_relations(self.root, graph, **bounds)

    def test_typescript_import_reexport_multiline_and_negative_lexical_cases(self):
        self.write("web/util.ts", "export const value = 1;\n")
        self.write("web/side.js", "side();\n")
        self.write("web/main.tsx", (
            "import {\n"
            "  value\n"
            "} from './util';\n"
            "export { value } from './util';\n"
            "import './side';\n"
            "// import './missing';\n"
            "/* export * from './missing'; */\n"
            "const a = \x60\n"
            "import './missing';\n"
            "\x60;\n"
            "import unknown from './not-found';\n"
            "const b = import('./dynamic');\n"
        ))
        edges, coverage = self.projection()
        imports = [e for e in edges if e["src"] == "file:web/main.tsx"]
        resolved = [e for e in imports if e["resolution_status"] == "resolved"]
        self.assertEqual(3, len(resolved))
        self.assertEqual({"file:web/side.js", "file:web/util.ts"}, {e["dst"] for e in resolved})
        self.assertEqual("S1", resolved[0]["evidence_level"])
        self.assertTrue(any(e["relation"] == "references" for e in resolved))
        self.assertTrue(any(e["source"]["start_line"] == 1 and e["source"]["end_line"] == 3
                            for e in resolved))
        unknown = [e for e in imports if e["resolution_status"] == "unresolved"]
        self.assertEqual(1, len(unknown))
        self.assertEqual("S0", unknown[0]["evidence_level"])
        self.assertFalse(any("missing" in e["dst"] or "dynamic" in e["dst"] for e in imports))
        self.assertEqual(3, coverage["edge_counts"]["imports"])

    def test_unqualified_js_import_collision_must_stay_s0(self):
        self.write("js/a.ts", "export const x = 1;\n")
        self.write("js/a.js", "export const x = 2;\n")
        self.write("js/consumer.ts", "import {x} from './a';\n")
        edges, _ = self.projection()
        call = next(e for e in edges if e["src"] == "file:js/consumer.ts")
        self.assertEqual("ambiguous", call["resolution_status"])
        self.assertEqual("S0", call["evidence_level"])
        self.assertEqual(["file:js/a.js", "file:js/a.ts"], call["candidate_target_ids"])

    def test_javascript_named_function_definitions_and_s0_callsites(self):
        self.write("web/logic.ts", (
            "export function compute(value: number) {\n"
            "  return value;\n"
            "}\n"
            "compute(1);\n"
            "const ignored = 'compute(3)';\n"
            "// compute(9)\n"
            "object.compute(4);\n"
        ))
        edges, coverage = self.projection()
        definitions = [edge for edge in edges if edge["relation"] == "defines"]
        self.assertEqual(1, len(definitions))
        definition = definitions[0]
        self.assertEqual("js:web/logic.ts:function:compute:L1", definition["dst"])
        self.assertEqual(("S1", "resolved"), (
            definition["evidence_level"], definition["resolution_status"],
        ))
        calls = [edge for edge in edges if edge["relation"] == "calls"]
        self.assertEqual(1, len(calls), calls)
        self.assertEqual("S0", calls[0]["evidence_level"])
        self.assertEqual("candidate", calls[0]["resolution_status"])
        self.assertEqual([definition["dst"]], calls[0]["candidate_target_ids"])
        self.assertEqual("file:web/logic.ts#L4-L4", calls[0]["source"]["range_ref"])
        self.assertEqual(1, coverage["edge_counts"]["defines"])


    def test_json_schema_instance_data_cannot_become_proven_contract_ref(self):
        self.write("schemas/base.json", '{"type":"object"}\n')
        self.write("schemas/default.json", (
            '{"type":"object","default":{"$ref":"./base.json"}}\n'
        ))
        self.write("schemas/ambiguous.json", (
            '{"allOf":[{"$ref":"./base.json"}],'
            '"default":{"$ref":"./base.json"}}\n'
        ))
        self.write("schemas/legitimate.json", (
            '{"properties":{"item":{"$ref":"./base.json"}}}\n'
        ))
        edges, _ = self.projection()
        for name in ("default", "ambiguous"):
            own = [
                e for e in edges
                if e["src"] == f"file:schemas/{name}.json"
            ]
            self.assertFalse(
                any(e["evidence_level"] == "S1" for e in own),
                own,
            )
        legitimate = [
            e for e in edges
            if e["src"] == "file:schemas/legitimate.json"
        ]
        self.assertEqual(1, len(legitimate), legitimate)
        self.assertEqual("file:schemas/base.json", legitimate[0]["dst"])
        self.assertEqual("S1", legitimate[0]["evidence_level"])


    def test_percent_encoded_schema_path_remains_unproven(self):
        self.write("schemas/base schema.json", '{"type":"object"}\n')
        self.write("schemas/base%20schema.json", '{"type":"object"}\n')
        self.write("schemas/encoded.json", '{"$ref":"base%20schema.json"}\n')
        edges, _ = self.projection()
        own = [e for e in edges if e["src"] == "file:schemas/encoded.json"]
        self.assertEqual(1, len(own), own)
        self.assertEqual("S0", own[0]["evidence_level"])
        self.assertEqual("unresolved", own[0]["resolution_status"])
        self.assertNotEqual("file:schemas/base%20schema.json", own[0]["dst"])

    def test_jsx_child_text_cannot_become_s1_function_or_import(self):
        self.write("web/util.js", "export const value = 1;\n")
        for suffix in ("jsx", "tsx"):
            relative = f"web/page.{suffix}"
            self.write(relative, (
                'import "./util";\n'
                "const ui = <pre>\n"
                "function fake() {}\n"
                'import "./util";\n'
                "</pre>;\n"
                "export function real() {}\n"
            ))
        edges, _ = self.projection()
        for suffix in ("jsx", "tsx"):
            own = [e for e in edges if e["src"] == f"file:web/page.{suffix}"]
            definitions = [e for e in own if e["relation"] == "defines"]
            imports = [e for e in own if e["relation"] == "imports"]
            self.assertEqual(
                [f"js:web/page.{suffix}:function:real:L6"],
                [e["dst"] for e in definitions],
            )
            self.assertEqual(1, len(imports), imports)
            self.assertEqual("file:web/util.js", imports[0]["dst"])
            self.assertEqual("S1", imports[0]["evidence_level"])

    def test_nix_literals_are_linked_but_strings_and_comments_skipped(self):
        self.write("modules/gui.nix", "{ ... }: { }\n")
        self.write("flake.nix", (
            "{ ... }: {\n"
            "  imports = [\n"
            "    ./modules/gui.nix\n"
            "    ./modules/missing.nix\n"
            "  ];\n"
            "  value = import ./modules/gui.nix;\n"
            "  text = \"import ./modules/fake.nix\";\n"
            "  # import ./modules/fake.nix\n"
            "}\n"
        ))
        graph = generate_import_graph_document(self.root, "nix-run", "a" * 64)
        nodes = {n["node_id"]: n["language"] for n in graph["nodes"]}
        self.assertEqual("nix", nodes["file:flake.nix"])
        edges, _ = extract_declared_relations(self.root, graph)
        imported = [edge for edge in edges if edge["src"] == "file:flake.nix"]
        self.assertEqual(3, len(imported))
        self.assertEqual(2, sum(e["dst"] == "file:modules/gui.nix" for e in imported))
        self.assertEqual(1, sum(e["resolution_status"] == "unresolved" for e in imported))
        self.assertTrue(all("fake" not in e["dst"] for e in imported))

    def test_json_contract_ref_is_static_and_compose_service_is_candidate(self):
        self.write("schemas/base.json", '{"type": "object"}\n')
        self.write("schemas/consumer.json", '{\n "$ref": "./base.json#/$defs/Thing"\n}\n')
        self.write("compose.yaml", (
            "name: demo\n"
            "services:\n"
            "  api:\n"
            "    image: example:latest\n"
            "  worker:\n"
            "    image: example:latest\n"
            "networks:\n"
            "  default:\n"
        ))
        edges, _ = self.projection()
        schema_edges = [e for e in edges if e["origin_artifact"] == "json_schema_declared_ref"]
        self.assertEqual(1, len(schema_edges))
        self.assertEqual("file:schemas/base.json", schema_edges[0]["dst"])
        self.assertEqual("S1", schema_edges[0]["evidence_level"])
        self.assertEqual(2, schema_edges[0]["source"]["start_line"])
        compose = [e for e in edges if e["relation"] == "configures_service"]
        self.assertEqual(2, len(compose))
        self.assertTrue(all(e["evidence_level"] == "S0" for e in compose))
        self.assertEqual({"declared-service:compose.yaml:api", "declared-service:compose.yaml:worker"},
                         {e["dst"] for e in compose})

    def test_nix_import_does_not_promote_function_arguments_or_nested_attrs(self):
        for name in ("gui", "config", "hidden"):
            self.write(f"modules/{name}.nix", "{ ... }: {}\n")
        self.write("flake.nix", (
            "imports = [\n"
            "  ./modules/gui.nix\n"
            "  { path = ./modules/hidden.nix; }\n"
            "];\n"
            "value = import ./modules/config.nix { foo = ./modules/hidden.nix; };\n"
            "other.imports = [ ./modules/hidden.nix ];\n"
        ))
        edges, _ = self.projection()
        relations = [e for e in edges if e["src"] == "file:flake.nix"]
        self.assertEqual({"file:modules/gui.nix", "file:modules/config.nix"},
                         {e["dst"] for e in relations})
        self.assertTrue(all(e["evidence_level"] == "S1" for e in relations))

    def test_schema_bare_relative_filename_and_no_guessed_json_suffix(self):
        self.write("schemas/base.json", '{"type":"object"}\n')
        self.write("schemas/actual.json", '{"$ref":"base.json#/$defs/A"}\n')
        self.write("schemas/without_extension.json", '{"$ref":"./base"}\n')
        self.write("schemas/remote.json", '{"$ref":"https://example.com/base.json"}\n')
        edges, _ = self.projection()
        refs = {e["src"]: e for e in edges if e["relation"] == "declares_contract"}
        self.assertEqual(("file:schemas/base.json", "S1"),
                         (refs["file:schemas/actual.json"]["dst"],
                          refs["file:schemas/actual.json"]["evidence_level"]))
        self.assertEqual("S0", refs["file:schemas/without_extension.json"]["evidence_level"])
        self.assertNotEqual("file:schemas/base.json",
                            refs["file:schemas/without_extension.json"]["dst"])
        self.assertEqual("S0", refs["file:schemas/remote.json"]["evidence_level"])

    def test_escaped_multiline_js_string_does_not_define_or_import(self):
        self.write("web/util.ts", "export const value = 1;\n")
        self.write("web/main.ts", (
            "const text = \"header\\\n"
            "import './util';\\\n"
            "function fake() { }\\\n"
            "footer\";\n"
            "export function real() { return 1; }\n"
            "real();\n"
            "import './util';\n"
        ))
        edges, _ = self.projection()
        own = [edge for edge in edges if edge["src"] == "file:web/main.ts"]
        definitions = [e for e in own if e["relation"] == "defines"]
        imports = [e for e in own if e["relation"] == "imports"]
        calls = [e for e in own if e["relation"] == "calls"]
        self.assertEqual(["js:web/main.ts:function:real:L5"], [d["dst"] for d in definitions])
        self.assertEqual(1, len(imports), imports)
        self.assertEqual("file:web/util.ts", imports[0]["dst"])
        self.assertEqual(1, len(calls))
        self.assertEqual("S0", calls[0]["evidence_level"])

    def test_apostrophe_in_js_comment_cannot_swallow_true_declarations(self):
        self.write("web/util.ts", "export const value = 1;\n")
        self.write("web/comment.ts", (
            "// user's helper\n"
            "export function real() {}\n"
            "import './util';\n"
            "const url = 'https://example.com/api';\n"
            "real();\n"
        ))
        edges, _ = self.projection()
        edges = [item for item in edges if item["src"] == "file:web/comment.ts"]
        self.assertTrue(any(
            item["relation"] == "defines"
            and item["dst"] == "js:web/comment.ts:function:real:L2"
            for item in edges
        ))
        self.assertTrue(any(
            item["relation"] == "imports" and item["dst"] == "file:web/util.ts"
            and item["evidence_level"] == "S1" for item in edges
        ))
        self.assertTrue(any(
            item["relation"] == "calls" and item["evidence_level"] == "S0"
            for item in edges
        ))

    def test_nix_similar_path_suffixes_cannot_promote_prefix(self):
        self.write("foo.nix", "{ ... }: { }\n")
        self.write("bar.nix", "{ ... }: { }\n")
        self.write("flake.nix", (
            "a = import ./foo.nix.bak;\n"
            "b = import ./foo.nix-old;\n"
            "c = import ./foo.nix/path;\n"
            "d = import ./foo.nix+extra;\n"
            "e = import ./bar.nix;\n"
        ))
        edges, _ = self.projection()
        imports = [item for item in edges if item["src"] == "file:flake.nix"]
        self.assertEqual(["file:bar.nix"], [item["dst"] for item in imports])
        self.assertTrue(all(item["evidence_level"] == "S1" for item in imports))

    def test_schema_id_may_rebase_and_must_not_claim_wrong_file(self):
        self.write("schemas/base.json", '{"type":"object"}\n')
        self.write("schemas/nested/base.json", '{"type":"object"}\n')
        self.write("schemas/consumer.json", (
            '{"$id":"nested/consumer.json","$ref":"base.json"}\n'
        ))
        self.write("schemas/scoped.json", (
            '{"properties":{"inner":{"$id":"nested/inner.json","$ref":"base.json"}}}\n'
        ))
        edges, _ = self.projection()
        hits = [
            row for row in edges if row["relation"] == "declares_contract"
            and row["src"] in {"file:schemas/consumer.json", "file:schemas/scoped.json"}
        ]
        self.assertEqual(2, len(hits))
        for edge in hits:
            self.assertEqual("S0", edge["evidence_level"])
            self.assertEqual("unresolved", edge["resolution_status"])
            self.assertNotEqual("file:schemas/base.json", edge["dst"])

    def test_js_regex_quotes_do_not_consume_real_symbols_or_imports(self):
        self.write("web/util.js", "export const x = 1;\n")
        self.write("web/consumer.js", (
            "const quote = /\"/;\n"
            "const cls = /[\"']+/;\n"
            "const escaped = /a\\/b/;\n"
            "export function real() {}\n"
            "import './util';\n"
            "real();\n"
        ))
        edges, _ = self.projection()
        own = [row for row in edges if row["src"] == "file:web/consumer.js"]
        self.assertTrue(any(
            row["relation"] == "defines"
            and row["dst"] == "js:web/consumer.js:function:real:L4" for row in own
        ))
        self.assertTrue(any(
            row["relation"] == "imports"
            and row["dst"] == "file:web/util.js"
            and row["evidence_level"] == "S1" for row in own
        ))
        self.assertEqual(1, len([row for row in own if row["relation"] == "calls"]))

    def test_nested_js_template_never_promotes_inner_text_to_s1(self):
        self.write("web/util.js", "export const x = 1;\n")
        tick = chr(96)
        source = (
            "const x = " + tick + "outer " + "$" + "{wrap(" + tick
            + 'inner\nimport "./util";\nfunction fake() {}\n'
            + tick + ")} end" + tick + ";\n"
            + "export function real() {}\n"
            + 'import "./util";\n'
        )
        self.write("web/main.js", source)
        edges, _ = self.projection()
        own = [e for e in edges if e["src"] == "file:web/main.js"]
        definitions = [e["dst"] for e in own if e["relation"] == "defines"]
        imports = [e for e in own if e["relation"] == "imports"]
        self.assertEqual(["js:web/main.js:function:real:L5"], definitions)
        self.assertEqual(1, len(imports))
        self.assertEqual("file:web/util.js", imports[0]["dst"])

    def test_nix_identifier_with_import_suffix_must_not_be_builtin(self):
        self.write("foo.nix", "{ ... }: {}\n")
        self.write("bar.nix", "{ ... }: {}\n")
        self.write("flake.nix", (
            "let my-import = path: path;\n"
            "    my'import = path: path;\n"
            "in { ignored = my-import ./foo.nix;\n"
            "     ignored2 = my'import ./foo.nix;\n"
            "     actual = import ./bar.nix; }\n"
        ))
        edges, _ = self.projection()
        refs = [e for e in edges if e["src"] == "file:flake.nix"]
        self.assertEqual(["file:bar.nix"], [e["dst"] for e in refs])

    def test_output_bytes_and_file_limits_deterministic(self):
        self.write("a.ts", "import './unknown';\n")
        self.write("b.ts", "import './unknown';\n")
        first = self.projection()
        second = self.projection()
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        bounded, coverage = self.projection(max_files=1)
        self.assertEqual(1, coverage["files_parsed"])
        self.assertEqual(1, coverage["skipped"]["file_count_limit"])
        self.assertEqual(1, len(bounded))
        with self.assertRaisesRegex(ValueError, "max_files"):
            self.projection(max_files=0)
        with self.assertRaisesRegex(ValueError, "max_total_bytes"):
            self.projection(max_total_bytes=True)

    def test_shared_graph_projection_emits_all_four_languages(self):
        from merger.repoground.architecture.relationship_projection import generate_relationship_document

        self.write("web/util.ts", "export const x = 1;\n")
        self.write("web/main.ts", "import {x} from './util';\n")
        self.write("modules/gui.nix", "{ ... }: {}\n")
        self.write("flake.nix", "let module = import ./modules/gui.nix; in module\n")
        self.write("schemas/base.json", '{"type":"object"}\n')
        self.write("schemas/consumer.json", '{"$ref":"./base.json"}\n')
        self.write("compose.yml", "services:\n  web:\n    image: busybox\n")
        document = generate_relationship_document(self.root, "run-1", "a" * 64)
        relations = {(e["src"], e["dst"], e["relation"], e["evidence_level"])
                     for e in document["edges"]}
        self.assertIn(("file:web/main.ts", "file:web/util.ts", "imports", "S1"), relations)
        self.assertIn(("file:flake.nix", "file:modules/gui.nix", "imports", "S1"), relations)
        self.assertIn(("file:schemas/consumer.json", "file:schemas/base.json",
                       "declares_contract", "S1"), relations)
        self.assertIn(("file:compose.yml", "declared-service:compose.yml:web",
                       "configures_service", "S0"), relations)
        coverage = document["coverage"]["declared_source_coverage"]
        self.assertGreaterEqual(coverage["files_parsed"], 7)
        self.assertEqual("a" * 64, document["canonical_dump_index_sha256"])
        schema = Path(__file__).parent.parent / "contracts" / "relationship_projection.v1.schema.json"
        try:
            import jsonschema
        except ImportError:
            pass
        else:
            jsonschema.validate(document, json.loads(schema.read_text(encoding="utf-8")))

    def test_relation_edge_limit_is_explicit_not_claimed_complete(self):
        self.write("lib.ts", "export function target() { }\ntarget();\n")
        self.write("other.ts", "export function more() { }\nmore();\n")
        edges, coverage = self.projection(max_relation_edges=1)
        self.assertEqual(1, len(edges))
        self.assertTrue(coverage["truncated"])
        self.assertGreater(coverage["skipped"].get("files_not_scanned_after_relation_limit", 0)
                           + coverage["skipped"].get("relation_edge_limit", 0), 0)
        with self.assertRaisesRegex(ValueError, "max_relation_edges"):
            self.projection(max_relation_edges=False)

    def test_symlink_inventory_cannot_read_outside_repository(self):
        outside = self.root.parent / (self.root.name + "-external.ts")
        outside.write_text("import './secret';\n", encoding="utf-8")
        self.addCleanup(outside.unlink)
        link = self.root / "leak.ts"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            self.skipTest(str(exc))
        edges, coverage = self.projection()
        self.assertFalse(edges)
        self.assertGreaterEqual(coverage["skipped"].get("symlink_or_outside_repo", 0), 1)


if __name__ == "__main__":
    unittest.main()