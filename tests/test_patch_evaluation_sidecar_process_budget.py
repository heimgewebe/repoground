from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "patch_evaluation_sidecar_process_budget.py"
SPEC = importlib.util.spec_from_file_location(
    "patch_evaluation_sidecar_process_budget_tested", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
process_budget = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(process_budget)


def _install(*, configured_budget: int = 256):
    prlimit = shutil.which("prlimit") or "/usr/bin/prlimit"
    legacy = SimpleNamespace(
        __file__=str(ROOT / "tools" / "patch_evaluation_sidecar_legacy.py"),
        EvaluationError=RuntimeError,
        _resolve_system_tool=lambda name: Path(prlimit),
    )
    hardening = SimpleNamespace(
        __file__=str(ROOT / "tools" / "patch_evaluation_sidecar_hardening.py"),
        _MAX_ADDRESS_SPACE_BYTES=4 * 1024 * 1024 * 1024,
        _MAX_COMMAND_FILE_BYTES=1024 * 1024 * 1024,
        _MAX_COMMAND_PROCESSES=configured_budget,
        _MAX_COMMAND_OPEN_FILES=1024,
    )
    host_readback = SimpleNamespace(
        __file__=str(ROOT / "tools" / "patch_evaluation_sidecar_host_readback.py")
    )
    process_budget.apply_process_budget(
        legacy,
        hardening,
        host_readback,
        wrapper_path=ROOT / "tools" / "patch_evaluation_sidecar.py",
    )
    return legacy, hardening


def _write_task_status(proc_root: Path, pid: str, tid: str, uid: int) -> None:
    directory = proc_root / pid / "task" / tid
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "status").write_text(
        f"Name:\ttest\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n",
        encoding="utf-8",
    )


def test_task_count_uses_each_thread_real_uid_and_ignores_proc_races(
    tmp_path: Path,
) -> None:
    _install()
    _write_task_status(tmp_path, "100", "100", 1000)
    _write_task_status(tmp_path, "100", "101", 1000)
    _write_task_status(tmp_path, "100", "102", 1001)
    _write_task_status(tmp_path, "200", "200", 1000)
    (tmp_path / "not-a-pid").mkdir()
    (tmp_path / "300" / "task" / "300").mkdir(parents=True)
    (tmp_path / "400").mkdir()  # process vanished before its task directory opened

    assert process_budget._count_real_uid_tasks(proc_root=tmp_path, real_uid=1000) == 3


def test_loaded_host_limit_is_baseline_plus_incremental_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(configured_budget=256)
    monkeypatch.setattr(process_budget, "_count_real_uid_tasks", lambda **_: 270)
    monkeypatch.setattr(process_budget, "_inherited_nproc_hard_limit", lambda: 31422)

    snapshot = process_budget._effective_nproc_limit()

    assert snapshot == {
        "real_uid_tasks": 270,
        "configured_incremental_budget": 256,
        "effective_incremental_budget": 256,
        "absolute_limit": 526,
        "inherited_hard_limit": 31422,
    }


def test_finite_inherited_hard_limit_only_reduces_headroom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(configured_budget=256)
    monkeypatch.setattr(process_budget, "_count_real_uid_tasks", lambda **_: 270)
    monkeypatch.setattr(process_budget, "_inherited_nproc_hard_limit", lambda: 300)

    snapshot = process_budget._effective_nproc_limit()

    assert snapshot["absolute_limit"] == 300
    assert snapshot["effective_incremental_budget"] == 30


def test_no_inherited_task_headroom_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(configured_budget=256)
    monkeypatch.setattr(process_budget, "_count_real_uid_tasks", lambda **_: 270)
    monkeypatch.setattr(process_budget, "_inherited_nproc_hard_limit", lambda: 270)

    with pytest.raises(RuntimeError, match="no task headroom remains"):
        process_budget._effective_nproc_limit()


def test_prlimit_argv_no_longer_uses_absolute_legacy_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(configured_budget=256)
    monkeypatch.setattr(process_budget, "_count_real_uid_tasks", lambda **_: 270)
    monkeypatch.setattr(process_budget, "_inherited_nproc_hard_limit", lambda: 31422)

    argv = process_budget._limited_sandbox_argv(["/usr/bin/true"], 10)

    assert "--nproc=526:526" in argv
    assert "--nproc=256" not in argv
    assert argv[-2:] == ["--", "/usr/bin/true"]


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_NPROC is Linux-specific")
@pytest.mark.skipif(os.getuid() == 0, reason="Linux does not enforce RLIMIT_NPROC for root")
def test_small_incremental_budget_rejects_fork_storm() -> None:
    _install(configured_budget=6)
    script = (
        "import subprocess,sys; children=[]; stopped=False\n"
        "try:\n"
        "  for _ in range(64):\n"
        "    try: children.append(subprocess.Popen([sys.executable,'-c','import time; time.sleep(2)']))\n"
        "    except OSError: stopped=True; break\n"
        "  print(len(children), int(stopped))\n"
        "finally:\n"
        "  [p.terminate() for p in children]\n"
        "  [p.wait(timeout=5) for p in children]\n"
    )
    argv = process_budget._limited_sandbox_argv([sys.executable, "-c", script], 10)

    completed = subprocess.run(
        argv,
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )
    spawned, stopped = map(int, completed.stdout.split())

    assert stopped == 1
    assert spawned < 64
