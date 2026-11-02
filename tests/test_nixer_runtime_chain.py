"""No-rebuild S3 provenance boundaries: content match does not imply activation."""
import hashlib
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from scripts.ops.measure_nixer_runtime_chain import (
    _canonical,
    _derivation_sources,
    _git_blob,
    _http_observation,
    _mcp_observation,
    _store_output_from_execstart,
    compare_source_contents,
)

STORE = "/nix/store/" + "1" * 32 + "-nixer-0.2.0"
SHA = "a" * 40


class NixerRuntimeChainTests(unittest.TestCase):
    def test_compare_source_bytes_diverging_declared_git(self):
        older = {"server.py": b"old", "evidence.py": b"same", "image_pin.py": b"same"}
        declared = {"server.py": b"new", "evidence.py": b"same", "image_pin.py": b"same"}
        compare = compare_source_contents(
            older,
            lambda commit, name: (older if commit == SHA else declared)[name],
            SHA,
            "b" * 40,
        )
        self.assertTrue(all(v["match_older"] for v in compare.values()))
        self.assertFalse(compare["server.py"]["match_declared"])
        self.assertTrue(compare["evidence.py"]["match_declared"])
        self.assertTrue(compare["image_pin.py"]["match_declared"])
        self.assertEqual(compare["server.py"]["store_sha256"], hashlib.sha256(b"old").hexdigest())

    def test_missing_git_source_is_unknown_not_content_mismatch(self):
        compare = compare_source_contents(
            {"server.py": b"stored"},
            lambda _commit, _name: (_ for _ in ()).throw(RuntimeError("missing Git object")),
            SHA, "b" * 40,
        )
        self.assertIsNone(compare["server.py"]["match_older"])
        self.assertIsNone(compare["server.py"]["match_declared"])
        self.assertEqual(compare["evidence.py"]["status"], "unavailable")

    def test_equal_contents_at_two_commits_are_not_unique_commit_identity(self):
        compare = compare_source_contents(
            {name: b"same" for name in ("server.py", "evidence.py", "image_pin.py")},
            lambda _commit, _name: b"same",
            SHA, "b" * 40,
        )
        self.assertTrue(all(v["match_older"] and v["match_declared"] for v in compare.values()))
        self.assertFalse(any("unique_git_commit" in v for v in compare.values()))

    def test_derivation_source_paths_require_known_store_filename(self):
        drv = {"env": {"installPhase": (
            "cp /nix/store/" + "a" * 32 + "-server.py \"$out/a\"\n"
            "cp /nix/store/" + "b" * 32 + "-evidence.py \"$out/b\"\n"
            "cp /nix/store/" + "c" * 32 + "-image_pin.py \"$out/c\"\n"
            "cp /tmp/forged.py \"$out/d\"\n"
        )}}
        result = _derivation_sources(drv)
        self.assertEqual(set(result), {"server.py", "evidence.py", "image_pin.py"})
        self.assertTrue(all(x.startswith("/nix/store/") for x in result.values()))

    def test_valid_output_only_from_effective_nixer_execstart(self):
        self.assertEqual(
            _store_output_from_execstart(
                "ExecStart={ path=" + STORE + "/bin/nixer ; argv[]=... }"
            ),
            STORE,
        )
        self.assertIsNone(_store_output_from_execstart("/usr/bin/nixer"))
        self.assertIsNone(_store_output_from_execstart(STORE + "/bin/wrong"))

    def test_http_406_proves_http_only_not_mcp_handshake(self):
        request_error = urllib.error.HTTPError(
            "http://127.0.0.1:18187/mcp", 406, "Not Acceptable", None, io.BytesIO(),
        )
        with patch("scripts.ops.measure_nixer_runtime_chain.urllib.request.urlopen", side_effect=request_error):
            proof = _http_observation()
        self.assertTrue(proof["http_responded"])
        self.assertEqual(proof["http_status"], 406)
        self.assertNotIn("mcp_handshake", proof)

    def test_mcp_status_success_requires_identity_backend_and_jsonrpc(self):
        expected = {"serverInfo": {"name": "Nixer"}, "protocolVersion": "2025-06-18"}
        good = {"isError": False, "structuredContent": {
            "identity": "nixer-nix-specialist-v0",
            "service": "Nixer", "backend": {"ready": True},
        }}
        with patch("scripts.ops.measure_nixer_runtime_chain._mcp_request",
                   side_effect=[expected, good]) as request:
            result = _mcp_observation()
        self.assertTrue(result["protocol_handshake_verified"])
        self.assertTrue(result["tool_call_verified"])
        self.assertEqual(result["tool_name"], "nixer_status")
        self.assertEqual(request.call_count, 2)

    def test_mcp_status_backend_failure_is_not_success(self):
        expected = {"serverInfo": {"name": "Nixer"}, "protocolVersion": "2025-06-18"}
        failed = {"isError": False, "structuredContent": {
            "identity": "nixer-nix-specialist-v0",
            "service": "Nixer", "backend": {"ready": False},
        }}
        with patch("scripts.ops.measure_nixer_runtime_chain._mcp_request",
                   side_effect=[expected, failed]):
            result = _mcp_observation()
        self.assertTrue(result["protocol_handshake_verified"])
        self.assertFalse(result["tool_call_verified"])
        self.assertIsNone(result["tool_payload_sha256"])

    def test_mcp_transport_failure_keeps_unknown(self):
        with patch("scripts.ops.measure_nixer_runtime_chain._mcp_request",
                   side_effect=OSError("connection refused")):
            result = _mcp_observation()
        self.assertFalse(result["protocol_handshake_verified"])
        self.assertFalse(result["tool_call_verified"])
        self.assertEqual(result["gap"], "OSError")

    def test_git_sha_requires_full_literal(self):
        with self.assertRaises(ValueError):
            _git_blob(None, "HEAD", "server.py")
        with self.assertRaises(ValueError):
            _git_blob(None, SHA, "../../passwd")

    def test_canonical_hash_input_order_invariant(self):
        self.assertEqual(_canonical({"a": 1, "b": 2}), _canonical({"b": 2, "a": 1}))
        self.assertEqual(json.loads(_canonical({"b": 2, "a": 1})), {"a": 1, "b": 2})


if __name__ == "__main__":
    unittest.main()