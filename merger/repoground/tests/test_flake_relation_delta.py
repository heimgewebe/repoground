"""S2 exact-revision Flake relation transition tests: positive and false removals."""
from __future__ import annotations

import json
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import TestCase

from merger.repoground.cli.main import main
from merger.repoground.core.flake_relation_delta import flake_relation_delta
from tests.test_cross_repo_flake_relations import fixture, rewrite_committed


REPO = "heimgewebe/heim-pc"
TARGET = "heimgewebe/nixer"


def query(source, base, head, target, old_pin, new_pin):
    return flake_relation_delta(
        source, base, head, source_repo=REPO,
        targets_before={TARGET: (target, old_pin)},
        targets_after={TARGET: (target, new_pin)},
    )


def new_target_pin(target):
    return rewrite_committed(
        target, "flake.nix",
        "nixosModules.default = import ./nix/module.nix;",
        "nixosModules.default = import ./nix/module.nix; # new target revision",
    )


class FlakeRelationDeltaTests(TestCase):
    def test_unchanged_revisions_are_exact_and_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            source, base, target, pin, _ = fixture(Path(d))
            first = query(source, base, base, target, pin, pin)
            self.assertEqual(first["status"], "ok")
            self.assertEqual(first["changes"], [])
            self.assertEqual(first["direct_source_file_changes"], [])
            self.assertEqual(first, query(source, base, base, target, pin, pin))
            self.assertEqual(len(first["evidence_sha256"]), 64)
            self.assertIn("running_service", first["does_not_establish"])

    def test_outer_pin_changed_but_inner_old_is_unverified_not_removed(self):
        with tempfile.TemporaryDirectory() as d:
            source, base, target, pin, _ = fixture(Path(d))
            new_pin = new_target_pin(target)
            rewrite_committed(source, "flake.nix", pin, new_pin)
            head = rewrite_committed(source, "flake.lock", pin, new_pin)
            result = query(source, base, head, target, pin, new_pin)
            self.assertEqual(result["status"], "partial")
            self.assertIn("inner_flake_input_unverified:nixer", result["head_gaps"])
            self.assertEqual(
                [x["transition"] for x in result["changes"]].count("changed"), 1,
            )
            self.assertTrue(any(
                x["transition"] == "unverified"
                and x["relation_identity"]["relation_type"] == "nixos_module_binding"
                for x in result["changes"]
            ))
            self.assertFalse(any(x["transition"] == "removed" for x in result["changes"]))
            changed_paths = {x["path"] for x in result["direct_source_file_changes"]}
            self.assertEqual(changed_paths, {"flake.nix", "flake.lock"})
            self.assertTrue(all(
                x["asserts_runtime_change"] is False for x in result["changes"]
            ))

    def test_consistent_pin_change_has_changed_edges_not_removed(self):
        with tempfile.TemporaryDirectory() as d:
            source, base, target, pin, _ = fixture(Path(d))
            new_pin = new_target_pin(target)
            for path in ("flake.nix", "flake.lock", "nixos/system/flake.nix"):
                head = rewrite_committed(source, path, pin, new_pin)
            result = query(source, base, head, target, pin, new_pin)
            self.assertEqual(result["status"], "ok")
            self.assertFalse(result["gaps"])
            self.assertTrue(all(x["transition"] == "changed" for x in result["changes"]))
            self.assertTrue(any(x["relation_identity"]["relation_type"] ==
                                "flake_pinned_input" for x in result["changes"]))

    def test_real_service_declaration_removal_with_complete_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            source, base, target, pin, _ = fixture(Path(d))
            head = rewrite_committed(
                source, "nixos/system/modules/nixer.nix",
                "  systemd.user.services.nixer = { wantedBy = [ ]; };",
                "  # systemd.user.services.nixer was deliberately removed",
            )
            result = query(source, base, head, target, pin, pin)
            self.assertEqual(result["status"], "ok")
            removed = [x for x in result["changes"] if x["transition"] == "removed"]
            self.assertEqual(len(removed), 1)
            self.assertEqual(
                removed[0]["relation_identity"]["target"]["symbol"],
                "systemd.user.services.nixer",
            )
            self.assertFalse(any(x["transition"] == "unverified" for x in result["changes"]))

    def test_missing_target_git_object_never_becomes_removal(self):
        with tempfile.TemporaryDirectory() as d:
            source, base, target, pin, _ = fixture(Path(d))
            output = flake_relation_delta(
                source, base, base, source_repo=REPO,
                targets_before={TARGET: (target, pin)},
                targets_after={TARGET: (target / "missing", pin)},
            )
            self.assertEqual(output["status"], "partial")
            self.assertIn("target_commit_unavailable:heimgewebe/nixer", output["head_gaps"])
            self.assertFalse(any(x["transition"] == "removed" for x in output["changes"]))
            self.assertEqual(
                sum(x["transition"] == "unverified" for x in output["changes"]), 5,
            )

    def test_cli_exact_commits_and_invalid_sha(self):
        with tempfile.TemporaryDirectory() as d:
            source, base, target, pin, _ = fixture(Path(d))
            argv = [
                "federation", "flake-relation-delta",
                "--repo-root", str(source), "--repo-id", REPO,
                "--base", base, "--head", base,
                "--target-before", f"{TARGET}={target}@{pin}",
                "--target-after", f"{TARGET}={target}@{pin}",
            ]
            output = StringIO()
            with redirect_stdout(output):
                rc = main(argv)
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(output.getvalue())["changes"], [])
            with redirect_stdout(StringIO()):
                bad = main(argv[:argv.index("--head") + 1] + ["HEAD"]
                           + argv[argv.index("--head") + 2:])
            self.assertEqual(bad, 1)
