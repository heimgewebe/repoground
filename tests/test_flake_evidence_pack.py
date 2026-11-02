"""Real Git fixture and offline evidence-pack consumer tests."""
from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from merger.repoground.cli.main import main
from merger.repoground.core.flake_evidence_pack import (
    prepare_flake_evidence_pack,
    read_flake_evidence_pack,
    read_flake_evidence_pack_payload,
    write_flake_evidence_pack,
)
from tests.test_cross_repo_flake_relations import fixture

SOURCE_REPO = "heimgewebe/heim-pc"
TARGET_REPO = "heimgewebe/nixer"


class FlakeEvidencePackTest(unittest.TestCase):
    def _prepare(self, root):
        source, source_sha, target, target_sha, _pin = fixture(root)
        return source, source_sha, target, target_sha

    def test_precomputed_pack_is_deterministic_and_git_free_to_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, sha, target, target_sha = self._prepare(root)
            kwargs = {
                "source_repo": SOURCE_REPO,
                "targets": {TARGET_REPO: (target, target_sha)},
            }
            first = prepare_flake_evidence_pack(source, sha, **kwargs)
            second = prepare_flake_evidence_pack(source, sha, **kwargs)
            self.assertEqual(first, second)
            self.assertEqual(len(first["evidence"]["relations"]), 5)
            self.assertEqual(first["evidence"]["gaps"], [])
            pack_file = root / "offline.json"
            write_flake_evidence_pack(pack_file, first)
            with patch.object(subprocess, "run", side_effect=AssertionError("Git call on read")), \
                 patch.object(subprocess, "check_output", side_effect=AssertionError("Git call on read")):
                loaded = read_flake_evidence_pack(
                    pack_file, expected_repo=SOURCE_REPO, expected_commit=sha,
                )
            self.assertEqual(first, loaded)

    def test_read_offline_even_when_source_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, sha, target, target_sha = self._prepare(root)
            pack = prepare_flake_evidence_pack(
                source, sha,
                source_repo=SOURCE_REPO, targets={TARGET_REPO: (target, target_sha)},
            )
            path = root / "read.json"
            write_flake_evidence_pack(path, pack)
            with patch(
                "merger.repoground.core.flake_input_relations.flake_revision_relations",
                side_effect=AssertionError("producer invoked"),
                create=True,
            ), patch("subprocess.run", side_effect=AssertionError("Git invoked")):
                self.assertEqual(
                    read_flake_evidence_pack(path, expected_repo=SOURCE_REPO,
                                             expected_commit=sha)["pack_sha256"],
                    pack["pack_sha256"],
                )

    def test_tampered_bytes_or_hash_do_not_become_s1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, sha, target, target_sha = self._prepare(root)
            pack = prepare_flake_evidence_pack(
                source, sha, source_repo=SOURCE_REPO,
                targets={TARGET_REPO: (target, target_sha)},
            )
            for variant in ("gaps", "runtime", "digest"):
                with self.subTest(variant=variant):
                    bad = copy.deepcopy(pack)
                    if variant == "gaps":
                        bad["evidence"]["gaps"].append("never_measured")
                    elif variant == "runtime":
                        bad["evidence"]["relations"][0]["asserts_runtime_dependency"] = True
                    else:
                        bad["pack_sha256"] = "0" * 64
                    with self.assertRaises(ValueError):
                        read_flake_evidence_pack_payload(bad)

    def test_wrong_commit_and_repo_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, sha, target, target_sha = self._prepare(root)
            pack = prepare_flake_evidence_pack(
                source, sha, source_repo=SOURCE_REPO,
                targets={TARGET_REPO: (target, target_sha)},
            )
            path = root / "pack.json"
            write_flake_evidence_pack(path, pack)
            with self.assertRaisesRegex(ValueError, "source revision"):
                read_flake_evidence_pack(
                    path, expected_repo=SOURCE_REPO, expected_commit="f" * 40,
                )
            with self.assertRaisesRegex(ValueError, "source repo"):
                read_flake_evidence_pack(
                    path, expected_repo="wrong/repo", expected_commit=sha,
                )

    def test_symlink_not_accepted_and_existing_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, sha, target, target_sha = self._prepare(root)
            pack = prepare_flake_evidence_pack(
                source, sha, source_repo=SOURCE_REPO,
                targets={TARGET_REPO: (target, target_sha)},
            )
            path = root / "pack.json"
            write_flake_evidence_pack(path, pack)
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_flake_evidence_pack(path, pack)
            self.assertEqual(before, path.read_bytes())
            symlink = root / "alias.json"
            symlink.symlink_to(path)
            with self.assertRaises(OSError):
                read_flake_evidence_pack(
                    symlink, expected_repo=SOURCE_REPO, expected_commit=sha,
                )

    def test_cli_creates_once_and_reads_exact_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, sha, target, target_sha = self._prepare(root)
            path = root / "bundle.json"
            args = [
                "federation", "flake-pack-create",
                "--repo-root", str(source), "--repo-id", SOURCE_REPO,
                "--commit", sha,
                "--target", f"{TARGET_REPO}={target}@{target_sha}",
                "--out", str(path),
            ]
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(args), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "created")
            self.assertEqual(result["relation_count"], 5)
            self.assertEqual(result["pack_sha256"],
                             read_flake_evidence_pack(path, expected_repo=SOURCE_REPO,
                                                      expected_commit=sha)["pack_sha256"])
            with patch("subprocess.run", side_effect=AssertionError("Git invoked")):
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main([
                        "federation", "flake-pack-read", "--pack", str(path),
                        "--repo-id", SOURCE_REPO, "--commit", sha,
                    ]), 0)
                self.assertEqual(json.loads(output.getvalue())["pack_sha256"],
                                 result["pack_sha256"])

    def test_partial_evidence_retains_unverified_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, sha, target, _target_sha = self._prepare(root)
            unreachable = "e" * 40
            # Commit not supplied by the target checkout is S0, not an S1 claim.
            # Produce a valid partial producer result without forging its digest:
            # flip the URL, lock and inner input to the same unknown Git commit.
            from tests.test_cross_repo_flake_relations import rewrite_committed
            original_pin = (source / "flake.nix").read_text().split("nixer/")[1][:40]
            for file in ("flake.nix", "flake.lock", "nixos/system/flake.nix"):
                sha = rewrite_committed(source, file, original_pin, unreachable)
            pack = prepare_flake_evidence_pack(
                source, sha, source_repo=SOURCE_REPO,
                targets={TARGET_REPO: (target, unreachable)},
            )
            self.assertEqual(pack["evidence"]["relations"], [])
            self.assertIn("target_commit_unavailable:heimgewebe/nixer",
                          pack["evidence"]["gaps"])
            path = root / "partial.json"
            write_flake_evidence_pack(path, pack)
            self.assertEqual(
                read_flake_evidence_pack(path, expected_repo=SOURCE_REPO,
                                         expected_commit=sha)["evidence"]["status"],
                "partial",
            )

    def test_manifest_cli_and_mcp_read_same_immutable_evidence_without_git(self):
        import argparse
        from merger.repoground.cli.cmd_ground import build_snapshot_create_result
        from merger.repoground.core.bundle_generation import resolve_bundle_manifest_path
        from merger.repoground.cli.mcp_stdio import RepoGroundMcpStdioServer
        from merger.repoground.core.flake_evidence_pack import read_flake_evidence_from_manifest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, sha, target, target_sha = self._prepare(root)
            subprocess.run(
                ["git", "-C", str(source), "remote", "add", "origin",
                 "https://github.com/heimgewebe/heim-pc.git"],
                capture_output=True, check=True,
            )
            snapshot_args = argparse.Namespace(
                repo=str(source), out=str(root / "pub"), profile="fleet-context",
                mode="gesamt", max_bytes="0", split_size="25MB",
                path_filter=None, ext=None, output_mode=None,
                redact_secrets=None, include_hidden=True,
                language_structure=False, latest_complete_registry=None,
                flake_source_repo=SOURCE_REPO,
                flake_targets=[f"{TARGET_REPO}={target}@{target_sha}"],
            )
            result = build_snapshot_create_result(snapshot_args)
            self.assertEqual(result["finalization"]["status"], "pass")
            published = resolve_bundle_manifest_path(result["bundle_manifest"])
            manifest = json.loads(published.read_text())
            evidence_entries = [
                row for row in manifest["artifacts"]
                if row["role"] == "flake_relation_evidence_json"
            ]
            self.assertEqual(len(evidence_entries), 1)
            server = RepoGroundMcpStdioServer(bundle_root=published)
            server.handle_message({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26",
                           "clientInfo": {"name": "test", "version": "1"},
                           "capabilities": {}},
            })
            with patch("subprocess.run", side_effect=AssertionError("Git invoked")):
                direct = read_flake_evidence_from_manifest(published, expected_repo=SOURCE_REPO, expected_commit=sha)
                self.assertEqual(direct["evidence"]["status"], "ok")
                self.assertEqual(len(direct["evidence"]["relations"]), 5)
                self.assertEqual(direct["source_commit"], sha)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main([
                        "federation", "flake-pack-manifest",
                        "--manifest", str(published),
                        "--repo-id", SOURCE_REPO, "--commit", sha,
                    ]), 0)
                cli = json.loads(output.getvalue())
                response = server.handle_message({
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {
                        "name": "get_flake_relation_evidence",
                        "arguments": {
                            "bundle_manifest": str(published),
                            "expected_repo": SOURCE_REPO,
                            "expected_commit": sha,
                        },
                    },
                })
            mcp = response["result"]["structuredContent"]
            self.assertFalse(response["result"]["isError"])
            self.assertEqual(cli["pack_sha256"], direct["pack_sha256"])
            self.assertEqual(mcp["pack_sha256"], direct["pack_sha256"])
            import hashlib
            self.assertEqual(
                mcp["manifest_sha256"], hashlib.sha256(published.read_bytes()).hexdigest(),
            )
            self.assertEqual(mcp["evidence"]["gaps"], [])
            self.assertTrue(all(
                edge["asserts_runtime_dependency"] is False
                for edge in mcp["evidence"]["relations"]
            ))

    def test_manifest_reader_rejects_remote_identity_mismatch(self):
        from merger.repoground.core.flake_evidence_pack import _remote_matches_repo
        self.assertTrue(_remote_matches_repo("git@github.com:heimgewebe/heim-pc.git", SOURCE_REPO))
        self.assertTrue(_remote_matches_repo("https://github.com/heimgewebe/heim-pc.git", SOURCE_REPO))
        self.assertFalse(_remote_matches_repo("https://example.invalid/heimgewebe/heim-pc", SOURCE_REPO))
        self.assertFalse(_remote_matches_repo("https://github.com/evil/wrong-repo", SOURCE_REPO))


    def test_manifest_emission_rejects_wrong_source_origin(self):
        import argparse
        from merger.repoground.cli.cmd_ground import build_snapshot_create_result

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, sha, target, target_sha = self._prepare(root)
            subprocess.run(
                ["git", "-C", str(src), "remote", "add", "origin",
                 "https://github.com/another-owner/heim-pc.git"],
                capture_output=True, check=True,
            )
            ns = argparse.Namespace(
                repo=str(src), out=str(root / "pub"), profile="fleet-context",
                mode="gesamt", max_bytes="0", split_size="25MB",
                path_filter=None, ext=None, output_mode=None,
                redact_secrets=None, include_hidden=True, language_structure=False,
                latest_complete_registry=None, flake_source_repo=SOURCE_REPO,
                flake_targets=[f"{TARGET_REPO}={target}@{target_sha}"],
            )
            with self.assertRaisesRegex(ValueError, "source remote"):
                build_snapshot_create_result(ns)

    def test_paired_benchmark_checks_same_revision_and_payload(self):
        from scripts.measure_flake_evidence import measure_flake_evidence

        with tempfile.TemporaryDirectory() as tmp:
            src, sha, target, target_sha = self._prepare(Path(tmp))
            report = measure_flake_evidence(
                src, sha, source_repo=SOURCE_REPO,
                targets={TARGET_REPO: (target, target_sha)},
                samples=5, warmups=1,
            )
            self.assertEqual(report["source_commit"], sha)
            self.assertEqual(report["source_repo"], SOURCE_REPO)
            self.assertEqual(report["relations"], 5)
            self.assertEqual(report["gaps"], [])
            self.assertGreater(report["results"]["git_only"]["p95_ms"], 0)
            self.assertGreater(report["results"]["precomputed_offline"]["p95_ms"], 0)
            self.assertEqual(report["method"]["samples_per_path"], 5)
            with self.assertRaises(ValueError):
                measure_flake_evidence(
                    src, sha, source_repo=SOURCE_REPO,
                    targets={TARGET_REPO: (target, target_sha)},
                    samples=2,
                )

    def test_public_share_excludes_flake_pack_without_generation_failure(self):
        import argparse
        from merger.repoground.cli.cmd_ground import build_snapshot_create_result
        from merger.repoground.core.bundle_generation import resolve_bundle_manifest_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _sha, target, target_sha = self._prepare(root)
            subprocess.run(
                ["git", "-C", str(source), "remote", "add", "origin",
                 "https://github.com/heimgewebe/heim-pc.git"],
                capture_output=True, check=True,
            )
            out = root / "public"
            ns = argparse.Namespace(
                repo=str(source), out=str(out), profile="public-share",
                mode="gesamt", max_bytes="0", split_size="25MB",
                path_filter=None, ext=None, output_mode=None,
                redact_secrets=None, include_hidden=True,
                language_structure=False, latest_complete_registry=None,
                flake_source_repo=SOURCE_REPO,
                flake_targets=[f"{TARGET_REPO}={target}@{target_sha}"],
            )
            result = build_snapshot_create_result(ns)
            self.assertEqual(result["finalization"]["status"], "pass")
            manifest = resolve_bundle_manifest_path(result["bundle_manifest"])
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertFalse(any(
                item["role"] == "flake_relation_evidence_json"
                for item in metadata["artifacts"]
            ))
            self.assertFalse(list(out.glob("*.flake_relation_evidence.*.json")))

    def test_two_same_minute_publisher_generations_remain_isolated(self):
        import argparse
        from merger.repoground.cli.cmd_ground import build_snapshot_create_result
        from merger.repoground.core.bundle_generation import resolve_bundle_manifest_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, sha, target, target_sha = self._prepare(root)
            subprocess.run(
                ["git", "-C", str(source), "remote", "add", "origin",
                 "https://github.com/heimgewebe/heim-pc.git"],
                capture_output=True, check=True,
            )
            out = root / "pub" / "generation_a"
            ns = argparse.Namespace(
                repo=str(source), out=str(out), profile="fleet-context",
                mode="gesamt", max_bytes="0", split_size="25MB",
                path_filter=None, ext=None, output_mode=None,
                redact_secrets=None, include_hidden=True, language_structure=False,
                latest_complete_registry=None, flake_source_repo=SOURCE_REPO,
                flake_targets=[f"{TARGET_REPO}={target}@{target_sha}"],
            )
            first = build_snapshot_create_result(ns)
            self.assertEqual(first["finalization"]["status"], "pass")
            immutable = resolve_bundle_manifest_path(first["bundle_manifest"])
            before = immutable.read_bytes()
            # The existing publisher selects a distinct output directory for
            # each generation; do not reuse the underlying graph source files.
            ns.out = str(root / "pub" / "generation_b")
            second = build_snapshot_create_result(ns)
            self.assertEqual(second["finalization"]["status"], "pass")
            self.assertEqual(immutable.read_bytes(), before)
            manifest = resolve_bundle_manifest_path(second["bundle_manifest"])
            rows = [
                a for a in json.loads(manifest.read_text())["artifacts"]
                if a["role"] == "flake_relation_evidence_json"
            ]
            self.assertEqual(len(rows), 1)
            self.assertIn(".flake_relation_evidence.", rows[0]["path"])
            self.assertEqual(
                read_flake_evidence_pack(
                    manifest.parent / rows[0]["path"],
                    expected_repo=SOURCE_REPO, expected_commit=sha,
                )["evidence"]["status"], "ok",
            )

    def test_existing_staging_pack_is_reused_only_if_hash_identical(self):
        from merger.repoground.cli.cmd_ground import _write_or_reuse_flake_pack

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, sha, target, target_sha = self._prepare(root)
            pack = prepare_flake_evidence_pack(
                source, sha, source_repo=SOURCE_REPO,
                targets={TARGET_REPO: (target, target_sha)},
            )
            output = root / "pack.json"
            _write_or_reuse_flake_pack(output, pack)
            first = output.read_bytes()
            _write_or_reuse_flake_pack(output, pack)
            self.assertEqual(output.read_bytes(), first)
            altered = prepare_flake_evidence_pack(
                source, sha, source_repo=SOURCE_REPO,
                targets={TARGET_REPO: (target, "f" * 40)},
            )
            with self.assertRaisesRegex(ValueError, "different Flake evidence"):
                _write_or_reuse_flake_pack(output, altered)
            self.assertEqual(output.read_bytes(), first)

if __name__ == "__main__":
    unittest.main()
