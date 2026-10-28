"""Bounded, source-specific cross-format relationship fixtures."""
from __future__ import annotations

import json
import time
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
            "10000. ~~~md\n"
            "       [example2](./target.md)\n"
            "       ~~~\n"
            "[after](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [e for e in edges if e["src"] == "file:docs/list-fences.md"]
        self.assertEqual([4, 8], [
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
        self.assertEqual([1, 1, 3, 4, 5],
                         [edge["source"]["start_line"] for edge in own], own)

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
            "<!--x-->" * 8000 + " [real](./target.md)\n",
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
            "<!-- ` inside comment --> [real](./target.md)\n"
        ))
        edges, _, _ = self.edges()
        own = [edge for edge in edges if edge["src"] == "file:docs/comment-backtick.md"]
        self.assertEqual([1], [edge["source"]["start_line"] for edge in own], own)

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