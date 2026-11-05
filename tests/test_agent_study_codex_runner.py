"""Contract tests for the external real-provider adapter; no synthetic quality claim."""
import importlib.util
import json
import hashlib
import stat
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "agent_study_codex_runner.py"
spec = importlib.util.spec_from_file_location("agent_study_codex_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)


def event(kind, item=None, usage=None):
    payload = {"type": kind}
    if item is not None:
        payload["item"] = item
    if usage is not None:
        payload["usage"] = usage
    return payload


class CodexStudyRunnerTest(unittest.TestCase):
    def test_tool_inventory_has_no_mutating_snapshot_create(self):
        self.assertNotIn("repoground_snapshot_create", runner.TOOL_NAMES["repoground"])
        self.assertEqual(len(runner.MCP_TOOLS), len(set(runner.MCP_TOOLS)))
        self.assertEqual(set(runner.TOOL_NAMES), {"git", "file", "repoground"})

    def test_provider_usage_only_from_terminal_provider_event(self):
        usage = {"input_tokens": 120, "output_tokens": 17, "cached_input_tokens": 80}
        events = [(event("turn.completed", usage=usage), 3)]
        self.assertEqual(runner._usage(events), {
            "source": "provider_reported", "input_tokens": 120,
            "output_tokens": 17, "cached_input_tokens": 80,
        })
        self.assertIsNone(runner._usage([]))
        self.assertIsNone(runner._usage([(event("turn.completed", usage={
            "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 11,
        }), 2)]))

    def test_tool_duration_measured_from_start_end(self):
        started = {"id": "tool-7", "type": "command_execution",
                   "command": "git -C repos/repoground rev-parse HEAD",
                   "status": "in_progress"}
        finished = {**started, "status": "completed",
                    "exit_code": 0, "aggregated_output": "0fe8\n"}
        calls, answer = runner._tool_receipts([
            (event("item.started", started), 1.0),
            (event("item.completed", finished), 1.165),
        ], {})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "codex_git_command")
        self.assertEqual(calls[0]["duration_ms"], 165)
        self.assertEqual(calls[0]["output_bytes"], 5)
        self.assertEqual(answer, "")

    def test_unpaired_tool_event_is_not_given_fake_zero_latency(self):
        item = {"id": "t", "type": "command_execution", "command": "rg foo", "exit_code": 0}
        with self.assertRaisesRegex(ValueError, "unmeasured"):
            runner._tool_receipts([(event("item.completed", item), 2)], {})

    def test_successful_mcp_requires_observed_available(self):
        evidence = {"repo": "repoground", "source_commit": "a" * 40,
                    "generator_commit": "b" * 40, "manifest_sha256": "c" * 64,
                    "observed_status": "available", "freshness": "pinned_exact"}
        item = {"id": "m1", "type": "mcp_tool_call", "server": "study_repoground",
                "tool": "query_existing_index", "arguments": {"query": "foo"},
                "result": {"structured_content": {"status": "available"}},
                "error": None, "status": "completed"}
        calls, _ = runner._tool_receipts([
            (event("item.started", item), 1),
            (event("item.completed", item), 1.1),
        ], {"repoground": evidence})
        self.assertEqual(calls[0]["status"], "success")
        self.assertEqual(calls[0]["repoground_evidence"], evidence)
        absent = {**item, "result": {"structured_content": {"status": "unavailable"}}}
        calls, _ = runner._tool_receipts([
            (event("item.started", absent), 1),
            (event("item.completed", absent), 1.1),
        ], {"repoground": evidence})
        self.assertEqual(calls[0]["status"], "failed")
        self.assertNotIn("repoground_evidence", calls[0])

    def test_historical_citation_requires_explicit_source_bound_revision(self):
        pinned = {"heim-pc": {"commit": "a" * 40}}
        item = {
            "repo": "heim-pc", "path": "flake.lock", "commit": "b" * 40,
            "start_line": 1, "end_line": 20,
        }
        self.assertFalse(runner._valid_answer_citation(item, pinned))
        self.assertTrue(runner._valid_answer_citation(
            item, pinned, {"heim-pc": ["b" * 40]}
        ))
        self.assertFalse(runner._valid_answer_citation(
            item, pinned, {"heim-pc": ["c" * 40]}
        ))
        self.assertFalse(runner._valid_answer_citation(
            item, pinned, {"nixer": ["b" * 40]}
        ))

    def test_flake_relation_tool_requires_exact_manifest_commit_and_digest(self):
        self.assertIn("get_flake_relation_evidence", runner.MCP_TOOLS)
        expected = {"heim-pc": {
            "repo": "heim-pc", "source_commit": "a" * 40,
            "generator_commit": "b" * 40, "manifest_sha256": "c" * 64,
            "observed_status": "available", "freshness": "pinned_exact",
        }}
        payload = {
            "pack_sha256": "d" * 64,
            "source_commit": "a" * 40,
            "manifest_sha256": "c" * 64,
            "evidence": {
                "status": "ok", "relations": [{"relation_type": "flake_pinned_input"}],
                "gaps": [],
            },
        }
        event = {
            "id": "m-s4", "type": "mcp_tool_call",
            "server": "study_heim_pc", "tool": "get_flake_relation_evidence",
            "arguments": {
                "expected_repo": "heimgewebe/heim-pc", "expected_commit": "a" * 40,
            },
            "result": {"structured_content": payload},
            "error": None, "status": "completed",
        }
        success = runner._mcp_tool_receipt(event, 1, 12, expected)
        self.assertEqual(success["status"], "success")
        self.assertEqual(success["repoground_evidence"], expected["heim-pc"])
        for mutated in (
            {"source_commit": "e" * 40},
            {"manifest_sha256": "f" * 64},
            {"pack_sha256": "not-a-sha"},
            {"evidence": {"status": "unknown", "relations": [], "gaps": ["missing"]}},
        ):
            bad = {**payload, **mutated}
            response = {**event, "result": {"structured_content": bad}}
            proof = runner._mcp_tool_receipt(response, 1, 12, expected)
            self.assertEqual(proof["status"], "failed")
            self.assertNotIn("repoground_evidence", proof)

    def test_flake_relation_tool_allows_gaps_without_inventing_missing_relations(self):
        payload = {
            "pack_sha256": "d" * 64,
            "source_commit": "a" * 40,
            "manifest_sha256": "c" * 64,
            "evidence": {
                "status": "partial", "relations": [],
                "gaps": ["inner_flake_input_unverified:nixer"],
            },
        }
        self.assertTrue(
            runner._mcp_evidence_available("get_flake_relation_evidence", payload)
        )
        self.assertFalse(runner._mcp_evidence_available(
            "get_flake_relation_evidence",
            {**payload, "evidence": {"status": "ok", "gaps": []}}
        ))

    def test_builtin_empty_codex_discovery_is_not_treatment(self):
        item = {"id": "m1", "type": "mcp_tool_call", "server": "codex",
                "tool": "list_mcp_resources", "arguments": {},
                "result": {"structured_content": {"resources": []}},
                "status": "completed"}
        self.assertTrue(runner._builtin_empty_mcp(item))
        calls, _ = runner._tool_receipts([
            (event("item.started", item), 1),
            (event("item.completed", item), 1.1),
        ], {})
        self.assertEqual(calls, [])
        invalid = {**item, "result": {"structured_content": {"resources": ["foreign"]}}}
        self.assertFalse(runner._builtin_empty_mcp(invalid))

    def test_malformed_answer_not_cast_into_success(self):
        fallback, ok = runner._answer("not JSON", {"repoground": {"commit": "a" * 40}})
        self.assertFalse(ok)
        self.assertEqual(fallback["outcome"], "unavailable")
        self.assertEqual(fallback["reported_paths"], [])
        self.assertFalse(fallback["asserted_sufficient_evidence"])

    def test_real_answer_explanation_is_mandatory_and_bounded(self):
        import json
        schema = runner._output_schema()
        self.assertIn("explanation", schema["required"])
        self.assertEqual(schema["properties"]["explanation"], {"type": "string"})
        self.assertIn("Ergänze explanation", runner._prompt({
            "condition": "git_only", "question": "Where is function Foo defined?",
        }))
        repositories = {"repoground": {"commit": "a" * 40}}
        answer = {
            "outcome": "abstain", "reported_paths": [], "citations": [],
            "asserted_sufficient_evidence": False,
            "explanation": "Die eingefrorene Revision enthält keinen belegbaren Treffer.",
        }
        parsed, valid = runner._answer(json.dumps(answer), repositories)
        self.assertTrue(valid)
        self.assertEqual(parsed["explanation"], answer["explanation"])
        for text in (None, "kurz", "", "x" * 8001, "Eine längere Erklärung mit echtem NUL\x00 im Modelltext."):
            broken = {**answer}
            if text is None:
                del broken["explanation"]
            else:
                broken["explanation"] = text
            fallback, valid = runner._answer(json.dumps(broken), repositories)
            self.assertFalse(valid)
            self.assertEqual(fallback["explanation"], "")
        self.assertEqual(runner.AGENT_VERSION, "codex-study-prompt-v3")

    def test_mcp_success_depends_on_specific_tool_contract(self):
        available = {"status": "available"}
        self.assertTrue(runner._mcp_evidence_available("bundle_discover", available))
        self.assertTrue(runner._mcp_evidence_available("find_symbol", available))
        self.assertTrue(runner._mcp_evidence_available("ask_context", {
            "status": "ok", "context_pack": {
                "availability": {"status": "available"},
            },
        }))
        self.assertFalse(runner._mcp_evidence_available("ask_context", {
            "status": "ok", "context_pack": {
                "availability": {"status": "unavailable"},
            },
        }))
        self.assertFalse(runner._mcp_evidence_available("ask_context", {"status": "ok"}))
        self.assertTrue(runner._mcp_evidence_available("grounding_verify", {"status": "pass"}))
        self.assertFalse(runner._mcp_evidence_available("grounding_verify", {"status": "fail"}))
        self.assertTrue(runner._mcp_evidence_available("live_freshness", {"status": "fresh"}))
        self.assertFalse(runner._mcp_evidence_available("live_freshness", {"status": "stale"}))
        self.assertFalse(runner._mcp_evidence_available("live_freshness", {"status": "unknown"}))
        self.assertFalse(runner._mcp_evidence_available("find_symbol", {"status": "invalid"}))

    def test_actual_mcp_response_status_and_iserror_affect_receipt(self):
        evidence = {
            "repo": "repoground", "source_commit": "a" * 40,
            "generator_commit": "b" * 40, "manifest_sha256": "c" * 64,
            "observed_status": "available", "freshness": "pinned_exact",
        }
        item = {
            "id": "m1", "type": "mcp_tool_call", "server": "study_repoground",
            "tool": "ask_context", "arguments": {"query": "where"},
            "result": {"structured_content": {
                "status": "ok", "context_pack": {
                    "availability": {"status": "available"},
                },
            }},
            "error": None, "status": "completed",
        }
        call = runner._mcp_tool_receipt(item, 1, 11, {"repoground": evidence})
        self.assertEqual(call["status"], "success")
        self.assertEqual(call["repoground_evidence"], evidence)
        item["result"]["isError"] = True
        call = runner._mcp_tool_receipt(item, 1, 11, {"repoground": evidence})
        self.assertEqual(call["status"], "failed")
        self.assertNotIn("repoground_evidence", call)

    def test_mcp_exposure_whitelists_only_frozen_tools(self):
        request = {
            "condition": "repoground_mandatory", "question": "Exact source question",
            "runner": {"model": "gpt-5.6-sol"},
            "repoground": {"repoground": {
                "manifest_path": "/fake/bundle/manifest.json",
            }},
        }
        config = {
            "codex_bin": "/fake/codex", "mcp_script": "/fake/mcp.py",
            "mcp_python": "/fake/python",
        }
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            argv = runner._codex_argv(
                request, config, workspace, {"repoground": workspace},
            )
        self.assertTrue(any(
            part.startswith("mcp_servers.study_repoground.enabled_tools=")
            and json.loads(part.partition("=")[2]) == list(runner.MCP_TOOLS)
            for part in argv
        ))
        self.assertNotIn("repoground_change_evidence_pack", runner.TOOL_NAMES["repoground"])
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            private_manifest = workspace / "pinned.bundle.manifest.json"
            argv = runner._codex_argv(
                request, config, workspace,
                {"repoground": workspace}, {"repoground": private_manifest},
            )
            self.assertTrue(any(str(private_manifest) in arg for arg in argv))
            self.assertFalse(any("/fake/bundle/manifest.json" in arg for arg in argv))


    def test_foreign_mcp_server_cannot_hide_as_repo_tool(self):
        call = {"id": "m2", "type": "mcp_tool_call",
                "server": "evil", "tool": "query_existing_index",
                "arguments": {}, "result": {"structured_content": {"status": "available"}},
                "error": None, "status": "completed"}
        evidence = {"repoground": {
            "repo": "repoground", "source_commit": "a" * 40,
            "generator_commit": "b" * 40, "manifest_sha256": "c" * 64,
            "observed_status": "available", "freshness": "pinned_exact",
        }}
        with self.assertRaisesRegex(ValueError, "unregistered"):
            runner._tool_receipts([
                (event("item.started", call), 1.0),
                (event("item.completed", call), 1.2),
            ], evidence)
        call["server"] = "study_repoground"
        call["tool"] = "snapshot_create"
        with self.assertRaisesRegex(ValueError, "unregistered"):
            runner._tool_receipts([
                (event("item.started", call), 1.0),
                (event("item.completed", call), 1.2),
            ], evidence)

    def test_invalid_model_path_is_failed_not_fabricated_success(self):
        repositories = {"repoground": {"commit": "a" * 40}}
        invalid = json.dumps({
            "outcome": "abstain",
            "reported_paths": [{"repo": "repoground", "path": "."}],
            "citations": [],
            "asserted_sufficient_evidence": False,
        })
        answer, parsed = runner._answer(invalid, repositories)
        self.assertFalse(parsed)
        self.assertEqual(answer, {
            "outcome": "unavailable", "reported_paths": [],
            "citations": [], "asserted_sufficient_evidence": False,
            "explanation": "",
        })
        valid = json.dumps({
            "outcome": "abstain", "reported_paths": [],
            "citations": [], "asserted_sufficient_evidence": False,
            "explanation": "Die eingefrorene Quelle reicht für diese Antwort nicht aus.",
        })
        answer, parsed = runner._answer(valid, repositories)
        self.assertTrue(parsed)
        self.assertEqual(answer["outcome"], "abstain")

    def test_broken_citation_revision_keeps_original_trace_not_quality(self):
        repositories = {"repoground": {"commit": "a" * 40}}
        response = json.dumps({
            "outcome": "answer", "reported_paths": [{"repo": "repoground", "path": "src/a.py"}],
            "citations": [{
                "repo": "repoground", "path": "src/a.py",
                "commit": "b" * 40, "start_line": 1, "end_line": 4,
            }],
            "asserted_sufficient_evidence": True,
            "explanation": "Die zitierte Revision gehört nicht zum eingefrorenen Quellstand.",
        })
        sanitized, parsed = runner._answer(response, repositories)
        self.assertFalse(parsed)
        self.assertFalse(sanitized["asserted_sufficient_evidence"])

    def test_prompt_lists_only_source_bound_repo_ids(self):
        request = {
            "condition": "git_only", "question": "Identify code",
            "repositories": {"repoground": {"commit": "a" * 40},
                             "grabowski": {"commit": "b" * 40}},
        }
        prompt = runner._prompt(request)
        self.assertIn("Zulässige Repo-Kürzel", prompt)
        self.assertIn("grabowski, repoground.", prompt)
        self.assertNotIn("RepoGround-Python", prompt)

    def test_each_arm_shares_exact_same_question_bytes(self):
        question = "Where is the concrete source definition of Foo?"
        bodies = [runner._prompt({"condition": arm, "question": question})
                  for arm in ("git_only", "repoground_mandatory", "repoground_selective")]
        self.assertTrue(all(body.split("AUFGABE (in allen drei Armen bytegleich):\n")[1] == question
                            for body in bodies))
        self.assertIn("null RepoGround-Aufrufe", bodies[2])

    def test_request_fails_if_runner_or_tool_identity_drifts(self):
        fingerprint = {"runner_version": "exact-runner", "tool_contract": "exact-contract"}
        req = {"kind": "repoground.agent_study_request", "version": "1.0",
               "request_id": "study-trial-a", "workspace_id": "workspace-abc",
               "condition": "git_only",
               "runner": {"provider": "openai-codex-cli", "model": "gpt-5.6-sol",
                          "sampling": {"model_reasoning_effort": "medium"},
                          "runner_version": "exact-runner"},
               "execution_context": {"agent_version": runner.AGENT_VERSION,
                                     "host_class": "heim-pc", "cache_policy": "controlled",
                                     "tool_contract": "exact-contract"},
               "repositories": {"repoground": {"commit": "a" * 40,
                                               "slug": "heimgewebe/repoground"}},
               "question": "Find me a code symbol", "repoground": None,
               "tools_allowed": sorted(runner.TOOL_NAMES["git"] + runner.TOOL_NAMES["file"]),
               "git_file_tool_names": sorted(runner.TOOL_NAMES["git"] + runner.TOOL_NAMES["file"]),
               "repoground_tool_names": [],
               "isolation": {"fresh_session": True, "fresh_workspace": True,
                             "no_prior_arm_transcripts": True, "disable_unlisted_plugins": True}}
        runner._validate_request(req, fingerprint)
        req["runner"]["runner_version"] = "forged-runner"
        with self.assertRaisesRegex(ValueError, "drift"):
            runner._validate_request(req, fingerprint)

    def test_nonempty_native_codex_resource_discovery_is_metadata_not_failed_treatment(self):
        for tool, collection in (
            ("list_mcp_resources", {"resources": [{"uri": "repoground://example"}]}),
            ("list_mcp_resource_templates", {
                "resourceTemplates": [{"uriTemplate": "repoground://source/{ref}"}],
            }),
        ):
            with self.subTest(tool=tool):
                item = {
                    "id": "resource", "type": "mcp_tool_call", "server": "codex",
                    "tool": tool, "arguments": {}, "status": "completed",
                    "result": {"structured_content": collection},
                }
                # B/C can inspect registered metadata, but discovery alone
                # is not a successful RepoGround retrieval.
                calls, answer = runner._tool_receipts([
                    (event("item.started", item), 1.0),
                    (event("item.completed", item), 1.2),
                ], {"repoground": {}})
                self.assertEqual(calls, [])
                self.assertEqual(answer, "")
                # Git-only must reject nonempty discovery: a hidden source
                # would invalidate its A/B/C isolation even without a read.
                with self.assertRaisesRegex(ValueError, "MCP discovery in git_only"):
                    runner._tool_receipts([
                        (event("item.started", item), 1.0),
                        (event("item.completed", item), 1.2),
                    ], {})
        empty = {**item, "tool": "list_mcp_resources", "result": {
            "structured_content": {"resources": []},
        }}
        calls, _ = runner._tool_receipts([
            (event("item.started", empty), 1.0),
            (event("item.completed", empty), 1.1),
        ], {})
        self.assertEqual(calls, [])
        unknown = {**item, "tool": "read_mcp_resource"}
        with self.assertRaisesRegex(ValueError, "unregistered"):
            runner._tool_receipts([
                (event("item.started", unknown), 1.0),
                (event("item.completed", unknown), 1.2),
            ], {})

    def test_pinned_manifest_survives_source_replacement_without_forged_health(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publisher = root / "published"
            publisher.mkdir()
            source = publisher / "test.bundle.manifest.json"
            raw = json.dumps({"links": {"post_emit_health_path": "health.json"}}).encode()
            source.write_bytes(raw)
            (publisher / "health.json").write_text(json.dumps({
                "status": "pass", "bundle_manifest_path": str(source),
            }))
            (publisher / "role.txt").write_text("original immutable content")
            bound = {
                "manifest_path": str(source),
                "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            }
            request = {"repoground": {"repoground": bound}}
            ws = root / "worktree"
            ws.mkdir()
            pinned = runner._pin_snapshot_manifests(request, ws)
            target = pinned["repoground"]
            self.assertEqual(target.read_bytes(), raw)
            self.assertNotEqual(source, target)
            self.assertEqual(json.loads((target.parent / "health.json").read_text())[
                "bundle_manifest_sha256"
            ], bound["manifest_sha256"])
            self.assertNotIn("bundle_manifest_sha256", json.loads(
                (publisher / "health.json").read_text()
            ))
            self.assertEqual((target.parent / "role.txt").read_text(), "original immutable content")
            source.write_bytes(b"substituted publication manifest")
            runner._assert_pinned_manifests(request, pinned)
            self.assertEqual(target.read_bytes(), raw)
            target.chmod(0o600)
            target.write_bytes(b"mutated private manifest")
            with self.assertRaisesRegex(ValueError, "private manifest changed"):
                runner._assert_pinned_manifests(request, pinned)

    def test_private_pin_preserves_declared_nested_roles(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publisher = root / "published"
            (publisher / "artifacts" / "docs").mkdir(parents=True)
            (publisher / "artifacts" / "docs" / "demo.md").write_text("nested source proof")
            source = publisher / "nested.bundle.manifest.json"
            raw = json.dumps({
                "links": {"post_emit_health_path": "health.json"},
                "artifacts": [{"path": "artifacts/docs/demo.md"}],
            }).encode()
            source.write_bytes(raw)
            (publisher / "health.json").write_text(json.dumps({
                "status": "pass", "bundle_manifest_path": str(source),
            }))
            work = root / "workspace"
            work.mkdir()
            copied = runner._pin_snapshot_manifests({"repoground": {
                "repoground": {
                    "manifest_path": str(source),
                    "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                },
            }}, work)["repoground"]
            self.assertEqual(
                (copied.parent / "artifacts" / "docs" / "demo.md").read_text(),
                "nested source proof",
            )

    def test_private_pin_never_hardlinks_published_bundle_files(self):
        import hashlib
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pub = root / "published"
            (pub / "nested").mkdir(parents=True)
            source = pub / "test.bundle.manifest.json"
            raw = json.dumps({
                "links": {"post_emit_health_path": "health.json"},
                "artifacts": [{"path": "nested/part.txt"}],
            }).encode()
            source.write_bytes(raw)
            (pub / "health.json").write_text(json.dumps({
                "status": "pass", "bundle_manifest_path": str(source),
            }))
            role = pub / "role.txt"
            role.write_bytes(b"preserve original bundle role bytes\x00\xfe")
            output_health = pub / "test.output_health.json"
            output_health.write_text('{"verdict":"pass"}')
            nested = pub / "nested" / "part.txt"
            nested.write_text("nested source proof")
            ws = root / "workspace"
            ws.mkdir()
            with patch.object(runner.os, "link", side_effect=AssertionError(
                "pinning must never alter published artifact link counts"
            )):
                copied = runner._pin_snapshot_manifests({"repoground": {
                    "repoground": {
                        "manifest_path": str(source),
                        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                    },
                }}, ws)["repoground"]
            for published in (role, output_health, nested):
                private = copied.parent / published.relative_to(pub)
                self.assertEqual(private.read_bytes(), published.read_bytes())
                self.assertEqual(published.stat().st_nlink, 1)
                self.assertEqual(private.stat().st_nlink, 1)
                self.assertNotEqual(
                    (private.stat().st_dev, private.stat().st_ino),
                    (published.stat().st_dev, published.stat().st_ino),
                )
                self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)
            (copied.parent / output_health.name).write_text('{"verdict":"changed"}')
            self.assertEqual(output_health.read_text(), '{"verdict":"pass"}')

    def test_nested_artifact_traversal_and_symlink_not_pinned(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pub = root / "published"
            pub.mkdir()
            (pub / "health.json").write_text(json.dumps({"status": "pass"}))
            source = pub / "a.bundle.manifest.json"
            ws = root / "workspace"
            ws.mkdir()
            for suffix, invalid in enumerate(("x/../secret", "x//bad", "/abs/no", "dir\\bad")):
                raw = json.dumps({"links": {"post_emit_health_path": "health.json"},
                                  "artifacts": [{"path": invalid}]}).encode()
                source.write_bytes(raw)
                request = {"repoground": {"repoground": {
                    "manifest_path": str(source),
                    "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                }}}
                work = ws / str(suffix)
                work.mkdir()
                with self.assertRaisesRegex(ValueError, "unsafe manifest"):
                    runner._pin_snapshot_manifests(request, work)
            (pub / "artifacts").symlink_to(root, target_is_directory=True)
            raw = json.dumps({"links": {"post_emit_health_path": "health.json"},
                              "artifacts": [{"path": "artifacts/demo.md"}]}).encode()
            source.write_bytes(raw)
            request = {"repoground": {"repoground": {
                "manifest_path": str(source),
                "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            }}}
            work = ws / "symlink"
            work.mkdir()
            with self.assertRaisesRegex(ValueError, "unsafe"):
                runner._pin_snapshot_manifests(request, work)

    def test_mcp_digest_changes_when_imported_module_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "merger" / "repoground" / "cli").mkdir(parents=True)
            (root / "merger" / "repoground" / "core").mkdir(parents=True)
            thin_launcher = root / "scripts" / "mcp_stdio.py"
            thin_launcher.write_text("from merger.repoground.cli import mcp_stdio\\n")
            transport = root / "merger" / "repoground" / "cli" / "mcp_stdio.py"
            tools = root / "merger" / "repoground" / "core" / "mcp_tools.py"
            transport.write_text("PROTOCOL = 1\\n")
            tools.write_text("STATUS = 'available'\\n")
            first, count = runner._mcp_implementation_digest(str(thin_launcher))
            self.assertEqual(count, 2)
            self.assertEqual(first, runner._mcp_implementation_digest(str(thin_launcher))[0])
            tools.write_text("STATUS = 'ok'\\n")
            second, new_count = runner._mcp_implementation_digest(str(thin_launcher))
            self.assertEqual(new_count, 2)
            self.assertNotEqual(first, second)
            self.assertEqual(thin_launcher.read_text(), "from merger.repoground.cli import mcp_stdio\\n")

    def test_malformed_jsonl_still_persists_complete_raw_bytes(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = "print('{not-json', flush=True)"
            raw_path = root / "malformed.jsonl"
            with self.assertRaises(ValueError):
                runner._capture(
                    [sys.executable, "-B", "-c", source],
                    root, root / "malformed.stderr", raw_path,
                )
            self.assertEqual(raw_path.read_bytes(), b"{not-json\n")
            self.assertEqual(stat.S_IMODE(raw_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((root / "malformed.stderr").stat().st_mode), 0o600)

    def test_timeout_retains_valid_event_and_incomplete_tail(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = (
                "import time,json; "
                "print(json.dumps({'type':'turn.started'}),flush=True); "
                "print('{\\\"type\\\":',end='',flush=True); time.sleep(3)"
            )
            trace_path = root / "timeout.jsonl"
            previous_timeout = runner.MODEL_TIMEOUT
            runner.MODEL_TIMEOUT = 0.13
            try:
                raw, events, code, timed_out, *_ = runner._capture(
                    [sys.executable, "-B", "-c", script],
                    root, root / "timeout.stderr", trace_path,
                )
            finally:
                runner.MODEL_TIMEOUT = previous_timeout
            self.assertTrue(timed_out)
            self.assertIn(b"turn.started", raw)
            self.assertTrue(raw.endswith(b'{"type":'))
            self.assertEqual(raw, trace_path.read_bytes())
            self.assertNotEqual(code, 0)
            self.assertEqual(events[0][0]["type"], "turn.started")

    def test_capture_records_real_time_with_streamed_tool_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            script = ("import json,time; "
                      "i={'id':'x','type':'command_execution','command':'rg foo',"
                      "'status':'in_progress'}; "
                      "print(json.dumps({'type':'item.started','item':i}),flush=True); "
                      "time.sleep(0.03); "
                      "i.update({'status':'completed','exit_code':0,'aggregated_output':'foo'}); "
                      "print(json.dumps({'type':'item.completed','item':i}),flush=True)")
            import sys
            raw, events, code, timed_out, start, end, duration = runner._capture(
                [sys.executable, "-B", "-c", script], path, path / "stderr.txt", path / "trace.jsonl",
            )
            calls, _ = runner._tool_receipts(events, {})
            self.assertEqual(code, 0)
            self.assertFalse(timed_out)
            self.assertGreater(duration, 20)
            self.assertGreaterEqual(calls[0]["duration_ms"], 20)
            self.assertIn(b"item.completed", raw)
            self.assertGreaterEqual(end, start)

    def test_source_intervention_v3_rejects_discovery_only_and_unproven_ranges(self):
        assert not runner._mandatory_source_intervention([
            {"sequence": 1, "name": "repoground_bundle_discover", "status": "success"},
        ])
        search = {"sequence": 1, "name": "repoground_ask_context", "status": "success"}
        source = {
            "sequence": 2, "name": "repoground_range_get",
            "status": "success", "source_content_sha256": "d" * 64,
        }
        assert runner._mandatory_source_intervention([search, source])
        assert not runner._mandatory_source_intervention([
            {**source, "sequence": 1}, {**search, "sequence": 2},
        ])
        assert not runner._mandatory_source_intervention([
            search, {**source, "source_content_sha256": "not-verified"}
        ])


    def test_sha_bound_range_get_receipt_requires_original_ref_and_actual_bytes(self):
        evidence = {
            "repo": "repoground", "source_commit": "a" * 40,
            "generator_commit": "b" * 40, "manifest_sha256": "c" * 64,
            "observed_status": "available", "freshness": "pinned_exact",
        }
        source_sha = hashlib.sha256(b"hello").hexdigest()
        ref = {"artifact_role": "canonical_md", "content_sha256": source_sha}
        payload = {"status": "available", "result": {
            "status": "available", "range": {
                "sha256": source_sha, "bytes": 5, "text": "hello",
            },
        }}
        call = {
            "id": "m", "type": "mcp_tool_call", "server": "study_repoground",
            "tool": "range_get", "arguments": {"range_ref": ref},
            "result": {"structured_content": payload},
            "status": "completed", "error": None,
        }
        proof = runner._mcp_tool_receipt(call, 1, 7, {"repoground": evidence})
        assert proof["status"] == "success"
        assert proof["source_content_sha256"] == source_sha
        assert proof["repoground_evidence"] == evidence
        for bad in (
            {**payload, "result": {**payload["result"], "range": {
                **payload["result"]["range"], "sha256": "e" * 64,
            }}},
            {**payload, "result": {**payload["result"], "range": {
                **payload["result"]["range"], "bytes": 4,
            }}},
            {**payload, "result": {**payload["result"], "range": {
                **payload["result"]["range"], "text": "other",
            }}},
        ):
            item = {**call, "result": {"structured_content": bad}}
            invalid = runner._mcp_tool_receipt(item, 1, 7, {"repoground": evidence})
            assert invalid["status"] == "failed"
            assert "source_content_sha256" not in invalid
        unbound = {**call, "arguments": {"range_ref": {**ref, "content_sha256": "f" * 64}}}
        assert runner._mcp_tool_receipt(unbound, 1, 7, {"repoground": evidence})["status"] == "failed"


    def test_v2_partial_range_read_uses_range_sha_not_entire_artifact(self):
        # The bundle artifact SHA and selected byte-range SHA are different.
        range_sha = hashlib.sha256(b"hello").hexdigest()
        whole_sha = hashlib.sha256(b"prefix-hello-suffix").hexdigest()
        self.assertNotEqual(range_sha, whole_sha)
        ref = {
            "artifact_role": "canonical_md", "range_ref_version": "2",
            "content_sha256": whole_sha, "range_content_sha256": range_sha,
        }
        payload = {"status": "available", "result": {"status": "available",
                   "range": {"sha256": range_sha, "text": "hello", "bytes": 5}}}
        evidence = {"repoground": {
            "repo": "repoground", "source_commit": "a" * 40,
            "generator_commit": "b" * 40, "manifest_sha256": "c" * 64,
            "observed_status": "available", "freshness": "pinned_exact",
        }}
        item = {"type": "mcp_tool_call", "server": "study_repoground",
                "tool": "range_get", "arguments": {"range_ref": ref},
                "result": {"structured_content": payload},
                "status": "completed", "error": None}
        proof = runner._mcp_tool_receipt(item, 1, 5, evidence)
        self.assertEqual(proof["status"], "success")
        self.assertEqual(proof["source_content_sha256"], range_sha)
        for broken_ref in (
            {**ref, "range_content_sha256": "d" * 64},
            {**ref, "range_ref_version": "3"},
            {**ref, "content_sha256": "bad"},
        ):
            with self.subTest(ref=broken_ref):
                invalid = runner._mcp_tool_receipt(
                    {**item, "arguments": {"range_ref": broken_ref}}, 1, 5, evidence,
                )
                self.assertEqual(invalid["status"], "failed")
        forged_content = {"status": "available", "result": {"status": "available",
                          "range": {"sha256": range_sha, "text": "other", "bytes": 5}}}
        invalid = runner._mcp_tool_receipt(
            {**item, "result": {"structured_content": forged_content}}, 1, 5, evidence,
        )
        self.assertEqual(invalid["status"], "failed")



    def test_mcp_resource_reads_verified_against_pinned_manifest_artifacts(self):
        # This is the actual Codex read_mcp_resource envelope; it is NOT one
        # of the 13 server-registered MCP tools.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stem = "heimgewebe__heim-pc__main--" + "a" * 40 + "-max-test"
            manifest_path = root / (stem + ".bundle.manifest.json")
            content = b'{"kind":"flake-proof","status":"partial"}\n'
            asset_name = stem + ".flake_relation_evidence.json"
            (root / asset_name).write_bytes(content)
            artifact_sha = hashlib.sha256(content).hexdigest()
            manifest = {"artifacts": [{
                "role": "flake_relation_evidence_json", "path": asset_name,
                "sha256": artifact_sha, "bytes": len(content),
            }]}
            manifest_bytes = (json.dumps(manifest, sort_keys=True) + "\n").encode()
            manifest_path.write_bytes(manifest_bytes)
            manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
            expected = {"heim-pc": {
                "repo": "heim-pc", "source_commit": "a" * 40,
                "generator_commit": "b" * 40, "manifest_sha256": manifest_sha,
                "observed_status": "available", "freshness": "pinned_exact",
                "_manifest_path": str(manifest_path),
            }}

            def item(uri, source_text, *, embedded_uri=None, server="study_heim_pc",
                     many=False):
                part = {"uri": embedded_uri or uri, "mimeType": "application/json",
                        "text": source_text}
                wrapper = {"server": server, "uri": uri,
                           "contents": [part, part] if many else [part]}
                return {"id": "t", "type": "mcp_tool_call",
                        "server": "study_heim_pc", "tool": "read_mcp_resource",
                        "status": "completed", "error": None,
                        "arguments": {"server": "study_heim_pc", "uri": uri},
                        "result": {"content": [
                            {"type": "text", "text": json.dumps(wrapper)},
                        ]}}

            prefix = "repoground://snapshot/" + stem
            uri = prefix + "/artifact/flake_relation_evidence_json"
            call = runner._mcp_tool_receipt(item(uri, content.decode()), 1, 5, expected)
            self.assertEqual(call["name"], "repoground_read_mcp_resource")
            self.assertEqual(call["status"], "success")
            self.assertEqual(call["resource_content_sha256"], artifact_sha)
            self.assertEqual(call["resource_role"], "flake_relation_evidence_json")
            self.assertEqual(call["repoground_evidence"]["manifest_sha256"], manifest_sha)
            self.assertNotIn("_manifest_path", call["repoground_evidence"])
            manifest_uri = prefix + "/manifest"
            manifest_call = runner._mcp_tool_receipt(
                item(manifest_uri, manifest_bytes.decode()), 2, 7, expected,
            )
            self.assertEqual(manifest_call["status"], "success")
            self.assertEqual(manifest_call["resource_content_sha256"], manifest_sha)
            bad_items = [
                item(uri, '{"kind":"forge"}'),
                item(uri, content.decode(), embedded_uri=prefix + "/manifest"),
                item(uri, content.decode(), server="study_grabowski"),
                item(uri, content.decode(), many=True),
                item(prefix + "/artifact/not_produced", content.decode()),
                item(prefix.replace("a" * 40, "c" * 40) +
                     "/artifact/flake_relation_evidence_json", content.decode()),
            ]
            for bad in bad_items:
                with self.subTest(resource=bad["arguments"]["uri"]):
                    proof = runner._mcp_tool_receipt(bad, 3, 5, expected)
                    self.assertEqual(proof["status"], "failed")
                    self.assertNotIn("resource_content_sha256", proof)
            with self.assertRaisesRegex(ValueError, "unregistered RepoGround MCP tool"):
                runner._mcp_tool_receipt({
                    **item(uri, content.decode()), "tool": "unregistered_write",
                }, 4, 5, expected)



    def test_private_manifest_survives_publication_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public = root / "publisher"
            private = root / "workspace"
            public.mkdir()
            private.mkdir()
            stem = "heimgewebe__heim-pc__main--" + "a" * 40 + "-max-test"
            name = stem + ".bundle.manifest.json"
            artifact_name = stem + ".flake_relation_evidence.json"
            body = b'{"kind":"flake-proof","status":"partial"}\n'
            digest = hashlib.sha256(body).hexdigest()
            doc = {"artifacts": [{"role": "flake_relation_evidence_json",
                                   "path": artifact_name, "sha256": digest,
                                   "bytes": len(body)}]}
            raw = (json.dumps(doc, sort_keys=True) + "\n").encode()
            for directory in (public, private):
                (directory / name).write_bytes(raw)
                (directory / artifact_name).write_bytes(body)
            evidence = {"heim-pc": {
                "repo": "heim-pc", "source_commit": "a" * 40,
                "generator_commit": "b" * 40,
                "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                "observed_status": "available", "freshness": "pinned_exact",
                "_manifest_path": str(public / name),
            }}
            bound = runner._private_manifest_evidence(
                evidence, {"heim-pc": private / name},
            )
            self.assertEqual(bound["heim-pc"]["_manifest_path"], str(private / name))
            self.assertEqual(evidence["heim-pc"]["_manifest_path"], str(public / name))
            (public / name).unlink()
            (public / artifact_name).unlink()
            uri = "repoground://snapshot/" + stem + "/artifact/flake_relation_evidence_json"
            item = {"type": "mcp_tool_call", "id": "resource",
                    "server": "study_heim_pc", "tool": "read_mcp_resource",
                    "status": "completed", "error": None,
                    "arguments": {"server": "study_heim_pc", "uri": uri},
                    "result": {"content": [{"type": "text", "text": json.dumps({
                        "server": "study_heim_pc", "uri": uri,
                        "contents": [{"uri": uri, "mimeType": "application/json",
                                      "text": body.decode()}],
                    })}]}}
            receipt = runner._mcp_tool_receipt(item, 1, 5, bound)
            self.assertEqual(receipt["status"], "success")
            self.assertEqual(receipt["resource_content_sha256"], digest)
            self.assertNotIn("_manifest_path", receipt["repoground_evidence"])
            with self.assertRaisesRegex(ValueError, "manifest inventory"):
                runner._private_manifest_evidence(evidence, {})



if __name__ == "__main__":
    unittest.main()
