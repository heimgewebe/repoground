"""Tests for the centralized Atlas CLI registrar (register_atlas_commands /
handle_atlas_command in cmd_atlas.py).

Scope:
- Both repoground (cli/main.py) and repoground (cli/repoground.py) consume the same
  registrar, so every subcommand only needs to be defined once.
- These tests verify: shared registrar shape (stable atlas subcommand set),
  dispatch via repoground for `machines`, dispatch via repoground for `machines`,
  and the `analyze growth` positional args are wired correctly.
"""
import argparse
import sys
import pytest

from merger.repoground.cli import cmd_atlas as cmd_atlas_module
from merger.repoground.cli.main import main as repoground_main
from merger.repoground.cli.serve import main as service_launcher_main


_EXPECTED_ATLAS_SUBCOMMANDS = {
    "scan",
    "machine-health",
    "machines",
    "roots",
    "snapshots",
    "diff",
    "history",
    "search",
    "index",
    "analyze",
}


def _build_atlas_parser() -> argparse.ArgumentParser:
    """Build a standalone parser that contains only the atlas subcommand."""
    root = argparse.ArgumentParser()
    subs = root.add_subparsers(dest="command")
    cmd_atlas_module.register_atlas_commands(subs)
    return root


def test_registrar_exposes_expected_subcommands():
    """register_atlas_commands registers exactly the expected set of atlas sub-commands."""
    parser = _build_atlas_parser()
    atlas_action = next(a for a in parser._subparsers._group_actions if a.dest == "command")
    atlas_parser = atlas_action.choices["atlas"]
    atlas_subs_action = next(a for a in atlas_parser._subparsers._group_actions if a.dest == "atlas_cmd")
    registered = set(atlas_subs_action.choices.keys())
    assert registered == _EXPECTED_ATLAS_SUBCOMMANDS


# ---------------------------------------------------------------------------
# Dispatch tests via repoground_main
# ---------------------------------------------------------------------------

def test_lenskit_dispatches_atlas_machines(monkeypatch):
    """repoground atlas machines routes to run_atlas_machines via handle_atlas_command."""
    called = False

    def mock_run_machines(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "machines"
        return 0

    monkeypatch.setattr(cmd_atlas_module, "run_atlas_machines", mock_run_machines)

    exit_code = repoground_main(["atlas", "machines"])
    assert exit_code == 0
    assert called


def test_lenskit_dispatches_atlas_machine_health(monkeypatch):
    """repoground atlas machine-health routes to run_atlas_machine_health."""
    called = False

    def mock_handler(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "machine-health"
        return 0

    monkeypatch.setattr(cmd_atlas_module, "run_atlas_machine_health", mock_handler)

    exit_code = repoground_main(["atlas", "machine-health"])
    assert exit_code == 0
    assert called


def test_lenskit_dispatches_atlas_analyze_growth(monkeypatch):
    """repoground atlas analyze growth <src> <tgt> parses positional args correctly."""
    called = False

    def mock_run_analyze(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "analyze"
        assert args.analyze_command == "growth"
        assert args.source_snapshot == "snap_src"
        assert args.target_snapshot == "snap_tgt"
        return 0

    monkeypatch.setattr(cmd_atlas_module, "run_atlas_analyze", mock_run_analyze)

    exit_code = repoground_main(["atlas", "analyze", "growth", "snap_src", "snap_tgt"])
    assert exit_code == 0
    assert called


# ---------------------------------------------------------------------------
# Dispatch tests via repoground_main
# ---------------------------------------------------------------------------

def _run_service_launcher(monkeypatch, argv):
    """Run repoground_main with a given argv, catching SystemExit, and return exit code."""
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        service_launcher_main()
    return exc.value.code


def test_repoground_dispatches_atlas_machines(monkeypatch):
    """repoground atlas machines routes to run_atlas_machines via handle_atlas_command."""
    called = False

    def mock_run_machines(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "machines"
        return 0

    monkeypatch.setattr(cmd_atlas_module, "run_atlas_machines", mock_run_machines)

    code = _run_service_launcher(monkeypatch, ["repoground", "atlas", "machines"])
    assert code == 0
    assert called


def test_repoground_dispatches_atlas_machine_health(monkeypatch):
    """repoground atlas machine-health routes to run_atlas_machine_health."""
    called = False

    def mock_handler(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "machine-health"
        return 0

    monkeypatch.setattr(cmd_atlas_module, "run_atlas_machine_health", mock_handler)

    code = _run_service_launcher(monkeypatch, ["repoground", "atlas", "machine-health"])
    assert code == 0
    assert called


def test_repoground_dispatches_atlas_analyze_growth(monkeypatch):
    """repoground atlas analyze growth <src> <tgt> parses positional args correctly."""
    called = False

    def mock_run_analyze(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "analyze"
        assert args.analyze_command == "growth"
        assert args.source_snapshot == "snap_src"
        assert args.target_snapshot == "snap_tgt"
        return 0

    monkeypatch.setattr(cmd_atlas_module, "run_atlas_analyze", mock_run_analyze)

    code = _run_service_launcher(monkeypatch, ["repoground", "atlas", "analyze", "growth", "snap_src", "snap_tgt"])
    assert code == 0
    assert called


# ---------------------------------------------------------------------------
# Shared registrar shape: stable atlas subcommand set
# ---------------------------------------------------------------------------

def _registered_atlas_subcommands() -> set:
    """Extract the set of atlas subcommand names from the shared registrar.

    This builds a parser and calls register_atlas_commands to verify the
    registrar state; it does not inspect the real repoground or repoground entry
    points, but rather tests the registered parser shape directly.
    """
    root = argparse.ArgumentParser()
    subs = root.add_subparsers(dest="command")
    # Both entry points ultimately call register_atlas_commands; we call
    # it directly here to verify the parser shape is identical.
    cmd_atlas_module.register_atlas_commands(subs)
    atlas_parser = subs.choices["atlas"]
    atlas_subs_action = next(a for a in atlas_parser._subparsers._group_actions if a.dest == "atlas_cmd")
    return set(atlas_subs_action.choices.keys())


def test_shared_registrar_subcommand_set_is_stable():
    """Shared registrar provides a stable, consistent set of atlas subcommands.

    This test verifies the registrar state directly, not the actual repoground or
    repoground entry-point parsers. Entry-point parity is verified by the dispatch
    tests (test_lenskit_dispatches_* / test_repoground_dispatches_*).
    """
    registered = _registered_atlas_subcommands()
    assert registered == _EXPECTED_ATLAS_SUBCOMMANDS


def test_handle_atlas_command_raises_on_unknown():
    """handle_atlas_command raises RuntimeError for unknown atlas_cmd values."""
    fake_args = argparse.Namespace(atlas_cmd="nonexistent_command_xyz")
    with pytest.raises(RuntimeError, match="Unexpected atlas command dispatch"):
        cmd_atlas_module.handle_atlas_command(fake_args)
