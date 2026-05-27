"""Tests for the centralized Atlas CLI registrar (register_atlas_commands /
handle_atlas_command in cmd_atlas.py).

Scope:
- Both lenskit (cli/main.py) and rlens (cli/rlens.py) consume the same
  registrar, so every subcommand only needs to be defined once.
- These tests verify: shared registrar shape (stable atlas subcommand set),
  dispatch via lenskit for `machines`, dispatch via rlens for `machines`,
  and the `analyze growth` positional args are wired correctly.
"""
import argparse
import sys
import pytest

from merger.lenskit.cli import cmd_atlas as cmd_atlas_module
from merger.lenskit.cli.main import main as lenskit_main
from merger.lenskit.cli.rlens import main as rlens_main


_EXPECTED_ATLAS_SUBCOMMANDS = {
    "scan",
    "machine-health",
    "machines",
    "roots",
    "snapshots",
    "diff",
    "history",
    "search",
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
# Dispatch tests via lenskit_main
# ---------------------------------------------------------------------------

def test_lenskit_dispatches_atlas_machines(monkeypatch):
    """lenskit atlas machines routes to run_atlas_machines via handle_atlas_command."""
    called = False

    def mock_run_machines(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "machines"
        return 0

    monkeypatch.setattr(cmd_atlas_module, "run_atlas_machines", mock_run_machines)

    exit_code = lenskit_main(["atlas", "machines"])
    assert exit_code == 0
    assert called


def test_lenskit_dispatches_atlas_machine_health(monkeypatch):
    """lenskit atlas machine-health routes to run_atlas_machine_health."""
    called = False

    def mock_handler(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "machine-health"
        return 0

    monkeypatch.setattr(cmd_atlas_module, "run_atlas_machine_health", mock_handler)

    exit_code = lenskit_main(["atlas", "machine-health"])
    assert exit_code == 0
    assert called


def test_lenskit_dispatches_atlas_analyze_growth(monkeypatch):
    """lenskit atlas analyze growth <src> <tgt> parses positional args correctly."""
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

    exit_code = lenskit_main(["atlas", "analyze", "growth", "snap_src", "snap_tgt"])
    assert exit_code == 0
    assert called


# ---------------------------------------------------------------------------
# Dispatch tests via rlens_main
# ---------------------------------------------------------------------------

def _run_rlens(monkeypatch, argv):
    """Run rlens_main with a given argv, catching SystemExit, and return exit code."""
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        rlens_main()
    return exc.value.code


def test_rlens_dispatches_atlas_machines(monkeypatch):
    """rlens atlas machines routes to run_atlas_machines via handle_atlas_command."""
    called = False

    def mock_run_machines(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "machines"
        return 0

    monkeypatch.setattr(cmd_atlas_module, "run_atlas_machines", mock_run_machines)

    code = _run_rlens(monkeypatch, ["rlens", "atlas", "machines"])
    assert code == 0
    assert called


def test_rlens_dispatches_atlas_machine_health(monkeypatch):
    """rlens atlas machine-health routes to run_atlas_machine_health."""
    called = False

    def mock_handler(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "machine-health"
        return 0

    monkeypatch.setattr(cmd_atlas_module, "run_atlas_machine_health", mock_handler)

    code = _run_rlens(monkeypatch, ["rlens", "atlas", "machine-health"])
    assert code == 0
    assert called


def test_rlens_dispatches_atlas_analyze_growth(monkeypatch):
    """rlens atlas analyze growth <src> <tgt> parses positional args correctly."""
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

    code = _run_rlens(monkeypatch, ["rlens", "atlas", "analyze", "growth", "snap_src", "snap_tgt"])
    assert code == 0
    assert called


# ---------------------------------------------------------------------------
# Shared registrar shape: stable atlas subcommand set
# ---------------------------------------------------------------------------

def _registered_atlas_subcommands() -> set:
    """Extract the set of atlas subcommand names from the shared registrar.

    This builds a parser and calls register_atlas_commands to verify the
    registrar state; it does not inspect the real lenskit or rlens entry
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

    This test verifies the registrar state directly, not the actual lenskit or
    rlens entry-point parsers. Entry-point parity is verified by the dispatch
    tests (test_lenskit_dispatches_* / test_rlens_dispatches_*).
    """
    registered = _registered_atlas_subcommands()
    assert registered == _EXPECTED_ATLAS_SUBCOMMANDS


def test_handle_atlas_command_raises_on_unknown():
    """handle_atlas_command raises RuntimeError for unknown atlas_cmd values."""
    fake_args = argparse.Namespace(atlas_cmd="nonexistent_command_xyz")
    with pytest.raises(RuntimeError, match="Unexpected atlas command dispatch"):
        cmd_atlas_module.handle_atlas_command(fake_args)
