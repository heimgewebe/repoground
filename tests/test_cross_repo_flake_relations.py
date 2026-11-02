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
        "flake.nix": '{\n  outputs = { self }: {\n'
                     '    nixosModules.default = import ./nix/module.nix;\n'
                     '  };\n}\n',
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
                      + owner + '/nixer/' + pin + '";\n  };\n'
                      '  outputs = inputs@{ self, nixer }:'
                      ' (import ./nixos/system/flake.nix).outputs inputs;\n}\n'),
        "flake.lock": json.dumps(lock),
        "nixos/system/flake.nix": (
            '{\n  inputs = {\n    nixer.url = "github:' + owner + '/nixer/'
            + pin + '";\n  };\n'
            '  outputs = { self, nixer }:\n    let\n'
            '      hostModules = [ nixer.nixosModules.default ./modules/nixer.nix ];\n'
            '    in { inherit hostModules; };\n}\n'
        ),
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


def rewrite_committed(root, path, original, replacement):
    target = root / path
    source = target.read_text(encoding="utf-8")
    assert original in source, (path, original)
    target.write_text(source.replace(original, replacement, 1), encoding="utf-8")
    git(root, "add", path)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=Test",
         "-c", "user.email=test@example.invalid",
         "commit", "-qm", "revised Git fixture"], check=True,
    )
    return git(root, "rev-parse", "HEAD")


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
                "nixos/system/flake.nix": (
                    '{\n  inputs = {\n    nixer.url = "github:heimgewebe/nixer/'
                    + pin + '";\n  };\n  outputs = { self, nixer }:\n'
                    '    let hostModules = [ nixer.nixosModules.default '
                    './modules/nixer.nix ]; in { inherit hostModules; };\n}\n'
                ),
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

    def test_outside_root_inputs_does_not_resolve(self):
        with tempfile.TemporaryDirectory() as directory:
            src, _sha, target, t_sha, pin = fixture(Path(directory))
            (src / "flake.nix").write_text(
                '{\n  other = {\n'
                f'    nixer.url = "github:heimgewebe/nixer/{pin}";\n'
                '  };\n}\n', encoding="utf-8"
            )
            git(src, "add", "flake.nix")
            subprocess.run(
                ["git", "-C", str(src), "-c", "user.name=Test",
                 "-c", "user.email=test@example.invalid",
                 "commit", "-qm", "unrelated attr"], check=True,
            )
            result = flake_revision_relations(
                src, git(src, "rev-parse", "HEAD"),
                source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, t_sha)},
            )
            self.assertEqual(result["relations"], [])
            self.assertIn("flake_url_outside_root_inputs:nixer", result["gaps"])

    def test_direct_top_level_inputs_attrpath_resolves(self):
        with tempfile.TemporaryDirectory() as directory:
            src, _sha, target, t_sha, pin = fixture(Path(directory))
            (src / "flake.nix").write_text(
                '{\n'
                f'  inputs.nixer.url = "github:heimgewebe/nixer/{pin}";\n'
                '  outputs = inputs@{ self, nixer }: '
                '(import ./nixos/system/flake.nix).outputs inputs;\n'
                '}\n', encoding="utf-8"
            )
            git(src, "add", "flake.nix")
            subprocess.run(
                ["git", "-C", str(src), "-c", "user.name=Test",
                 "-c", "user.email=test@example.invalid",
                 "commit", "-qm", "direct input attrpath"], check=True,
            )
            result = flake_revision_relations(
                src, git(src, "rev-parse", "HEAD"),
                source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, t_sha)},
            )
            self.assertEqual(result["gaps"], [])
            self.assertEqual(len(result["relations"]), 5)

    def test_duplicate_root_inputs_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as directory:
            src, _sha, target, t_sha, pin = fixture(Path(directory))
            (src / "flake.nix").write_text(
                '{\n  inputs = {\n'
                f'    nixer.url = "github:heimgewebe/nixer/{pin}";\n'
                f'    nixer.url = "github:heimgewebe/nixer/{pin}";\n'
                '  };\n}\n', encoding="utf-8"
            )
            git(src, "add", "flake.nix")
            subprocess.run(
                ["git", "-C", str(src), "-c", "user.name=Test",
                 "-c", "user.email=test@example.invalid",
                 "commit", "-qm", "duplicate attr"], check=True,
            )
            result = flake_revision_relations(
                src, git(src, "rev-parse", "HEAD"),
                source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, t_sha)},
            )
            self.assertEqual(result["relations"], [])
            self.assertIn("duplicate_flake_input:nixer", result["gaps"])

    def test_host_modules_after_closing_bracket_cannot_bind(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, sha, target, t_sha, _pin = fixture(Path(tmp))
            sha = rewrite_committed(
                src, "nixos/system/flake.nix",
                "hostModules = [ nixer.nixosModules.default ./modules/nixer.nix ];",
                "hostModules = [ ]; unused = [ nixer.nixosModules.default ./modules/nixer.nix ];",
            )
            result = flake_revision_relations(
                src, sha, source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, t_sha)},
            )
            self.assertEqual([r["relation_type"] for r in result["relations"]],
                             ["flake_pinned_input"])
            self.assertIn("host_modules_list_unverified:nixer", result["gaps"])

    def test_same_suffix_other_nixer_alias_cannot_bind(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, sha, target, t_sha, _pin = fixture(Path(tmp))
            sha = rewrite_committed(
                src, "nixos/system/flake.nix",
                "hostModules = [ nixer.nixosModules.default ./modules/nixer.nix ];",
                "hostModules = [ other-nixer.nixosModules.default ./modules/nixer.nix ];",
            )
            result = flake_revision_relations(
                src, sha, source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, t_sha)},
            )
            self.assertEqual([r["relation_type"] for r in result["relations"]],
                             ["flake_pinned_input"])

    def test_module_suffix_is_not_prefix_of_an_actual_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, sha, target, t_sha, _pin = fixture(Path(tmp))
            extra = src / "nixos/system/modules/nixer.nix.disabled"
            extra.write_text("services.nixer = { enable = true; };\n", encoding="utf-8")
            git(src, "add", "nixos/system/modules/nixer.nix.disabled")
            sha = rewrite_committed(
                src, "nixos/system/flake.nix",
                "hostModules = [ nixer.nixosModules.default ./modules/nixer.nix ];",
                "hostModules = [ nixer.nixosModules.default ./modules/nixer.nix.disabled ];",
            )
            result = flake_revision_relations(
                src, sha, source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, t_sha)},
            )
            self.assertEqual([r["relation_type"] for r in result["relations"]],
                             ["flake_pinned_input"])

    def test_nested_export_is_not_an_actual_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, sha, target, t_sha, _pin = fixture(Path(tmp))
            revised = rewrite_committed(
                target, "flake.nix",
                "nixosModules.default = import ./nix/module.nix;",
                "unused = { nixosModules.default = import ./nix/module.nix; };",
            )
            # Pin remains the old object; root URL/lock must follow the exact
            # newly created target Git revision for this negative fixture.
            sha = rewrite_committed(src, "flake.nix", t_sha, revised)
            sha = rewrite_committed(src, "flake.lock", t_sha, revised)
            sha = rewrite_committed(src, "nixos/system/flake.nix", t_sha, revised)
            result = flake_revision_relations(
                src, sha, source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, revised)},
            )
            self.assertEqual([r["relation_type"] for r in result["relations"]],
                             ["flake_pinned_input"])
            self.assertIn("target_module_export_unverified:heimgewebe/nixer",
                          result["gaps"])

    def test_inner_flake_conflicting_pin_cannot_claim_outer_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, sha, target, t_sha, _pin = fixture(Path(tmp))
            sha = rewrite_committed(
                src, "nixos/system/flake.nix",
                f'nixer.url = "github:heimgewebe/nixer/{t_sha}";',
                f'nixer.url = "github:other/nixer/{"f" * 40}";',
            )
            result = flake_revision_relations(
                src, sha, source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, t_sha)},
            )
            self.assertEqual([r["relation_type"] for r in result["relations"]],
                             ["flake_pinned_input"])
            self.assertIn("inner_flake_input_unverified:nixer", result["gaps"])

    def test_nested_let_variable_is_not_a_returned_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, sha, target, t_sha, _pin = fixture(Path(tmp))
            new = rewrite_committed(
                target, "flake.nix",
                "outputs = { self }: {\n"
                "    nixosModules.default = import ./nix/module.nix;\n"
                "  };",
                "outputs = { self }: let\n"
                "    hidden = { nixosModules.default = import ./nix/module.nix; };\n"
                "  in { packages.default = null; };",
            )
            sha = rewrite_committed(src, "flake.nix", t_sha, new)
            sha = rewrite_committed(src, "flake.lock", t_sha, new)
            sha = rewrite_committed(src, "nixos/system/flake.nix", t_sha, new)
            result = flake_revision_relations(
                src, sha, source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, new)},
            )
            self.assertEqual([r["relation_type"] for r in result["relations"]],
                             ["flake_pinned_input"])
            self.assertIn("target_module_export_unverified:heimgewebe/nixer",
                          result["gaps"])

    def test_outer_flake_missing_outputs_passthrough_does_not_claim_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, sha, target, t_sha, _pin = fixture(Path(tmp))
            sha = rewrite_committed(
                src, "flake.nix",
                "(import ./nixos/system/flake.nix).outputs inputs;",
                "{ packages.default = null; };",
            )
            result = flake_revision_relations(
                src, sha, source_repo="heimgewebe/heim-pc",
                targets={"heimgewebe/nixer": (target, t_sha)},
            )
            self.assertEqual([r["relation_type"] for r in result["relations"]],
                             ["flake_pinned_input"])
            self.assertIn("inner_flake_input_unverified:nixer", result["gaps"])
