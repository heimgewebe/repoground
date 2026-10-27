"""Contract and negative-case checks for the existing-artifact relation projection."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from merger.repoground.architecture.symbol_index import generate_symbol_index_document
from merger.repoground.architecture.call_graph import generate_call_graph_document
from merger.repoground.architecture.import_graph import generate_import_graph_document
from merger.repoground.architecture.relationship_projection import project_relationships


class TestRelationshipProjection(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write("pkg/__init__.py", "")
        self.write("pkg/one.py", "def work():\n    return 1\n")
        self.write("pkg/two.py", "def work():\n    return 2\n")
        self.write("pkg/consumer.py", "from pkg.one import work\n\ndef run():\n    return work()\n")
        self.write("tests/test_consumer.py", "from pkg.consumer import run\n\ndef test_run():\n    return run()\n")
        self.write("pkg/dynamic.py", "def run_dynamic(func):\n    return func()\n")

    def write(self, path: str, source: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")

    def sources(self):
        kw = ("run-id", "a" * 64)
        return {
            "symbol_index": generate_symbol_index_document(self.root, *kw),
            "call_graph": generate_call_graph_document(self.root, *kw, max_workers=1),
            "architecture_graph": generate_import_graph_document(self.root, *kw),
        }

    def test_resolved_calls_and_test_references_are_provenanced(self):
        documents = self.sources()
        result = project_relationships(**documents)
        edges = result["edges"]
        work = "py:pkg:one.py:function:work"
        assert any(edge["relation"] == "defines" and edge["dst"] == work for edge in edges)
        calls = [edge for edge in edges if edge["relation"] == "calls" and edge["dst"] == work]
        self.assertEqual(1, len(calls))
        self.assertEqual(("resolved", "S1"), (calls[0]["resolution_status"], calls[0]["evidence_level"]))
        self.assertEqual("file:pkg/consumer.py#L4-L4", calls[0]["source"]["range_ref"])
        self.assertEqual("py:pkg:consumer.py:function:run", calls[0]["src"])
        self.assertTrue(any(edge["relation"] == "tests" and edge["src"] == "file:tests/test_consumer.py"
                            and edge["dst"] == "py:pkg:consumer.py:function:run" for edge in edges))
        self.assertEqual("a" * 64, result["canonical_dump_index_sha256"])
        self.assertIn("test_sufficiency", result["does_not_establish"])

    def test_unresolved_calls_are_not_promoted_and_alias_collision_is_not_resolved(self):
        docs = self.sources()
        self.write("other.py", "def work():\n    return 3\n")
        self.write("pkg/one/__init__.py", "def work():\n    return 4\n")
        self.write("ambiguous_consumer.py", "import pkg.one\n")
        docs = self.sources()
        edges = project_relationships(**docs)["edges"]
        dynamic = [e for e in edges if e["relation"] == "calls" and e["src"] == "py:pkg:dynamic.py:function:run_dynamic"]
        self.assertEqual(1, len(dynamic))
        self.assertEqual("S0", dynamic[0]["evidence_level"])
        self.assertTrue(dynamic[0]["dst"].startswith("unresolved-call:"))
        unresolved_import = [e for e in edges if e["relation"] == "imports"
                             and e["src"] == "file:ambiguous_consumer.py"]
        self.assertTrue(unresolved_import)
        self.assertTrue(all(e["evidence_level"] == "S0" for e in unresolved_import))
        self.assertTrue(all(e["resolution_status"] == "unresolved" for e in unresolved_import))

    def test_byte_stability_without_producer_wall_clock(self):
        first = project_relationships(**self.sources())
        second = project_relationships(**self.sources())
        self.assertEqual(
            json.dumps(first, ensure_ascii=False, sort_keys=True).encode(),
            json.dumps(second, ensure_ascii=False, sort_keys=True).encode(),
        )

    def test_provenance_mismatch_rejected_not_combined(self):
        docs = self.sources()
        docs["call_graph"] = copy.deepcopy(docs["call_graph"])
        docs["call_graph"]["canonical_dump_index_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "provenance mismatch"):
            project_relationships(**docs)

    def test_generate_document_and_contract_structure(self):
        from merger.repoground.architecture.relationship_projection import generate_relationship_document
        expected = project_relationships(**self.sources())
        actual = generate_relationship_document(self.root, "run-id", "a" * 64)
        self.assertEqual(expected, actual)
        contract = Path(__file__).parent.parent / "contracts" / "relationship_projection.v1.schema.json"
        schema = json.loads(contract.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["kind"]["const"], actual["kind"])
        self.assertEqual(schema["properties"]["version"]["const"], actual["version"])
        # Validate with jsonschema in full environments without making this
        # standard-library regression depend on an optional local package.
        try:
            import jsonschema
        except ImportError:
            pass
        else:
            jsonschema.validate(actual, schema)

    def test_bounded_edges_and_invalid_ranges(self):
        docs = self.sources()
        result = project_relationships(**docs, max_edges=1)
        self.assertEqual(1, result["coverage"]["emitted_edges"])
        self.assertTrue(result["coverage"]["truncated"])
        with self.assertRaisesRegex(ValueError, "max_edges"):
            project_relationships(**docs, max_edges=True)
        docs["symbol_index"] = copy.deepcopy(docs["symbol_index"])
        docs["symbol_index"]["symbols"][0]["start_line"] = -1
        with self.assertRaisesRegex(ValueError, "range"):
            project_relationships(**docs)


if __name__ == "__main__":
    unittest.main()