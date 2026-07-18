import pytest
from merger.repoground.cli.main import main as repoground_main
from merger.repoground.cli.serve import main as service_launcher_main

def test_repoground_main_parses_atlas_analyze_duplicates(monkeypatch):
    """Verifies that `repoground atlas analyze duplicates <id>` routes correctly."""
    called = False

    def mock_run_analyze(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "analyze"
        assert args.analyze_command == "duplicates"
        assert args.snapshot_id == "snap_test_123"
        return 0

    import merger.repoground.cli.cmd_atlas
    monkeypatch.setattr(merger.repoground.cli.cmd_atlas, "run_atlas_analyze", mock_run_analyze)

    exit_code = repoground_main(["atlas", "analyze", "duplicates", "snap_test_123"])
    assert exit_code == 0
    assert called

def test_service_launcher_parses_atlas_analyze_duplicates(monkeypatch):
    """Verifies that `repoground atlas analyze duplicates <id>` routes correctly."""
    called = False

    def mock_run_analyze(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "analyze"
        assert args.analyze_command == "duplicates"
        assert args.snapshot_id == "snap_test_123"
        return 0

    import merger.repoground.cli.cmd_atlas
    monkeypatch.setattr(merger.repoground.cli.cmd_atlas, "run_atlas_analyze", mock_run_analyze)

    # repoground exit strategy uses sys.exit, so we need to catch it
    # We also need to patch sys.argv because service_launcher_main() takes no arguments
    import sys
    monkeypatch.setattr(sys, "argv", ["repoground", "atlas", "analyze", "duplicates", "snap_test_123"])

    with pytest.raises(SystemExit) as excinfo:
        service_launcher_main()

    assert excinfo.value.code == 0
    assert called


def test_repoground_main_parses_atlas_analyze_orphans(monkeypatch):
    called = False
    def mock_run_analyze(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "analyze"
        assert args.analyze_command == "orphans"
        assert args.snapshot_id == "snap_test_123"
        return 0

    import merger.repoground.cli.cmd_atlas
    monkeypatch.setattr(merger.repoground.cli.cmd_atlas, "run_atlas_analyze", mock_run_analyze)

    exit_code = repoground_main(["atlas", "analyze", "orphans", "snap_test_123"])
    assert exit_code == 0
    assert called

def test_service_launcher_parses_atlas_analyze_orphans(monkeypatch):
    called = False
    def mock_run_analyze(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "analyze"
        assert args.analyze_command == "orphans"
        assert args.snapshot_id == "snap_test_123"
        return 0

    import merger.repoground.cli.cmd_atlas
    monkeypatch.setattr(merger.repoground.cli.cmd_atlas, "run_atlas_analyze", mock_run_analyze)

    import sys
    monkeypatch.setattr(sys, "argv", ["repoground", "atlas", "analyze", "orphans", "snap_test_123"])

    with pytest.raises(SystemExit) as excinfo:
        service_launcher_main()

    assert excinfo.value.code == 0
    assert called

def test_repoground_main_parses_atlas_analyze_disk(monkeypatch):
    called = False
    def mock_run_analyze(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "analyze"
        assert args.analyze_command == "disk"
        assert args.snapshot_id == "snap_test_123"
        return 0

    import merger.repoground.cli.cmd_atlas
    monkeypatch.setattr(merger.repoground.cli.cmd_atlas, "run_atlas_analyze", mock_run_analyze)

    exit_code = repoground_main(["atlas", "analyze", "disk", "snap_test_123"])
    assert exit_code == 0
    assert called

def test_service_launcher_parses_atlas_analyze_disk(monkeypatch):
    called = False
    def mock_run_analyze(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "analyze"
        assert args.analyze_command == "disk"
        assert args.snapshot_id == "snap_test_123"
        return 0

    import merger.repoground.cli.cmd_atlas
    monkeypatch.setattr(merger.repoground.cli.cmd_atlas, "run_atlas_analyze", mock_run_analyze)

    import sys
    monkeypatch.setattr(sys, "argv", ["repoground", "atlas", "analyze", "disk", "snap_test_123"])

    with pytest.raises(SystemExit) as excinfo:
        service_launcher_main()

    assert excinfo.value.code == 0
    assert called

def test_repoground_main_parses_atlas_analyze_growth(monkeypatch):
    called = False
    def mock_run_analyze(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "analyze"
        assert args.analyze_command == "growth"
        assert args.source_snapshot == "snap_src_123"
        assert args.target_snapshot == "snap_tgt_123"
        return 0

    import merger.repoground.cli.cmd_atlas
    monkeypatch.setattr(merger.repoground.cli.cmd_atlas, "run_atlas_analyze", mock_run_analyze)

    exit_code = repoground_main(["atlas", "analyze", "growth", "snap_src_123", "snap_tgt_123"])
    assert exit_code == 0
    assert called

def test_service_launcher_parses_atlas_analyze_growth(monkeypatch):
    called = False
    def mock_run_analyze(args):
        nonlocal called
        called = True
        assert args.atlas_cmd == "analyze"
        assert args.analyze_command == "growth"
        assert args.source_snapshot == "snap_src_123"
        assert args.target_snapshot == "snap_tgt_123"
        return 0

    import merger.repoground.cli.cmd_atlas
    monkeypatch.setattr(merger.repoground.cli.cmd_atlas, "run_atlas_analyze", mock_run_analyze)

    import sys
    monkeypatch.setattr(sys, "argv", ["repoground", "atlas", "analyze", "growth", "snap_src_123", "snap_tgt_123"])

    with pytest.raises(SystemExit) as excinfo:
        service_launcher_main()

    assert excinfo.value.code == 0
    assert called
