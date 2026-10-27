"""Bounded, source-specific cross-format relationship fixtures."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from merger.repoground.architecture.declared_relations import extract_declared_relations
from merger.repoground.architecture.import_graph import generate_import_graph_document
from merger.repoground.architecture.relationship_projection import generate_relationship_document


class TestStaticConfigLinks(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, path: str, data: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding="utf-8")

    def edges(self):
        graph = generate_import_graph_document(self.root, "run-static-1", "a" * 64)
        result, coverage = extract_declared_relations(self.root, graph)
        return result, coverage, graph

    def test_markdown_exact_links_with_code_html_and_anchor_boundaries(self):
        self.write("README.md", "# root\n")
        self.write("docs/detail.md", "# File exists, fragment unchecked\n")
        tick = chr(96)
        self.write("docs/overview.md", (
            "[real](./detail.md#part)\n"
            "[above](../README.md)\n"
            "[unknown](./missing.md)\n"
            "[site](https://example.org/x.md)\n"
            + tick + "[fake](./detail.md)" + tick + "\n"
            + tick * 3 + "md\n[code](./detail.md)\n" + tick * 3 + "\n"
            "<!-- [comment](./detail.md) -->\n"
            "<pre>\n[htmlcode](./detail.md)\n</pre>\n"
            "Example:\n\n"
            "    [indented](./detail.md)\n"
            "\t[tabbed](./detail.md)\n"
            "  \t[two-spaces-tab](./detail.md)\n"
        ))
        edges, coverage, graph = self.edges()
        self.assertEqual("markdown", next(
            n["language"] for n in graph["nodes"] if n["node_id"] == "file:docs/overview.md"
        ))
        own = [e for e in edges if e["src"] == "file:docs/overview.md"]
        self.assertEqual(3, len(own), own)
        self.assertEqual(
            {"file:docs/detail.md", "file:README.md"},
            {e["dst"] for e in own if e["evidence_level"] == "S1"},
        )
        self.assertEqual(1, len([e for e in own if e["evidence_level"] == "S0"]))
        self.assertEqual(1, len([e for e in own if e["resolution_status"] == "unresolved"]))
        self.assertTrue(any(e["source"]["range_ref"] == "file:docs/overview.md#L1-L1" for e in own))
        self.assertIn("markdown_anchor_validity", coverage["does_not_establish"])

    def test_github_actions_exact_local_metadata_remote_and_block_scalar(self):
        self.write(".github/workflows/reusable.yml", "name: reused\non: workflow_call\n")
        self.write("actions/local/action.yml", "name: local\nruns:\n  using: composite\n  steps: []\n")
        self.write("actions/dupe/action.yml", "name: ambig1\n")
        self.write("actions/dupe/action.yaml", "name: ambig2\n")
        self.write(".github/workflows/build.yml", (
            "jobs:\n"
            "  reused:\n"
            "    uses: ./.github/workflows/reusable.yml\n"
            "  build:\n"
            "    steps:\n"
            "      - uses: ./actions/local\n"
            "      - uses: ./actions/dupe\n"
            "      - uses: actions/checkout@v4\n"
            "        with:\n"
            "          uses: ./.github/workflows/reusable.yml\n"
            "      - run: |\n"
            "          uses: ./.github/workflows/fake.yml\n"
            "      - run: |2\n"
            "          uses: ./actions/local\n"
            "      - run: >2-\n"
            "          uses: ./actions/local\n"
            "      - run: >-2\n"
            "          uses: ./actions/local\n"
            "      - run: |+2\n"
            "          uses: ./actions/local\n"
            "      - uses: $/actions/local\n"
            "      - uses: ./.github/workflows/reusable.yml\n"
            "      - run: echo uses: ./.github/workflows/fake.yml\n"
            "    env:\n"
            "      uses: ./.github/workflows/reusable.yml\n"
            "      steps:\n"
            "        - uses: ./actions/local\n"
            "  invalid_job:\n"
            "    uses: ./actions/local\n"
        ))
        edges, coverage, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:.github/workflows/build.yml"]
        resolved = [e for e in own if e["evidence_level"] == "S1"]
        self.assertEqual(3, len(resolved), own)
        self.assertEqual({
            "file:.github/workflows/reusable.yml",
            "file:actions/local/action.yml",
        }, {e["dst"] for e in resolved})
        ambiguous = [e for e in own if e["origin_artifact"] ==
                     "github_actions_ambiguous_action_metadata"]
        self.assertEqual(1, len(ambiguous))
        self.assertEqual({
            "file:actions/dupe/action.yml", "file:actions/dupe/action.yaml",
        }, set(ambiguous[0]["candidate_target_ids"]))
        external = [e for e in own if e["dst"] == "external-action:actions/checkout@v4"]
        self.assertEqual(1, len(external))
        self.assertEqual("S0", external[0]["evidence_level"])
        invalid_reusable = [e for e in own if e["origin_artifact"] ==
                            "github_actions_step_uses_unproven"]
        invalid_job = [e for e in own if e["origin_artifact"] ==
                       "github_actions_job_uses_unproven"]
        self.assertEqual(1, len(invalid_reusable))
        self.assertEqual(["file:.github/workflows/reusable.yml"],
                         invalid_reusable[0]["candidate_target_ids"])
        self.assertEqual(1, len(invalid_job))
        self.assertEqual("S0", invalid_job[0]["evidence_level"])
        self.assertNotIn("fake.yml", json.dumps(own))
        self.assertIn("github_actions_execution", coverage["does_not_establish"])

    def test_composite_action_local_uses_and_untrusted_yaml_context(self):
        self.write("actions/first/action.yml", "name: first\n")
        self.write("actions/first/action.yaml", "name: duplicate\n")
        self.write("actions/composite/action.yml", (
            "name: composite\n"
            "runs:\n"
            "  using: composite\n"
            "  steps:\n"
            "    - uses: ./actions/first\n"
            "    - run: |\n"
            "        uses: ./actions/first\n"
            "env:\n"
            "  steps:\n"
            "    - uses: ./actions/first\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges if edge["src"] == "file:actions/composite/action.yml"]
        self.assertEqual(1, len(own))
        self.assertEqual("S0", own[0]["evidence_level"])
        self.assertEqual({
            "file:actions/first/action.yml", "file:actions/first/action.yaml",
        }, set(own[0]["candidate_target_ids"]))


    def test_indentless_yaml_steps_keep_action_context(self):
        self.write("actions/local/action.yml", "name: local\n")
        self.write(".github/workflows/indentless.yml", (
            "jobs:\n"
            "  build:\n"
            "    steps:\n"
            "    - uses: ./actions/local\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:.github/workflows/indentless.yml"]
        self.assertEqual(
            [("file:actions/local/action.yml", "S1")],
            [(e["dst"], e["evidence_level"]) for e in own],
        )

    def test_multiline_yaml_quoted_scalar_does_not_invent_uses(self):
        self.write("actions/local/action.yml", "name: local\n")
        self.write(".github/workflows/quoted.yml", (
            "jobs:\n"
            "  build:\n"
            "    steps:\n"
            '      - run: "echo starts\n'
            "          uses: ./actions/local\n"
            '        done"\n'
            "      - run: 'start\n"
            "          uses: ./actions/local\n"
            "        it''s done'\n"
            "      - uses: ./actions/local\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:.github/workflows/quoted.yml"]
        self.assertEqual(1, len(own), own)
        self.assertEqual("file:actions/local/action.yml", own[0]["dst"])
        self.assertEqual("S1", own[0]["evidence_level"])
        self.assertEqual(10, own[0]["source"]["start_line"])

    def test_multiline_markdown_code_span_excludes_only_code_links(self):
        self.write("docs/target.md", "# real target\n")
        tick = chr(96)
        self.write("docs/inline.md", (
            "[before](./target.md)\n" + tick + "\n"
            "[not-a-link](./target.md)\n" + tick + "\n"
            "[after](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:docs/inline.md"]
        self.assertEqual(
            [1, 5],
            [e["source"]["start_line"] for e in own if e["evidence_level"] == "S1"],
        )

    def test_systemd_shell_caddy_relations_all_remain_s0(self):
        self.write("units/app.service", (
            "[Unit]\n"
            "Description=My service\n"
            "Requires=cache.service db@.service\n"
            "After=network.target\n"
            "[Service]\n"
            "ExecStart=/usr/bin/true\n"
        ))
        self.write("units/cache.service", "[Unit]\nDescription=Cache\n")
        self.write("scripts/helpers.sh", "echo ok\n")
        self.write("scripts/start.sh", (
            "source ./helpers.sh\n"
            ". ../scripts/helpers.sh\n"
            "source \"$DYNAMIC_PATH\"\n"
            "echo 'source ./helpers.sh'\n"
        ))
        self.write("configs/app.caddy", "example.com { respond hello }\n")
        self.write("Caddyfile", (
            "import ./configs/app.caddy\n"
            "import snippets\n"
            "# import ./configs/app.caddy\n"
        ))
        edges, coverage, graph = self.edges()
        languages = {e["path"]: e["language"] for e in graph["nodes"] if e["kind"] == "file"}
        self.assertEqual("systemd", languages["units/app.service"])
        self.assertEqual("shell", languages["scripts/start.sh"])
        self.assertEqual("caddy", languages["Caddyfile"])
        self.assertEqual("caddy", languages["configs/app.caddy"])
        unit = [e for e in edges if e["src"] == "file:units/app.service"]
        self.assertEqual(
            {
                "declared-unit:app.service", "declared-unit:cache.service",
                "declared-unit:db@.service", "declared-unit:network.target",
            }, {e["dst"] for e in unit},
        )
        shell = [e for e in edges if e["src"] == "file:scripts/start.sh"]
        self.assertEqual(2, len(shell))
        self.assertTrue(all(e["evidence_level"] == "S0" for e in shell))
        self.assertTrue(all(
            "file:scripts/helpers.sh" in e.get("candidate_target_ids", []) for e in shell
        ))
        caddy = [e for e in edges if e["src"] == "file:Caddyfile"]
        self.assertEqual(2, len(caddy))
        self.assertTrue(all(e["evidence_level"] == "S0" for e in caddy))
        self.assertEqual(
            ["file:configs/app.caddy"],
            [e["candidate_target_ids"][0] for e in caddy if e.get("candidate_target_ids")],
        )
        self.assertEqual("S0", next(e["evidence_level"] for e in unit if e["relation"] == "configures_service"))
        self.assertIn("caddy_import_expansion", coverage["does_not_establish"])

    def test_projection_contract_is_stable_and_legacy_consumers_unchanged(self):
        self.write("README.md", "[graph](./target.md)\n")
        self.write("target.md", "# target\n")
        self.write("app.sh", "source ./other.sh\n")
        self.write("other.sh", "echo x\n")
        first = generate_relationship_document(self.root, "run-static", "b" * 64)
        second = generate_relationship_document(self.root, "run-static", "b" * 64)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertIn(
            ("file:README.md", "file:target.md", "references", "S1"),
            {(e["src"], e["dst"], e["relation"], e["evidence_level"]) for e in first["edges"]},
        )
        self.assertEqual("b" * 64, first["canonical_dump_index_sha256"])
        self.assertGreaterEqual(first["coverage"]["declared_source_coverage"]["files_parsed"], 4)
        contract = (
            Path(__file__).parent.parent / "contracts" / "relationship_projection.v1.schema.json"
        )
        try:
            import jsonschema
        except ImportError:
            pass
        else:
            jsonschema.validate(first, json.loads(contract.read_text(encoding="utf-8")))

    def test_new_source_limits_do_not_claim_completeness(self):
        self.write("a.md", "[target](./target.md)\n")
        self.write("b.md", "[target](./target.md)\n")
        self.write("target.md", "# target\n")
        graph = generate_import_graph_document(self.root, "run", "a" * 64)
        edges, coverage = extract_declared_relations(self.root, graph, max_relation_edges=1)
        self.assertEqual(1, len(edges))
        self.assertTrue(coverage["truncated"])
        self.assertGreater(coverage["skipped"].get("relation_edge_limit", 0) +
                           coverage["skipped"].get("files_not_scanned_after_relation_limit", 0), 0)


if __name__ == "__main__":
    unittest.main()