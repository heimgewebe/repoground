"""Focused positive and false-relation guards for S1 Flake Git-object projection."""
import json
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase

from merger.repoground.core.flake_input_relations import flake_revision_relations


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def make_repo(root, files):
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    # Prevent detached auto-maintenance racing temporary Git fixture cleanup.
    subprocess.run(["git", "-C", str(root), "config", "maintenance.auto", "false"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "gc.auto", "0"], check=True)
    for path, data in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding="utf-8")
    git(root, "add", ".")
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=Test",
         "-c", "user.email=test@example.invalid", "commit", "-qm", "snapshot"],
        check=True,
    )
    return git(root, "rev-parse", "HEAD")


def fixture(root, *, owner="heimgewebe", lock_rev=None, missing_module=False):
    target = root / "target"
    t_sha = make_repo(target, {
        "flake.nix": '{ nixosModules.default = import ./nix/module.nix; }\n',
        "nix/module.nix": "{ ... }: { }\n",
    })
    pin = t_sha
    lock = {
        "nodes": {
            "root": {"inputs": {"nixer": "nixer"}},
            "nixer": {"locked": {"type": "github", "owner": owner,
                                 "repo": "nixer", "rev": lock_rev or pin}},
        },
        "root": "root",
    }
    files = {
        "flake.nix": ('{\n  inputs = {\n    nixer.url = "github:'
                      + owner + '/nixer/' + pin + '";\n  };\n}\n'),
        "flake.lock": json.dumps(lock),
        "nixos/system/flake.nix":
            "{\n  hostModules = [ nixer.nixosModules.default ./modules/nixer.nix ];\n}\n",
    }
    if not missing_module:
        files["nixos/system/modules/nixer.nix"] = (
            "{ lib, ... }: {\n"
            "  services.nixer = { enable = true; };\n"
            "  systemd.user.services.nixer = { wantedBy = [ ]; };\n"
            "}\n"
        )
    source = root / "source"
    s_sha = make_repo(source, files)
    return source, s_sha, target, t_sha, pin


class FlakeRelationsTest(TestCase):
    def test_correct_chain_is_stable_and_declared_only(self):
        with tempfile.TemporaryDirectory() as directory:
            src, sha, target, t_sha, pin = fixture(Path(directory))
            output = flake_revision_relations(
                src, sha, source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, pin)},
            )
            self.assertEqual(output["status"], "ok")
            self.assertEqual(output["gaps"], [])
            self.assertEqual(
                {edge["relation_type"] for edge in output["relations"]},
                {"flake_pinned_input", "nixos_module_binding", "nixos_local_module_inclusion",
                 "nixos_service_declaration"},
            )
            self.assertEqual(len(output["relations"]), 5)
            self.assertEqual(output["relations"][0]["source"]["commit"], sha)
            self.assertEqual(output["relations"][0]["target"]["commit"], t_sha)
            self.assertEqual(output["relations"][0]["source"]["line_start"], 3)
            self.assertEqual(
                [edge["source"]["line_start"] for edge in output["relations"]
                 if edge["relation_type"] == "nixos_service_declaration"], [2, 3],
            )
            self.assertTrue(all(not edge["asserts_runtime_dependency"]
                                for edge in output["relations"]))
            self.assertIn("running_service", output["does_not_establish"])
            self.assertEqual(output, flake_revision_relations(
                src, sha, source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, pin)},
            ))

    def test_false_owner_is_not_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            src, sha, target, t_sha, pin = fixture(Path(directory))
            result = flake_revision_relations(
                src, sha, source_repo="heimgewebe/heim-pc",
                targets={"other/nixer": (target, t_sha)},
            )
            self.assertEqual(result["relations"], [])
            self.assertIn("target_not_provided:heimgewebe/nixer", result["gaps"])

    def test_lock_disagreement_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            src, sha, target, t_sha, pin = fixture(Path(directory), lock_rev="f"*40)
            result = flake_revision_relations(
                src, sha, source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, t_sha)},
            )
            self.assertFalse(result["relations"])
            self.assertIn("flake_lock_mismatch:nixer", result["gaps"])

    def test_no_fleet_membership_required(self):
        with tempfile.TemporaryDirectory() as directory:
            src, sha, target, t_sha, pin = fixture(Path(directory))
            self.assertTrue((src / "flake.lock").is_file())
            self.assertFalse((src / "fleet/repos.yml").exists())

    def test_wrong_target_commit_is_not_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            src, sha, target, t_sha, pin = fixture(Path(directory))
            result = flake_revision_relations(
                src, sha, source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, "e" * 40)},
            )
            self.assertEqual(result["relations"], [])
            self.assertIn("target_commit_mismatch:heimgewebe/nixer", result["gaps"])

    def test_missing_module_yields_only_flake_edge(self):
        with tempfile.TemporaryDirectory() as directory:
            src, sha, target, t_sha, pin = fixture(Path(directory), missing_module=True)
            result = flake_revision_relations(
                src, sha, source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, pin)},
            )
            self.assertEqual(
                [x["relation_type"] for x in result["relations"]],
                ["flake_pinned_input"],
            )
            self.assertIn(
                "host_module_path_missing:nixos/system/modules/nixer.nix",
                result["gaps"],
            )

    def test_pinned_object_ignores_mutable_worktree_head(self):
        with tempfile.TemporaryDirectory() as directory:
            src, sha, target, t_sha, pin = fixture(Path(directory))
            (target / "flake.nix").write_text(
                "# nixosModules.default = { };\n"
                "{ packages.default = 1; }\n", encoding="utf-8"
            )
            git(target, "add", "flake.nix")
            subprocess.run(
                ["git", "-C", str(target), "-c", "user.name=Test",
                 "-c", "user.email=test@example.invalid",
                 "commit", "-qm", "comment-only module"], check=True,
            )
            new_sha = git(target, "rev-parse", "HEAD")
            # The pinned commit remains the old one; its contents are still
            # authoritative, not mutable worktree HEAD.
            result = flake_revision_relations(
                src, sha, source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, pin)},
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(result["relations"]), 5)
            self.assertNotEqual(new_sha, pin)

    def test_nonexistent_target_not_assumed(self):
        with tempfile.TemporaryDirectory() as directory:
            src, sha, target, t_sha, pin = fixture(Path(directory))
            missing = target / "not-a-repo"
            result = flake_revision_relations(
                src, sha, source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (missing, pin)},
            )
            self.assertEqual(result["relations"], [])
            self.assertIn("target_commit_unavailable:heimgewebe/nixer", result["gaps"])

    def test_cli_federation_flake_relations(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from merger.repoground.cli.main import main

        with tempfile.TemporaryDirectory() as directory:
            src, sha, target, t_sha, pin = fixture(Path(directory))
            output = StringIO()
            with redirect_stdout(output):
                rc = main([
                    "federation", "flake-relations", "--repo-root", str(src),
                    "--repo-id", "heimgewebe/heim-pc", "--commit", sha,
                    "--target", f"heimgewebe/nixer={target}@{pin}",
                ])
            self.assertEqual(rc, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(result["relations"]), 5)

    def test_comment_only_target_export_stays_unverified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            pin = make_repo(target, {
                "flake.nix": "# nixosModules.default = pretend;\n"
                             "{ packages.default = 1; }\n",
            })
            source = root / "source"
            source_sha = make_repo(source, {
                "flake.nix": ('{\n  inputs = {\n    nixer.url = "github:heimgewebe/nixer/'
                              + pin + '";\n  };\n}\n'),
                "flake.lock": json.dumps({
                    "nodes": {
                        "root": {"inputs": {"nixer": "nixer"}},
                        "nixer": {"locked": {"type": "github",
                                            "owner": "heimgewebe",
                                            "repo": "nixer", "rev": pin}},
                    },
                    "root": "root",
                }),
                "nixos/system/flake.nix":
                    "hostModules = [ nixer.nixosModules.default ./modules/nixer.nix ];\n",
                "nixos/system/modules/nixer.nix": "services.nixer = { };\n",
            })
            result = flake_revision_relations(
                source, source_sha, source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, pin)},
            )
            self.assertEqual(
                [edge["relation_type"] for edge in result["relations"]],
                ["flake_pinned_input"],
            )
            self.assertIn("target_module_export_unverified:heimgewebe/nixer", result["gaps"])
