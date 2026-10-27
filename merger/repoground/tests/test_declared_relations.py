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