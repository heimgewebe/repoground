"""Contract tests for the external real-provider adapter; no synthetic quality claim."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

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
        })
        valid = json.dumps({
            "outcome": "abstain", "reported_paths": [],
            "citations": [], "asserted_sufficient_evidence": False,
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
        })
        sanitized, parsed = runner._answer(response, repositories)
        self.assertFalse(parsed)
        self.assertFalse(sanitized["asserted_sufficient_evidence"])

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
                [sys.executable, "-B", "-c", script], path, path / "stderr.txt",
            )
            calls, _ = runner._tool_receipts(events, {})
            self.assertEqual(code, 0)
            self.assertFalse(timed_out)
            self.assertGreater(duration, 20)
            self.assertGreaterEqual(calls[0]["duration_ms"], 20)
            self.assertIn(b"item.completed", raw)
            self.assertGreaterEqual(end, start)


if __name__ == "__main__":
    unittest.main()