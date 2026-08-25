import json
import threading
from pathlib import Path
import pytest

from merger.repoground.core import mcp_tools
from merger.repoground.core import bundle_access


class FakeArtifacts:
    def __init__(self, manifest: Path):
        self.bundle_manifest = manifest
        self.canonical_md = manifest.with_name("brief.md")
        self.canonical_md.write_text("# brief\n", encoding="utf-8")

    def get_all_paths(self):
        return [self.bundle_manifest, self.canonical_md]


def test_mcp_snapshot_create_dispatches_existing_generator_with_guards(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    output_root = tmp_path / "brief-root"
    calls = {}

    def fake_scan_repo(*args, **kwargs):
        calls["scan"] = {"args": args, "kwargs": kwargs}
        return {"name": "repo", "root": repo, "files": [], "total_files": 0, "total_bytes": 0, "ext_hist": {}}

    def fake_write_reports_v2(*args, **kwargs):
        calls["write"] = {"args": args, "kwargs": kwargs}
        out = args[0]
        manifest = out / "repo_merge.bundle.manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps({"kind": "repolens.bundle.manifest", "capabilities": {}, "artifacts": []}),
            encoding="utf-8",
        )
        return FakeArtifacts(manifest)

    from merger.repoground.cli import cmd_ground

    monkeypatch.setattr(cmd_ground, "scan_repo", fake_scan_repo)
    monkeypatch.setattr(cmd_ground, "write_reports_v2", fake_write_reports_v2)

    result = mcp_tools.snapshot_create(
        repo=repo,
        output_root=output_root,
        output_subdir="run-1",
        profile="agent-portable",
        timeout_seconds=30,
        max_total_bytes="1MB",
    )

    assert result["kind"] == "repobrief.mcp.snapshot_create"
    assert result["status"] == "ok"
    assert result["mutation_boundary"]["explicit_write_tool"] is True
    assert result["mutation_boundary"]["not_reachable_from_read_tools"] is True
    assert result["mutation_boundary"]["writes"] == ["brief_bundle_artifacts"]
    assert "git_push" in result["mutation_boundary"]["forbidden_operations"]
    assert result["created_snapshot"]["command"] == "repoground snapshot create"
    assert result["created_snapshot"]["mutation_boundary"]["read_paths_do_not_refresh"] is True
    assert calls["scan"]["args"][0] == repo.resolve()
    assert calls["scan"]["kwargs"]["include_hidden"] is False
    assert calls["write"]["kwargs"]["generator_info"]["platform"] == "mcp-explicit-tool"
    assert calls["write"]["args"][0] == (output_root / "run-1").resolve()
    assert "mcp_server_available" in result["does_not_establish"]


def test_mcp_snapshot_create_rejects_output_inside_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(mcp_tools.RepoGroundMcpToolError, match="inside"):
        mcp_tools.snapshot_create(
            repo=repo,
            output_root=repo / "briefs",
            profile="agent-portable",
        )


def test_mcp_snapshot_create_rejects_relative_escape_subdir(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    output_root = tmp_path / "briefs"

    with pytest.raises(mcp_tools.RepoGroundMcpToolError, match="relative"):
        mcp_tools.snapshot_create(
            repo=repo,
            output_root=output_root,
            output_subdir="../escape",
            profile="agent-portable",
        )


def test_mcp_snapshot_create_rejects_oversized_repo_before_writes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "big.txt").write_bytes(b"x" * 64)
    output_root = tmp_path / "briefs"

    with pytest.raises(mcp_tools.RepoGroundMcpToolError, match="exceeds"):
        mcp_tools.snapshot_create(
            repo=repo,
            output_root=output_root,
            profile="agent-portable",
            max_total_bytes="32",
        )
    assert not output_root.exists()


def test_mcp_snapshot_create_rejects_timeout_above_guard(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    output_root = tmp_path / "briefs"

    with pytest.raises(mcp_tools.RepoGroundMcpToolError, match="timeout_seconds"):
        mcp_tools.snapshot_create(
            repo=repo,
            output_root=output_root,
            profile="agent-portable",
            timeout_seconds=mcp_tools.MAX_TIMEOUT_SECONDS + 1,
        )


def _stub_timeout_signals(
    monkeypatch, *, previous_timer, previous_handler=None, now=100.0
):
    if previous_handler is None:
        previous_handler = object()
    clock = {"now": now}
    state = {"handler": previous_handler, "timer": previous_timer}
    timer_calls = []
    handler_calls = []

    def fake_setitimer(which, delay, interval=0.0):
        previous = state["timer"]
        state["timer"] = (float(delay), float(interval))
        timer_calls.append((which, float(delay), float(interval)))
        return previous

    def fake_getitimer(which):
        assert which == mcp_tools.signal.ITIMER_REAL
        return state["timer"]

    def fake_signal(signum, handler):
        previous = state["handler"]
        state["handler"] = handler
        handler_calls.append((signum, handler))
        return previous

    monkeypatch.setattr(mcp_tools.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(mcp_tools.signal, "getsignal", lambda _signum: state["handler"])
    monkeypatch.setattr(mcp_tools.signal, "signal", fake_signal)
    monkeypatch.setattr(mcp_tools.signal, "setitimer", fake_setitimer)
    monkeypatch.setattr(mcp_tools.signal, "getitimer", fake_getitimer)
    return previous_handler, clock, state, timer_calls, handler_calls


def test_timeout_guard_subtracts_elapsed_time_from_later_outer_timer(monkeypatch):
    previous_handler, clock, state, _timer_calls, _handler_calls = _stub_timeout_signals(
        monkeypatch, previous_timer=(10.0, 0.0)
    )

    with mcp_tools._timeout_guard(5):
        assert state["timer"] == (5.0, 0.0)
        clock["now"] = 102.5

    assert state["timer"] == (pytest.approx(7.5), 0.0)
    assert state["handler"] is previous_handler


def test_timeout_guard_keeps_earlier_outer_deadline_armed(monkeypatch):
    fired = []
    clock = None

    def outer_handler(_signum, _frame):
        fired.append(clock["now"])

    _previous_handler, clock, state, _timer_calls, _handler_calls = _stub_timeout_signals(
        monkeypatch, previous_timer=(2.0, 0.0), previous_handler=outer_handler
    )

    with mcp_tools._timeout_guard(5):
        assert state["timer"] == (2.0, 0.0)
        clock["now"] = 102.0
        state["timer"] = (0.0, 0.0)
        state["handler"](mcp_tools.signal.SIGALRM, None)
        assert fired == [102.0]
        assert state["timer"] == (pytest.approx(3.0), 0.0)

    assert state["timer"] == (0.0, 0.0)
    assert state["handler"] is outer_handler


def test_timeout_guard_preserves_native_periodic_outer_timer(monkeypatch):
    fired = []
    clock = None

    def outer_handler(_signum, _frame):
        fired.append(clock["now"])

    _previous_handler, clock, state, _timer_calls, _handler_calls = _stub_timeout_signals(
        monkeypatch, previous_timer=(1.0, 0.25), previous_handler=outer_handler
    )

    with mcp_tools._timeout_guard(5):
        assert state["timer"] == (1.0, 0.25)
        clock["now"] = 101.0
        state["timer"] = (0.25, 0.25)
        state["handler"](mcp_tools.signal.SIGALRM, None)
        assert fired == [101.0]
        assert state["timer"] == (0.25, 0.25)
        assert state["handler"] is not outer_handler
        clock["now"] = 101.1
        state["timer"] = (0.15, 0.25)

    assert state["timer"] == (pytest.approx(0.15), 0.25)
    assert state["handler"] is outer_handler


def test_timeout_guard_propagates_earlier_outer_handler_exception(monkeypatch):
    class OuterDeadlineExpired(RuntimeError):
        pass

    clock = None

    def outer_handler(_signum, _frame):
        raise OuterDeadlineExpired("outer deadline")

    _previous_handler, clock, state, _timer_calls, _handler_calls = _stub_timeout_signals(
        monkeypatch, previous_timer=(1.0, 0.0), previous_handler=outer_handler
    )

    with pytest.raises(OuterDeadlineExpired, match="outer deadline"):
        with mcp_tools._timeout_guard(5):
            clock["now"] = 101.0
            state["timer"] = (0.0, 0.0)
            state["handler"](mcp_tools.signal.SIGALRM, None)

    assert state["timer"] == (0.0, 0.0)
    assert state["handler"] is outer_handler


def test_timeout_guard_restores_later_outer_timer_when_body_raises(monkeypatch):
    previous_handler, clock, state, _timer_calls, _handler_calls = _stub_timeout_signals(
        monkeypatch, previous_timer=(10.0, 0.0)
    )

    with pytest.raises(RuntimeError, match="boom"):
        with mcp_tools._timeout_guard(5):
            clock["now"] = 100.5
            raise RuntimeError("boom")

    assert state["timer"] == (pytest.approx(9.5), 0.0)
    assert state["handler"] is previous_handler


def test_timeout_guard_still_rejects_non_main_thread():
    errors = []

    def run_guard():
        try:
            with mcp_tools._timeout_guard(1):
                pass
        except Exception as exc:  # pragma: no branch - exactly one expected path
            errors.append(exc)

    thread = threading.Thread(target=run_guard)
    thread.start()
    thread.join()

    assert len(errors) == 1
    assert isinstance(errors[0], mcp_tools.RepoGroundMcpToolError)
    assert "main thread" in str(errors[0])


def test_read_only_access_does_not_trigger_mcp_snapshot_create(monkeypatch, tmp_path):
    artifact = tmp_path / "demo.md"
    artifact.write_text("# demo\n", encoding="utf-8")
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "artifacts": [{"role": "canonical_md", "path": artifact.name}],
                "capabilities": {},
            }
        ),
        encoding="utf-8",
    )

    def forbidden_call(**_kwargs):
        raise AssertionError("read-only access must not call snapshot_create")

    monkeypatch.setattr(mcp_tools, "snapshot_create", forbidden_call)

    status = bundle_access.snapshot_status(manifest)
    found = bundle_access.get_artifact(manifest, "canonical_md")

    assert status["mutation_boundary"]["writes"] == []
    assert status["mutation_boundary"]["read_paths_do_not_refresh"] is True
    assert found["status"] == "available"
