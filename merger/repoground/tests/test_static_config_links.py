"""Bounded, source-specific cross-format relationship fixtures."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from merger.repoground.architecture.declared_relations import extract_declared_relations
from merger.repoground.architecture.import_graph import generate_import_graph_document
from merger.repoground.architecture.relationship_projection import (
    generate_relationship_document,
)
from merger.repoground.architecture.static_config_links import config_reference_edges


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

    def test_github_actions_quoted_uses_keys_are_real_references(self):
        import yaml

        self.write(".github/workflows/reusable.yml", "on: workflow_call\n")
        self.write("actions/local/action.yml", "name: local\n")
        source = (
            "jobs:\n"
            "  reusable:\n"
            '    "uses": ./.github/workflows/reusable.yml\n'
            "  build:\n"
            "    steps:\n"
            '      - "uses": ./actions/local\n'
            "      - 'uses': ./actions/local\n"
            "      - env:\n"
            '          "uses": ./actions/local\n'
            '        "uses": ./actions/local\n'
            "      - run: |\n"
            '          "uses": ./actions/local\n'
        )
        parsed = yaml.safe_load(source)
        self.assertEqual("./.github/workflows/reusable.yml", parsed["jobs"]["reusable"]["uses"])
        self.assertEqual("./actions/local", parsed["jobs"]["build"]["steps"][0]["uses"])
        self.assertEqual("./actions/local", parsed["jobs"]["build"]["steps"][1]["uses"])
        self.write(".github/workflows/quoted-uses.yml", source)
        self.write("actions/composite/action.yml", (
            "runs:\n  using: composite\n  steps:\n"
            "    - 'uses': ./actions/local\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges if edge["src"] == "file:.github/workflows/quoted-uses.yml"]
        proven = [edge for edge in own if edge["evidence_level"] == "S1"]
        self.assertEqual([3, 6, 7, 10], [
            edge["source"]["start_line"] for edge in proven
        ], own)
        self.assertEqual(
            ["file:.github/workflows/reusable.yml"]
            + ["file:actions/local/action.yml"] * 3,
            [edge["dst"] for edge in proven],
        )
        composite = [
            edge for edge in edges
            if edge["src"] == "file:actions/composite/action.yml"
        ]
        self.assertEqual(
            [("file:actions/local/action.yml", "S1")],
            [(edge["dst"], edge["evidence_level"]) for edge in composite],
        )

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
            '      - run: "echo uses: ./.github/workflows/fake.yml"\n'
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


    def test_markdown_blockquote_fence_masks_links_but_keeps_prose(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/quoted.md", (
            "> ~~~markdown\n"
            "> [example](./target.md)\n"
            "> ~~~\n"
            "> [real](./target.md)\n"
            "> > ~~~md\n"
            "> > [nested-code](./target.md)\n"
            "> > ~~~\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:docs/quoted.md"]
        self.assertEqual([4], [e["source"]["start_line"] for e in own], own)
        self.assertEqual("S1", own[0]["evidence_level"])

    def test_markdown_tab_quote_fence_is_not_prose(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/tabbed.md", (
            ">\t~~~markdown\n"
            ">\t[not-a-link](./target.md)\n"
            ">\t~~~\n"
            "[real](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:docs/tabbed.md"]
        self.assertEqual([4], [e["source"]["start_line"] for e in own], own)

    def test_markdown_unmatched_backtick_does_not_hide_real_links(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/unmatched.md", (
            "Text with unmatched ` and [same](./target.md)\n"
            "\n"
            "[after](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:docs/unmatched.md"]
        self.assertEqual([1, 3], [e["source"]["start_line"] for e in own], own)
        self.assertTrue(all(e["evidence_level"] == "S1" for e in own))

    def test_markdown_inline_and_fenced_html_examples_do_not_swallow_links(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/inline-html.md", (
            "Use `<code>` to start a code span.\n"
            "[real](./target.md)\n"
        ))
        self.write("docs/fenced-html.md", (
            "~~~html\n"
            "<pre>\n"
            "~~~\n"
            "[real](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        for name, expected_line in (("inline-html", 2), ("fenced-html", 4)):
            own = [e for e in edges if e["src"] == f"file:docs/{name}.md"]
            self.assertEqual([expected_line], [
                e["source"]["start_line"] for e in own
            ], own)

    def test_markdown_list_item_fence_does_not_invent_dependencies(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/list-fences.md", (
            "- ~~~markdown\n"
            "  [example](./target.md)\n"
            "  ~~~\n"
            "[real](./target.md)\n"
            "\n10000. ~~~md\n"
            "       [example2](./target.md)\n"
            "       ~~~\n"
            "[after](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:docs/list-fences.md"]
        self.assertEqual([4, 9], [
            e["source"]["start_line"] for e in own
        ], own)

    def test_yaml_anchored_env_mapping_does_not_fake_local_action(self):
        self.write("actions/local/action.yml", "name: local\n")
        self.write(".github/workflows/anchor.yml", (
            "jobs:\n"
            "  build:\n"
            "    steps:\n"
            "      - env: &shared\n"
            "          uses: ./actions/local\n"
            "        run: echo hello\n"
            "      - uses: ./actions/local\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:.github/workflows/anchor.yml"]
        self.assertEqual([7], [e["source"]["start_line"] for e in own], own)

    def test_yaml_anchored_scalar_properties_do_not_create_s1_edges(self):
        import yaml

        self.write("actions/local/action.yml", "name: local\n")
        cases = (
            ("block", "- run: &script |", ""),
            ("folded_quoted_key", '- "run": &script >-', ""),
            ("tag_before_anchor", "- run: !!str &script |", ""),
            ("anchor_before_tag", "- run: &script !!str |", ""),
            ("multiline_double", '- "name": &description "first line', '        last line"\n'),
            ("multiline_single", "- 'name': &description 'first line", "        last line'\n"),
        )
        for label, opening, closing in cases:
            with self.subTest(label=label):
                source = (
                    "jobs:\n"
                    "  build:\n"
                    "    steps:\n"
                    f"      {opening}\n"
                    "          uses: ./actions/local\n"
                    + closing
                    + "      - uses: ./actions/local\n"
                )
                parsed = yaml.safe_load(source)
                first, second = parsed["jobs"]["build"]["steps"]
                self.assertIn("uses: ./actions/local", first.get("run", first.get("name")))
                self.assertEqual("./actions/local", second["uses"])
                path = f".github/workflows/anchored-{label}.yml"
                self.write(path, source)
                edges, _, _ = self.edges()
                own = [edge for edge in edges if edge["src"] == f"file:{path}"]
                actual = [(edge["source"]["start_line"], edge["evidence_level"]) for edge in own]
                self.assertEqual([(len(source.splitlines()), "S1")], actual, own)

    def test_markdown_html_comment_opened_inside_fence_cannot_hide_real_links(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/commented-fence.md", (
            "~~~html\n"
            "<!--\n"
            "~~~\n"
            "\n"
            "[real](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:docs/commented-fence.md"]
        self.assertEqual([5], [e["source"]["start_line"] for e in own], own)

    def test_markdown_backslash_before_code_span_closer_is_still_closing(self):
        self.write("docs/fake.md", "# must be masked\n")
        self.write("docs/real.md", "# real target\n")
        tick = chr(96)
        slash = chr(92)
        self.write("docs/backslash-closer.md", (
            tick + "[fake](./fake.md)" + slash + tick
            + " [real](./real.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:docs/backslash-closer.md"]
        self.assertEqual(["file:docs/real.md"], [e["dst"] for e in own], own)
        self.assertEqual("S1", own[0]["evidence_level"])

    def test_yaml_step_env_mapping_does_not_emit_action_edge(self):
        self.write("actions/local/action.yml", "name: local\n")
        self.write(".github/workflows/env.yml", (
            "jobs:\n"
            "  build:\n"
            "    steps:\n"
            "      - env:\n"
            "          uses: ./actions/local\n"
            "      - uses: ./actions/local\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:.github/workflows/env.yml"]
        self.assertEqual(1, len(own), own)
        self.assertEqual("S1", own[0]["evidence_level"])
        self.assertEqual("file:actions/local/action.yml", own[0]["dst"])
        self.assertEqual(6, own[0]["source"]["start_line"])

    def test_markdown_info_fence_is_not_a_closing_fence(self):
        self.write("docs/target.md", "# target\n")
        ticks = chr(96) * 3
        self.write("docs/fences.md", (
            ticks + "markdown\n"
            + ticks + "bash\n"
            "[not-link](./target.md)\n"
            + ticks + "\n"
            "[real](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:docs/fences.md"]
        self.assertEqual([5], [
            e["source"]["start_line"] for e in own if e["evidence_level"] == "S1"
        ])

    def test_repository_root_composite_action_uses_metadata(self):
        self.write("actions/local/action.yml", "name: local\n")
        for filename in ("action.yml", "action.yaml"):
            self.write(filename, (
                "name: root\n"
                "runs:\n"
                "  using: composite\n"
                "  steps:\n"
                "    - uses: ./actions/local\n"
            ))
        edges, _, _ = self.edges()
        for filename in ("action.yml", "action.yaml"):
            own = [e for e in edges if e["src"] == "file:" + filename]
            self.assertEqual(1, len(own), own)
            self.assertEqual("file:actions/local/action.yml", own[0]["dst"])
            self.assertEqual("S1", own[0]["evidence_level"])
            self.assertEqual(5, own[0]["source"]["start_line"])


    def test_yaml_sequence_mapping_sibling_action_uses_is_extracted(self):
        self.write("actions/local/action.yml", "name: local\n")
        self.write("actions/decoy/action.yml", "name: decoy\n")
        self.write(".github/workflows/sibling.yml", (
            "jobs:\n"
            "  build:\n"
            "    steps:\n"
            "      - env:\n"
            "          uses: ./actions/decoy\n"
            "        uses: ./actions/local\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:.github/workflows/sibling.yml"]
        self.assertEqual(1, len(own), own)
        self.assertEqual("file:actions/local/action.yml", own[0]["dst"])
        self.assertEqual("S1", own[0]["evidence_level"])
        self.assertEqual(6, own[0]["source"]["start_line"])

    def test_workflow_root_local_action_directory_is_resolved(self):
        self.write("action.yml", "name: repository root\n")
        self.write(".github/workflows/root.yml", (
            "jobs:\n"
            "  build:\n"
            "    steps:\n"
            "      - uses: ./\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:.github/workflows/root.yml"]
        self.assertEqual(1, len(own), own)
        self.assertEqual("file:action.yml", own[0]["dst"])
        self.assertEqual("S1", own[0]["evidence_level"])

    def test_escaped_markdown_link_openers_do_not_claim_s1(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/escape.md", (
            "\\" + "[not-a-link](./target.md)\n"
            + "\\\\" + "[escaped-backslash-then-link](./target.md)\n"
            + "[actual](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:docs/escape.md"]
        self.assertEqual(
            [2, 3],
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

    def test_quoted_yaml_step_mapping_keys_do_not_fake_actions(self):
        self.write("actions/local/action.yml", "name: local\n")
        self.write(".github/workflows/quoted-mapping.yml", (
            "jobs:\n"
            "  build:\n"
            "    steps:\n"
            '      - "env":\n'
            "          uses: ./actions/local\n"
            "      - 'with':\n"
            "          uses: ./actions/local\n"
            "      - uses: ./actions/local\n"
            "  quoted:\n"
            '    "steps":\n'
            "      - uses: ./actions/local\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges
               if edge["src"] == "file:.github/workflows/quoted-mapping.yml"]
        self.assertEqual([8, 11], [
            edge["source"]["start_line"] for edge in own
            if edge["evidence_level"] == "S1"
        ], own)

    def test_unclosed_blockquote_fence_ends_at_quote_boundary(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/unclosed-quote.md", (
            "> ~~~sh\n"
            "> echo hello\n"
            "\n"
            "[real](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges if edge["src"] == "file:docs/unclosed-quote.md"]
        self.assertEqual([4], [edge["source"]["start_line"] for edge in own], own)

    def test_unclosed_nested_quote_fence_does_not_hide_outer_prose(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/nested-unclosed.md", (
            "> > ~~~sh\n"
            "> > echo hello\n"
            "> [outer](./target.md)\n"
            "[outside](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges if edge["src"] == "file:docs/nested-unclosed.md"]
        self.assertEqual([3, 4], [edge["source"]["start_line"] for edge in own], own)

    def test_unclosed_list_fence_does_not_hide_outside_prose(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/list-unclosed.md", (
            "- ~~~sh\n"
            "  echo hello\n"
            "[real](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges if edge["src"] == "file:docs/list-unclosed.md"]
        self.assertEqual([3], [edge["source"]["start_line"] for edge in own], own)

    def test_html_comment_inside_unclosed_quote_fence_is_literal(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/comment-unclosed.md", (
            "> ~~~html\n"
            "> <!--\n"
            "\n"
            "[real](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges if edge["src"] == "file:docs/comment-unclosed.md"]
        self.assertEqual([4], [edge["source"]["start_line"] for edge in own], own)

    def test_quoted_yaml_multiline_scalar_bodies_never_emit_action_edges(self):
        self.write("actions/local/action.yml", "name: local\n")
        self.write(".github/workflows/quoted-scalars.yml", (
            "jobs:\n"
            "  build:\n"
            "    steps:\n"
            '      - "run": |\n'
            "          uses: ./actions/local\n"
            "      - 'run': >-\n"
            "          uses: ./actions/local\n"
            '      - "name": "first line\n'
            "          uses: ./actions/local\n"
            '        last line"\n'
            "      - uses: ./actions/local\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges
               if edge["src"] == "file:.github/workflows/quoted-scalars.yml"]
        self.assertEqual([11], [
            edge["source"]["start_line"] for edge in own
            if edge["evidence_level"] == "S1"
        ], own)

    def test_markdown_links_survive_inline_and_multiline_html_code_tags(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/second.md", "# second\n")
        self.write("docs/code-prose.md", (
            "[before](./target.md) <code>[hidden](./target.md)</code> "
            "[after](./second.md)\n"
            "<code>[hidden-start](./target.md)\n"
            "[hidden-end](./target.md)</code> [after-close](./target.md)\n"
            "<pre class='sample'>[hidden-pre](./target.md)</pre> "
            "[end](./target.md)\n"
            "`<code>` [literal](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges if edge["src"] == "file:docs/code-prose.md"]
        self.assertEqual([1, 1, 3, 5],
                         [edge["source"]["start_line"] for edge in own], own)

    def test_markdown_active_html_closes_before_markdown_exclusions(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/html-closing.md", (
            "<pre>\n"
            "[hidden](./target.md)\n"
            "    </pre>\n"
            "[after-indented-close](./target.md)\n"
            "<pre>\n"
            "`</pre>` [after-backtick-close](./target.md)\n"
            "`<pre>` [literal-opener](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges
               if edge["src"] == "file:docs/html-closing.md"]
        self.assertEqual([4, 7], [
            edge["source"]["start_line"] for edge in own
        ], own)

    def test_multiline_yaml_flow_mapping_does_not_invent_step_uses(self):
        self.write("actions/local/action.yml", "name: local\n")
        self.write(".github/workflows/flow-env.yml", (
            "jobs:\n"
            "  build:\n"
            "    steps:\n"
            "      - env: {\n"
            "          NOTE: value,\n"
            "          uses: ./actions/local\n"
            "        }\n"
            "        uses: ./actions/local\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges
               if edge["src"] == "file:.github/workflows/flow-env.yml"]
        self.assertEqual([8], [
            edge["source"]["start_line"] for edge in own
        ], own)

    def test_multiline_html_closing_line_remains_raw(self):
        self.write("docs/target.md", "# target\n")
        for closing in ("</pre>", "`</pre>`", "    </pre>"):
            with self.subTest(closing=closing):
                self.write("docs/raw.md", (
                    "<pre>\n[hidden](./target.md)\n"
                    + closing + " [hidden](./target.md)\n"
                    "[real](./target.md)\n"
                    "<code>hidden</code> [suffix](./target.md)\n"
                ))
                edges, _, _ = self.edges()
                own = [edge for edge in edges if edge["src"] == "file:docs/raw.md"]
                self.assertEqual([(4, "S1"), (5, "S1")], [
                    (edge["source"]["start_line"], edge["evidence_level"])
                    for edge in own
                ], own)

    def test_flow_yaml_multiline_quotes_hide_false_uses(self):
        self.write("actions/local/action.yml", "name: local\n")
        for quote in ('"', "'"):
            with self.subTest(quote=quote):
                self.write(".github/workflows/quotes.yml", (
                    "jobs:\n  build:\n    steps:\n      - env: {\n"
                    + "          NOTE: " + quote + "hello,\n"
                    "            a line with } inside the still-open quote\n"
                    "          uses: ./actions/local\n"
                    + "          " + quote + "\n"
                    "        }\n        uses: ./actions/local\n"
                ))
                edges, _, _ = self.edges()
                own = [edge for edge in edges
                       if edge["src"] == "file:.github/workflows/quotes.yml"]
                self.assertEqual([(10, "S1")], [
                    (edge["source"]["start_line"], edge["evidence_level"])
                    for edge in own
                ], own)

    def test_flow_yaml_plain_scalar_quote_punctuation_preserves_uses(self):
        self.write("actions/local/action.yml", "name: local\n")
        for value in ("hello ' world", 'hello " world', "hello'world", 'hello"world'):
            with self.subTest(value=value):
                self.write(".github/workflows/plain-quotes.yml", (
                    "jobs:\n  build:\n    steps:\n      - env: {NOTE: "
                    + value + "}\n        uses: ./actions/local\n"
                ))
                edges, _, _ = self.edges()
                own = [edge for edge in edges
                       if edge["src"] == "file:.github/workflows/plain-quotes.yml"]
                self.assertEqual([(5, "S1")], [
                    (edge["source"]["start_line"], edge["evidence_level"])
                    for edge in own
                ], own)

    def test_flow_yaml_quote_opening_on_collection_line_remains_multiline(self):
        self.write("actions/local/action.yml", "name: local\n")
        for quote, escaped in (("'", "''"), ('"', '\\"')):
            with self.subTest(quote=quote):
                self.write(".github/workflows/inline-flow-quote.yml", (
                    "jobs:\n  build:\n    steps:\n      - env: {NOTE: "
                    + quote + "hello " + escaped + " }\n"
                    "          uses: ./actions/local\n"
                    + "          world" + quote + "}\n"
                    "        uses: ./actions/local\n"
                ))
                edges, _, _ = self.edges()
                own = [edge for edge in edges
                       if edge["src"] == "file:.github/workflows/inline-flow-quote.yml"]
                self.assertEqual([(7, "S1")], [
                    (edge["source"]["start_line"], edge["evidence_level"])
                    for edge in own
                ], own)

    def test_same_line_html_block_close_masks_suffix_but_inline_code_does_not(self):
        self.write("docs/target.md", "# target\n")
        for opening in ("<pre>", "<PRE class='sample'>"):
            with self.subTest(opening=opening):
                self.write("docs/same-line-html.md", (
                    opening + "hidden</pre> [hidden](./target.md)\n"
                    "[real](./target.md)\n"
                    "<code>[hidden](./target.md)</code> [real](./target.md)\n"
                    "`<pre>hidden</pre>` [real](./target.md)\n"
                ))
                edges, _, _ = self.edges()
                own = [edge for edge in edges
                       if edge["src"] == "file:docs/same-line-html.md"]
                self.assertEqual([(2, "S1"), (3, "S1"), (4, "S1")], [
                    (edge["source"]["start_line"], edge["evidence_level"])
                    for edge in own
                ], own)

    def test_pre_whole_line_mask_requires_html_block_start(self):
        for prefix in ("", "   ", "> ", "> > ", "- ", "> - "):
            for inline in (False, True):
                with self.subTest(prefix=prefix, inline=inline):
                    before = "[before](./target.md) " if inline else ""
                    source = (
                        prefix + before + "<pre>hidden</pre> [after](./target.md)\n"
                        "[real](./target.md)\n"
                    )
                    own = config_reference_edges(
                        "docs/pre-start.md", source, {"file:docs/target.md"},
                    )
                    expected = [(1, "S1"), (1, "S1")] if inline else []
                    self.assertEqual(expected + [(2, "S1")], [
                        (edge["source"]["start_line"], edge["evidence_level"])
                        for edge in own
                    ], own)

    def test_inline_pre_continuation_preserves_closing_line_suffix(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/inline-pre.md", (
            "[before](./target.md) <pre>[hidden](./target.md)\n"
            "[hidden](./target.md)</pre> [after](./target.md)\n"
            "[real](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges if edge["src"] == "file:docs/inline-pre.md"]
        self.assertEqual([(1, "S1"), (2, "S1"), (3, "S1")], [
            (edge["source"]["start_line"], edge["evidence_level"])
            for edge in own
        ], own)

    def test_yaml_plain_scalar_bracket_and_embedded_hash_preserve_uses(self):
        self.write("actions/local/action.yml", "name: local\n")
        for value in ("name: Build [linux", "env: {NOTE: abc#def}",
                      "env: {NOTE: abc#def} # comment"):
            with self.subTest(value=value):
                self.write(".github/workflows/plain.yml", (
                    "jobs:\n  build:\n    steps:\n      - " + value
                    + "\n        uses: ./actions/local\n"
                ))
                edges, _, _ = self.edges()
                own = [edge for edge in edges
                       if edge["src"] == "file:.github/workflows/plain.yml"]
                self.assertEqual([(5, "S1")], [
                    (edge["source"]["start_line"], edge["evidence_level"])
                    for edge in own
                ], own)

    def test_local_action_directory_dot_segments_are_normalized_safely(self):
        self.write("actions/local/action.yml", "name: local\n")
        self.write("outside/action.yml", "name: outside\n")
        self.write(".github/workflows/dot-segments.yml", (
            "jobs:\n"
            "  build:\n"
            "    steps:\n"
            "      - uses: ./actions/./local\n"
            "      - uses: ./actions/local/../local\n"
            "      - uses: ./actions/../../outside\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges
               if edge["src"] == "file:.github/workflows/dot-segments.yml"]
        self.assertEqual([
            (4, "file:actions/local/action.yml", "S1"),
            (5, "file:actions/local/action.yml", "S1"),
            (6, "module:./actions/../../outside", "S0"),
        ], [
            (edge["source"]["start_line"], edge["dst"], edge["evidence_level"])
            for edge in own
        ], own)

    def test_sequence_block_scalar_does_not_hide_sibling_action(self):
        self.write("actions/local/action.yml", "name: local\n")
        self.write(".github/workflows/multiline-name.yml", (
            "jobs:\n"
            "  build:\n"
            "    steps:\n"
            "      - name: >-\n"
            "          uses: ./actions/local\n"
            "        uses: ./actions/local\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges
               if edge["src"] == "file:.github/workflows/multiline-name.yml"]
        self.assertEqual([6], [
            edge["source"]["start_line"] for edge in own
            if edge["evidence_level"] == "S1"
        ], own)

    def test_thousands_of_html_comments_preserve_link_with_bounded_work(self):
        self.write("docs/target.md", "# target\n")
        self.write(
            "docs/many-comments.md",
            "prose " + "<!--x-->" * 8000 + " [real](./target.md)\n",
        )
        started = time.perf_counter()
        edges, _, _ = self.edges()
        elapsed = time.perf_counter() - started
        own = [edge for edge in edges
               if edge["src"] == "file:docs/many-comments.md"]
        self.assertEqual([1], [edge["source"]["start_line"] for edge in own], own)
        # Before this fix even 8k comments spent several seconds repeatedly
        # remasking the full line. Retain a generous CI budget.
        self.assertLess(elapsed, 2.0)

    def test_backtick_inside_html_comment_does_not_hide_following_link(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/comment-backtick.md", (
            "prose <!-- ` inside comment --> [real](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges if edge["src"] == "file:docs/comment-backtick.md"]
        self.assertEqual([1], [edge["source"]["start_line"] for edge in own], own)

    def test_inline_html_code_keeps_backtick_closers_literal(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/code-span.md", (
            "Text <code>\n"
            "`</code> [hidden](./target.md)`\n"
            "[also-hidden](./target.md)\n"
            "</code> [real](./target.md)\n"
            "[after](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:docs/code-span.md"]
        self.assertEqual([(4, "S1"), (5, "S1")], [
            (e["source"]["start_line"], e["evidence_level"]) for e in own
        ], own)

    def test_local_action_matching_outer_quotes_preserve_inner_quotes(self):
        self.write("actions/local/action.yml", "name: local\n")
        for outer, inner in (("'", '"'), ('"', "'")):
            with self.subTest(outer=outer):
                self.write(".github/workflows/quoted-local.yml", (
                    "jobs:\n  build:\n    steps:\n"
                    "      - uses: " + outer + "./actions/./local" + inner + outer + "\n"
                    "      - uses: " + outer + "./actions/./local" + outer + "\n"
                ))
                edges, _, _ = self.edges()
                own = [e for e in edges
                       if e["src"] == "file:.github/workflows/quoted-local.yml"]
                self.assertEqual([
                    (4, "module:./actions/./local" + inner, "S0"),
                    (5, "file:actions/local/action.yml", "S1"),
                ], [(e["source"]["start_line"], e["dst"], e["evidence_level"])
                    for e in own], own)

    def test_tagged_env_mapping_does_not_promote_nested_action_use(self):
        self.write("actions/local/action.yml", "name: local\n")
        for tag in ("!!map", "&envanchor !!map", "!<tag:yaml.org,2002:map>"):
            with self.subTest(tag=tag):
                self.write(".github/workflows/tagged-env.yml", (
                    "jobs:\n  build:\n    steps:\n"
                    "      - env: " + tag + "\n"
                    "          uses: ./actions/local\n"
                    "        run: echo ok\n"
                    "      - uses: ./actions/local\n"
                ))
                edges, _, _ = self.edges()
                own = [e for e in edges
                       if e["src"] == "file:.github/workflows/tagged-env.yml"]
                self.assertEqual([(7, "file:actions/local/action.yml", "S1")], [
                    (e["source"]["start_line"], e["dst"], e["evidence_level"])
                    for e in own
                ], own)

    def test_script_style_textarea_blocks_mask_fake_markdown_links(self):
        self.write("docs/target.md", "# target\n")
        for tag in ("script", "style", "textarea"):
            with self.subTest(tag=tag):
                self.write("docs/raw-html.md", (
                    "<" + tag + ">\n"
                    'const example = "[hidden](./target.md)";\n'
                    "</" + tag + "> [hidden](./target.md)\n"
                    "[real](./target.md)\n"
                ))
                edges, _, _ = self.edges()
                own = [e for e in edges if e["src"] == "file:docs/raw-html.md"]
                self.assertEqual([(4, "file:docs/target.md", "S1")], [
                    (e["source"]["start_line"], e["dst"], e["evidence_level"])
                    for e in own
                ], own)
        inline = config_reference_edges(
            "docs/raw-html.md",
            "[before](./target.md) <script>hidden</script> [after](./target.md)\n",
            {"file:docs/target.md"},
        )
        self.assertEqual([(1, "S1"), (1, "S1")], [
            (e["source"]["start_line"], e["evidence_level"]) for e in inline
        ], inline)

    def test_long_multiline_step_flow_map_preserves_single_direct_use(self):
        self.write("actions/local/action.yml", "name: local\n")
        self.write(".github/workflows/long-flow.yml", (
            "jobs:\n  build:\n    steps:\n      - {\n"
            + (" \n" * 40000)
            + "        uses: ./actions/local\n      }\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges
               if e["src"] == "file:.github/workflows/long-flow.yml"]
        self.assertEqual([(40005, "file:actions/local/action.yml", "S1")], [
            (e["source"]["start_line"], e["dst"], e["evidence_level"])
            for e in own
        ], own)

    def test_root_step_flow_mapping_only_proves_direct_uses(self):
        self.write("actions/local/action.yml", "name: local\n")
        cases = (
            ("{\n          uses: ./actions/local\n        }", [5]),
            ("{uses: ./actions/local}", [4]),
            ("{\n          env: {uses: ./actions/local},\n"
             + "          uses: ./actions/local\n        }", [6]),
            ("{\n          env: {\n            uses: ./actions/local\n          }\n        }", []),
            ("{with: {uses: ./actions/local}}", []),
            ("env: {\n          uses: ./actions/local\n        }", []),
            ("{\n          name: missing-comma\n          uses: ./actions/local\n        }", []),
            ("{uses: ./actions/local, uses: ./actions/local}", []),
            ("{\n          uses: ./actions/local\n        ]", []),
        )
        for step, expected in cases:
            with self.subTest(step=step):
                self.write(".github/workflows/root-flow.yml", (
                    "jobs:\n  build:\n    steps:\n      - " + step + "\n"
                ))
                edges, _, _ = self.edges()
                own = [e for e in edges
                       if e["src"] == "file:.github/workflows/root-flow.yml"]
                self.assertEqual([(line, "S1") for line in expected], [
                    (e["source"]["start_line"], e["evidence_level"]) for e in own
                ], own)

    def test_raw_pre_closing_line_cannot_reopen_container(self):
        self.write("docs/target.md", "# target\n")
        for closing in ("</pre>", "    </pre>", "`</pre>`"):
            with self.subTest(closing=closing):
                self.write("docs/pre-reopen.md", (
                    "<pre>\n" + closing + " `<pre>` [hidden](./target.md)\n"
                    "[real](./target.md)\n"
                    "<pre>\n[hidden](./target.md)\n</pre>\n"
                    "[after](./target.md)\n"
                ))
                edges, _, _ = self.edges()
                own = [e for e in edges if e["src"] == "file:docs/pre-reopen.md"]
                self.assertEqual([(3, "S1"), (7, "S1")], [
                    (e["source"]["start_line"], e["evidence_level"]) for e in own
                ], own)

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


    def test_yaml_step_flow_properties_keep_only_direct_uses(self):
        import yaml

        self.write("actions/local/action.yml", "name: local\n")
        for index, props in enumerate(("&step", "!!map &step", "&step !!map", "! &step")):
            with self.subTest(properties=props):
                source = (
                    "jobs:\n  build:\n    steps:\n"
                    f"      - {props} {{env: {{\n"
                    "          uses: ./actions/local\n"
                    "        }, run: echo ok}\n"
                    "      - uses: ./actions/local\n"
                )
                first, second = yaml.safe_load(source)["jobs"]["build"]["steps"]
                self.assertNotIn("uses", first)
                self.assertEqual("./actions/local", first["env"]["uses"])
                self.assertEqual("./actions/local", second["uses"])
                path = f".github/workflows/property-flow-{index}.yml"
                self.write(path, source)
                edges, _, _ = self.edges()
                own = [edge for edge in edges if edge["src"] == f"file:{path}"]
                self.assertEqual([(7, "file:actions/local/action.yml", "S1")], [
                    (edge["source"]["start_line"], edge["dst"], edge["evidence_level"])
                    for edge in own
                ], own)

                direct = (
                    "jobs:\n  build:\n    steps:\n"
                    f"      - {props} "
                    "{env: {uses: ./actions/local}, uses: ./actions/local}\n"
                )
                self.assertEqual(
                    "./actions/local",
                    yaml.safe_load(direct)["jobs"]["build"]["steps"][0]["uses"],
                )
                path = f".github/workflows/property-direct-{index}.yml"
                self.write(path, direct)
                edges, _, _ = self.edges()
                own = [edge for edge in edges if edge["src"] == f"file:{path}"]
                self.assertEqual([(4, "file:actions/local/action.yml", "S1")], [
                    (edge["source"]["start_line"], edge["dst"], edge["evidence_level"])
                    for edge in own
                ], own)

    def test_yaml_nonspecific_tag_does_not_expose_scalar_uses(self):
        import yaml

        self.write("actions/local/action.yml", "name: local\n")
        for index, props in enumerate(("!", "! &scalar", "&scalar !")):
            cases = (
                ("block", (
                    "jobs:\n  build:\n    steps:\n"
                    f"      - run: {props} |\n"
                    "          uses: ./actions/local\n"
                    "      - uses: ./actions/local\n"
                ), 6),
                ("quoted", (
                    "jobs:\n  build:\n    steps:\n"
                    f'      - name: {props} "first\n'
                    "          uses: ./actions/local\n"
                    '          last"\n'
                    "        uses: ./actions/local\n"
                ), 7),
            )
            for label, source, expected_line in cases:
                with self.subTest(properties=props, scalar=label):
                    first = yaml.safe_load(source)["jobs"]["build"]["steps"][0]
                    self.assertIn("uses: ./actions/local", first.get("run", first.get("name")))
                    path = f".github/workflows/nonspecific-{index}-{label}.yml"
                    self.write(path, source)
                    edges, _, _ = self.edges()
                    own = [edge for edge in edges if edge["src"] == f"file:{path}"]
                    self.assertEqual([(expected_line, "S1")], [
                        (edge["source"]["start_line"], edge["evidence_level"])
                        for edge in own
                    ], own)

    def test_markdown_tab_containers_with_space_continuations(self):
        self.write("docs/target.md", "# target\n")
        cases = (
            ("quote", ">\t~~~md\n> [example](./target.md)\n> ~~~\n"
             "[real](./target.md)\n", 4),
            ("list", "-\t~~~md\n    [example](./target.md)\n    ~~~\n\n"
             "[real](./target.md)\n", 5),
        )
        for label, source, expected_line in cases:
            with self.subTest(container=label):
                path = f"docs/tab-container-{label}.md"
                self.write(path, source)
                edges, _, _ = self.edges()
                own = [edge for edge in edges if edge["src"] == f"file:{path}"]
                self.assertEqual([(expected_line, "S1")], [
                    (edge["source"]["start_line"], edge["evidence_level"])
                    for edge in own
                ], own)

    def test_split_raw_html_start_tags_hide_literal_links(self):
        self.write("docs/target.md", "# target\n")
        for tag in ("pre", "script", "style", "textarea"):
            with self.subTest(tag=tag):
                path = f"docs/split-raw-{tag}.md"
                self.write(path, (
                    f"<{tag}\n"
                    ' class="example">\n'
                    "[example](./target.md)\n"
                    f"</{tag}> [still-literal](./target.md)\n"
                    "[real](./target.md)\n"
                ))
                edges, _, _ = self.edges()
                own = [edge for edge in edges if edge["src"] == f"file:{path}"]
                self.assertEqual([(5, "file:docs/target.md", "S1")], [
                    (edge["source"]["start_line"], edge["dst"], edge["evidence_level"])
                    for edge in own
                ], own)

    def test_raw_html_block_tags_end_at_blank_line(self):
        self.write("docs/target.md", "# target\n")
        for tag in ("div", "details", "section", "table"):
            with self.subTest(tag=tag):
                path = f"docs/raw-block-{tag}.md"
                self.write(path, (
                    f"<{tag}>\n"
                    "[example](./target.md)\n"
                    f"</{tag}>\n"
                    "[still-literal](./target.md)\n\n"
                    "[real](./target.md)\n"
                ))
                edges, _, _ = self.edges()
                own = [edge for edge in edges if edge["src"] == f"file:{path}"]
                self.assertEqual([(6, "file:docs/target.md", "S1")], [
                    (edge["source"]["start_line"], edge["dst"], edge["evidence_level"])
                    for edge in own
                ], own)

    def test_raw_html_blockquote_blank_line_ends_block(self):
        self.write("docs/target.md", "# target\n")
        self.write("docs/raw-quote.md", (
            "> <div>\n"
            "> [example](./target.md)\n"
            "> </div>\n"
            ">\n"
            "> [real](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges if edge["src"] == "file:docs/raw-quote.md"]
        self.assertEqual([(5, "S1")], [
            (edge["source"]["start_line"], edge["evidence_level"]) for edge in own
        ], own)

    def test_yaml_flow_scalar_properties_keep_literal_braces_quoted(self):
        import yaml

        self.write("actions/local/action.yml", "name: local\n")
        variants = (("!", '"'), ("!!str", '"'), ("!!str &name", "'"), ("&name !!str", "'"))
        for index, (properties, quote) in enumerate(variants):
            for direct in (False, True):
                with self.subTest(properties=properties, quote=quote, direct=direct):
                    suffix = (
                        f"          last{quote}, uses: ./actions/local}}\n"
                        if direct else
                        f"          last{quote}}}\n      - uses: ./actions/local\n"
                    )
                    source = (
                        "jobs:\n  build:\n    steps:\n"
                        f"      - &step {{name: {properties} {quote}first }}\n"
                        "          uses: ./actions/local\n"
                        + suffix
                    )
                    steps = yaml.safe_load(source)["jobs"]["build"]["steps"]
                    self.assertIn("uses: ./actions/local", steps[0]["name"])
                    self.assertEqual("./actions/local", steps[0 if direct else 1]["uses"])
                    path = f".github/workflows/flow-property-quote-{index}-{direct}.yml"
                    self.write(path, source)
                    edges, _, _ = self.edges()
                    own = [edge for edge in edges if edge["src"] == f"file:{path}"]
                    self.assertEqual([(6 if direct else 7, "file:actions/local/action.yml", "S1")], [
                        (edge["source"]["start_line"], edge["dst"], edge["evidence_level"])
                        for edge in own
                    ], own)




    def test_markdown_html_attributes_never_become_literal_links(self):
        known = {"file:target.md", "file:before.md", "file:inside.md", "file:after.md"}
        tags = (
            '<a title="[fake](./target.md)">',
            "<a title='[fake](./target.md)'>",
            '<a title="> [fake](./target.md)">',
            '<a\n title="[fake](./target.md)">',
            '<a title="[fake](./target.md)\nmore">',
            '<custom-tag data_ref=[fake](./target.md) disabled>',
            '<a title="<code> [fake](./target.md)">',
            '<a title="<!-- [fake](./target.md)">',
        )
        for tag in tags:
            with self.subTest(tag=tag):
                source = (
                    "[before](./before.md) " + tag
                    + "[inside](./inside.md)</a> [after](./after.md)"
                )
                edges = config_reference_edges("README.md", source, known)
                self.assertEqual(
                    ["file:before.md", "file:inside.md", "file:after.md"],
                    [edge["dst"] for edge in edges], edges,
                )

    def test_markdown_html_and_backticks_use_first_token_boundary(self):
        known = {"file:target.md", "file:real.md"}
        sources = (
            r'Some \<a title="`[fake](./target.md)`"> [real](./real.md)',
            'Some <a title="` [fake](./target.md)">text</a> [real](./real.md) `tail',
            '`<a title="[fake](./target.md)">` [real](./real.md)',
            'Some <a title="` > [fake](./target.md) `">text</a> [real](./real.md)',
        )
        for source in sources:
            with self.subTest(source=source):
                edges = config_reference_edges("README.md", source, known)
                self.assertEqual(["file:real.md"], [edge["dst"] for edge in edges], edges)

    def test_markdown_invalid_or_escaped_html_keeps_literal_prose(self):
        known = {"file:real.md"}
        sources = (
            r'Some \<a title="[real](./real.md)">',
            'Some <a invalid*="[real](./real.md)">',
            'Some <a title="[real](./real.md)',
            'Some </a title="[real](./real.md)">',
            'Some <33 title="[real](./real.md)">',
        )
        for source in sources:
            with self.subTest(source=source):
                edges = config_reference_edges("README.md", source, known)
                self.assertEqual(["file:real.md"], [edge["dst"] for edge in edges], edges)

    def test_markdown_other_raw_html_tokens_hide_only_their_contents(self):
        known = {"file:target.md", "file:real.md"}
        tokens = (
            '<?process [fake](./target.md) ?>',
            '<![CDATA[[fake](./target.md)]]>',
            '<!DOCTYPE [fake](./target.md)>',
        )
        for token in tokens:
            with self.subTest(token=token):
                source = "Some " + token + " [real](./real.md)"
                edges = config_reference_edges("README.md", source, known)
                self.assertEqual(["file:real.md"], [edge["dst"] for edge in edges], edges)

    def test_markdown_comments_preserve_all_splitline_boundaries(self):
        known = {"file:real.md"}
        for boundary in ("\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"):
            with self.subTest(boundary=repr(boundary)):
                source = "<!-- a" + boundary + "b -->\n[real](./real.md)\n"
                edges = config_reference_edges("README.md", source, known)
                self.assertEqual(
                    [("file:real.md", 3)],
                    [(edge["dst"], edge["source"]["start_line"]) for edge in edges],
                    edges,
                )

    def test_masked_inline_html_does_not_split_backtick_paragraph(self):
        known = {"file:target.md", "file:real.md"}
        for middle in ("<code>x</code>", "<code>\nx\n</code>"):
            with self.subTest(middle=middle):
                source = "`start\n" + middle + "\n[fake](./target.md) end`\n\n[real](./real.md)"
                edges = config_reference_edges("README.md", source, known)
                self.assertEqual(["file:real.md"], [edge["dst"] for edge in edges], edges)

    def test_github_actions_plain_scalar_uses_requires_mapping_separator(self):
        import yaml

        known = {"file:actions/local/action.yml"}
        sources = (
            "jobs:\n  build:\n    steps:\n      - name: Build\n          uses:./actions/local\n",
            "jobs:\n  build:\n    steps:\n      - uses:./actions/local\n",
        )
        for source in sources:
            with self.subTest(source=source):
                parsed = yaml.safe_load(source)
                step = parsed["jobs"]["build"]["steps"][0]
                self.assertTrue(isinstance(step, str) or "uses" not in step)
                edges = config_reference_edges(".github/workflows/example.yml", source, known)
                self.assertEqual([], edges)
        positive = "jobs:\n  build:\n    steps:\n      - uses: ./actions/local\n"
        edges = config_reference_edges(".github/workflows/example.yml", positive, known)
        self.assertEqual([("file:actions/local/action.yml", "S1")], [
            (edge["dst"], edge["evidence_level"]) for edge in edges
        ])



    def test_yaml_sequence_scalars_and_non_identifier_keys_are_not_uses(self):
        import yaml

        known = {"file:actions/local/action.yml", "file:actions/real/action.yml"}
        scalar_steps = (
            "      - |\n        uses: ./actions/local\n",
            "      - >-\n        uses: ./actions/local\n",
            "      - &script |\n        uses: ./actions/local\n",
            "      - !!str |\n        uses: ./actions/local\n",
            '      - "my step": |\n          uses: ./actions/local\n',
            "      - 'my step': >-\n          uses: ./actions/local\n",
        )
        for steps in scalar_steps:
            with self.subTest(steps=steps):
                source = "jobs:\n  build:\n    steps:\n" + steps + "      - uses: ./actions/real\n"
                parsed = yaml.safe_load(source)
                self.assertEqual("./actions/real", parsed["jobs"]["build"]["steps"][-1]["uses"])
                edges = config_reference_edges(".github/workflows/scalars.yml", source, known)
                self.assertEqual(
                    [("file:actions/real/action.yml", "S1")],
                    [(edge["dst"], edge["evidence_level"]) for edge in edges], edges,
                )

    def test_yaml_hash_without_separator_remains_in_literal_uses_path(self):
        known = {"file:actions/local/action.yml", "file:.github/workflows/reusable.yml"}
        source = (
            "jobs:\n"
            "  reusable:\n"
            "    uses: ./.github/workflows/reusable.yml#v1\n"
            "  build:\n"
            "    steps:\n"
            "      - uses: ./actions/local#v1\n"
        )
        edges = config_reference_edges(".github/workflows/hash.yml", source, known)
        self.assertEqual(2, len(edges), edges)
        self.assertTrue(all(edge["evidence_level"] == "S0" for edge in edges), edges)
        self.assertTrue(all("#v1" in edge["dst"] for edge in edges), edges)

    def test_markdown_html_attributes_cannot_mask_fence_boundaries(self):
        known = {"file:target.md", "file:real.md"}
        sources = (
            '<a title="\n~~~\n">\n[fake](./target.md)\n~~~\n',
            '~~~\n<a title="\n~~~\n">\n~~~\n[fake](./target.md)\n~~~\n',
        )
        for source in sources:
            with self.subTest(source=source):
                edges = config_reference_edges("README.md", source + "\n[real](./real.md)\n", known)
                self.assertEqual(["file:real.md"], [edge["dst"] for edge in edges], edges)

    def test_markdown_complete_standalone_tags_start_html_blocks(self):
        known = {"file:target.md", "file:real.md"}
        for tag in ('<img src="logo.png">', "<span>", "<br>", '<a href="x">', "</a>"):
            with self.subTest(tag=tag):
                source = tag + "\n[fake](./target.md)\n\n[real](./real.md)\n"
                edges = config_reference_edges("README.md", source, known)
                self.assertEqual(["file:real.md"], [edge["dst"] for edge in edges], edges)
        source = "Prose\n<span>\n[real](./real.md)\n"
        edges = config_reference_edges("README.md", source, known)
        self.assertEqual(["file:real.md"], [edge["dst"] for edge in edges], edges)

    def test_markdown_escape_consumes_only_first_backtick_of_run(self):
        known = {"file:target.md", "file:real.md"}
        for width in range(2, 6):
            with self.subTest(width=width):
                source = (
                    "\\" + chr(96) * width + "[fake](./target.md)"
                    + chr(96) * (width - 1) + "\n\n[real](./real.md)"
                )
                edges = config_reference_edges("README.md", source, known)
                self.assertEqual(["file:real.md"], [edge["dst"] for edge in edges], edges)



    def test_yaml_invalid_and_ambiguous_documents_have_explicit_coverage_gaps(self):
        cases = {
            "invalid_yaml": "jobs:\n  build:\n    steps:\n      - run: echo uses: ./actions/local\n",
            "yaml_alias_provenance_unavailable": (
                "anchor: &step {uses: ./actions/local}\n"
                "jobs: {build: {steps: [*step]}}\n"
            ),
            "yaml_duplicate_or_merge_key": (
                "jobs: {build: {steps: [{uses: ./actions/local, uses: ./actions/other}]}}\n"
            ),
            "yaml_unsupported_tag": (
                "jobs: !custom {build: {steps: [{uses: ./actions/local}]}}\n"
            ),
        }
        self.write("actions/local/action.yml", "name: local\n")
        for code, source in cases.items():
            with self.subTest(code=code):
                self.write(".github/workflows/uncertain.yml", source)
                edges, coverage, _ = self.edges()
                self.assertFalse(any(
                    edge["src"] == "file:.github/workflows/uncertain.yml"
                    for edge in edges
                ), edges)
                self.assertEqual(1, coverage["skipped"].get(code), coverage)

    def test_yaml_composed_tags_must_match_node_kinds(self):
        self.write("actions/local/action.yml", "name: local\n")
        for source in (
            "jobs: !!str {build: {steps: [{uses: ./actions/local}]}}\n",
            "jobs: {build: {steps: !!map [{uses: ./actions/local}]}}\n",
            "jobs: {build: {steps: [{uses: !!map ./actions/local}]}}\n",
        ):
            with self.subTest(source=source):
                self.write(".github/workflows/tag-kind.yml", source)
                edges, coverage, _ = self.edges()
                self.assertFalse(any(
                    edge["src"] == "file:.github/workflows/tag-kind.yml"
                    for edge in edges
                ), edges)
                self.assertEqual(1, coverage["skipped"].get("yaml_unsupported_tag"), coverage)

    def test_yaml_multiline_use_evidence_includes_value(self):
        self.write("actions/local/action.yml", "name: local\n")
        for opener in ("uses:", "uses: >-", 'uses: "\\'):
            with self.subTest(opener=opener):
                suffix = '"' if opener.startswith('uses: "') else ""
                source = (
                    "jobs:\n  build:\n    steps:\n"
                    "      - " + opener + "\n"
                    "          ./actions/local" + suffix + "\n"
                )
                self.write(".github/workflows/multiline-use.yml", source)
                edges, _, _ = self.edges()
                own = [e for e in edges
                       if e["src"] == "file:.github/workflows/multiline-use.yml"]
                self.assertEqual(1, len(own), own)
                self.assertEqual("S1", own[0]["evidence_level"])
                self.assertEqual({
                    "path": ".github/workflows/multiline-use.yml",
                    "start_line": 4, "end_line": 5,
                    "range_ref": "file:.github/workflows/multiline-use.yml#L4-L5",
                }, own[0]["source"])

    def test_markdown_trimmed_parent_does_not_fabricate_precise_source_line(self):
        for leading in ("\u2028", "\f", "\v"):
            with self.subTest(leading=repr(leading)):
                source = leading + "\n[a](./target.md)\n[a](./target.md)\n"
                edges = config_reference_edges("README.md", source, {"file:target.md"})
                self.assertTrue(edges)
                # A native parent whose rows were stripped cannot prove a
                # precise per-token line; preserve its true enclosing range.
                for edge in edges:
                    self.assertEqual((1, 4), (
                        edge["source"]["start_line"], edge["source"]["end_line"],
                    ), edges)

    def test_markdown_nonvoid_html_slash_keeps_code_container_open(self):
        for tag in ("code", "pre", "script", "style", "textarea"):
            with self.subTest(tag=tag):
                source = (
                    f"Some <{tag}/>[fake](./target.md)</{tag}> "
                    "[real](./real.md)\n"
                )
                edges = config_reference_edges(
                    "README.md", source, {"file:target.md", "file:real.md"},
                )
                self.assertEqual(["file:real.md"], [edge["dst"] for edge in edges], edges)

    def test_markdown_block_comments_and_noninterrupting_ordered_markers(self):
        comment = "<!-- \u0060 inside --> [raw](./target.md)\n\n[real](./real.md)\n"
        edges = config_reference_edges(
            "README.md", comment, {"file:target.md", "file:real.md"},
        )
        self.assertEqual(["file:real.md"], [edge["dst"] for edge in edges], edges)
        source = (
            "paragraph\n10000. ~~~md\n"
            "       [real](./target.md)\n       ~~~\n"
        )
        edges = config_reference_edges("README.md", source, {"file:target.md"})
        self.assertEqual([3], [edge["source"]["start_line"] for edge in edges], edges)

    def test_markdown_native_links_images_references_and_unicode_source_ranges(self):
        known = {"file:target.md", "file:other.md", "file:image.svg", "file:real.md"}
        cases = (
            ("prose [real](./target.md)\n", [("file:target.md", 1)]),
            ("![alt [fake](./other.md)](./image.svg)\n", [("file:image.svg", 1)]),
            ("[ref][name]\n\n[name]: ./target.md\n", []),
            ("before\f[real](./target.md)\n", [("file:target.md", 2)]),
            ("before\u2028[real](./target.md)\n", [("file:target.md", 2)]),
            ('before <a title="x\f[fake](./other.md)">x</a> [real](./target.md)\n',
             [("file:target.md", 2)]),
            ("<code>[hidden](./target.md)\n\n[hidden](./target.md)</code>\n"
             "[real](./real.md)\n", [("file:real.md", 4)]),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                edges = config_reference_edges("README.md", source, known)
                self.assertEqual(expected, [
                    (edge["dst"], edge["source"]["start_line"]) for edge in edges
                ], edges)


    def test_workflow_named_action_yaml_keeps_jobs_context(self):
        self.write("actions/local/action.yml", "name: local\n")
        self.write(".github/workflows/reusable.yml", "on: workflow_call\n")
        source = (
            "jobs:\n"
            "  build:\n"
            "    steps:\n"
            "      - uses: ./actions/local\n"
            "  reusable:\n"
            "    uses: ./.github/workflows/reusable.yml\n"
        )
        for name in ("action.yml", "action.yaml"):
            self.write(".github/workflows/" + name, source)
        self.write("actions/composite/action.yml", (
            "runs:\n  using: composite\n  steps:\n"
            "    - uses: ./actions/local\n"
        ))
        edges, _, _ = self.edges()
        for name in ("action.yml", "action.yaml"):
            with self.subTest(name=name):
                own = [
                    edge for edge in edges
                    if edge["src"] == "file:.github/workflows/" + name
                ]
                self.assertEqual([
                    ("file:actions/local/action.yml", 4, "S1"),
                    ("file:.github/workflows/reusable.yml", 6, "S1"),
                ], [
                    (edge["dst"], edge["source"]["start_line"], edge["evidence_level"])
                    for edge in own
                ])
        composite = [
            edge for edge in edges
            if edge["src"] == "file:actions/composite/action.yml"
        ]
        self.assertEqual(
            [("file:actions/local/action.yml", "S1")],
            [(edge["dst"], edge["evidence_level"]) for edge in composite],
        )


if __name__ == "__main__":
    unittest.main()
