"""Loaded-host process-budget overlay for the patch evaluation sidecar.

Linux ``RLIMIT_NPROC`` is counted against the real user ID and, more precisely,
counts threads rather than only process leaders.  An absolute value such as 256
therefore prevents a sandbox from starting when the operator user already owns
at least 256 tasks.

This overlay keeps the same configured command budget, but translates it to an
absolute limit at launch time: current real-UID task count plus the bounded
incremental budget.  The value is clamped to the inherited hard limit.  This is
fail-closed under concurrent host growth and deliberately does not claim a
strict per-command kernel quota, which RLIMIT_NPROC cannot provide.
"""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
from typing import Any, Sequence

try:
    import resource
except ImportError:  # pragma: no cover - the sidecar is Linux-only
    resource = None  # type: ignore[assignment]

_LEGACY: Any = None
_HARDENING: Any = None
_HOST_READBACK: Any = None
_WRAPPER_PATH: Path | None = None


def _m() -> Any:
    if _LEGACY is None or _HARDENING is None:
        raise RuntimeError("process-budget hardening has not been installed")
    return _LEGACY


def _evaluation_error(message: str) -> Exception:
    legacy = _m()
    error_type = getattr(legacy, "EvaluationError", RuntimeError)
    return error_type(message)


def _status_real_uid(status_path: Path) -> int | None:
    try:
        status = status_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in status.splitlines():
        if not line.startswith("Uid:"):
            continue
        fields = line.split()
        if len(fields) < 2:
            return None
        try:
            return int(fields[1])
        except ValueError:
            return None
    return None


def _count_real_uid_tasks(
    *, proc_root: Path = Path("/proc"), real_uid: int | None = None
) -> int:
    """Count visible Linux tasks whose real UID matches ``real_uid``.

    ``RLIMIT_NPROC`` accounts threads.  Therefore each ``/proc/<pid>/task/<tid>``
    entry is inspected rather than counting only top-level process directories.
    ``/proc`` changes while it is scanned; vanished or unreadable entries are
    ignored.  Any resulting undercount lowers the computed absolute limit and
    can only consume sidecar headroom, so the race remains fail-closed.
    """

    uid = os.getuid() if real_uid is None else real_uid
    count = 0
    try:
        processes = list(proc_root.iterdir())
    except OSError as exc:
        raise _evaluation_error(f"could not inspect process table: {exc}") from exc

    for process in processes:
        if not process.name.isdigit():
            continue
        try:
            tasks = list((process / "task").iterdir())
        except OSError:
            continue
        for task in tasks:
            if not task.name.isdigit():
                continue
            if _status_real_uid(task / "status") == uid:
                count += 1
    return count


def _inherited_nproc_hard_limit() -> int | None:
    if resource is None or not hasattr(resource, "RLIMIT_NPROC"):
        raise _evaluation_error("RLIMIT_NPROC is unavailable on this platform")
    _soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
    if hard == resource.RLIM_INFINITY:
        return None
    return int(hard)


def _effective_nproc_limit(
    *, proc_root: Path = Path("/proc"), real_uid: int | None = None
) -> dict[str, int | None]:
    """Return the absolute RLIMIT_NPROC derived from current host load.

    The configured value remains an incremental task budget.  A finite inherited
    hard limit may reduce that budget, but it is never raised or bypassed.
    """

    hardening = _HARDENING
    if hardening is None:
        raise RuntimeError("process-budget hardening has not been installed")

    configured_budget = int(hardening._MAX_COMMAND_PROCESSES)
    if configured_budget <= 0:
        raise _evaluation_error("configured command task budget must be positive")

    baseline = _count_real_uid_tasks(proc_root=proc_root, real_uid=real_uid)
    inherited_hard = _inherited_nproc_hard_limit()
    requested_limit = baseline + configured_budget
    absolute_limit = (
        requested_limit
        if inherited_hard is None
        else min(requested_limit, inherited_hard)
    )
    effective_budget = absolute_limit - baseline
    if effective_budget <= 0:
        hard_label = "unlimited" if inherited_hard is None else str(inherited_hard)
        raise _evaluation_error(
            "no task headroom remains for the sandbox "
            f"(real_uid_tasks={baseline}, inherited_hard_limit={hard_label})"
        )

    return {
        "real_uid_tasks": baseline,
        "configured_incremental_budget": configured_budget,
        "effective_incremental_budget": effective_budget,
        "absolute_limit": absolute_limit,
        "inherited_hard_limit": inherited_hard,
    }


def _limited_sandbox_argv(argv: Sequence[str], timeout_seconds: float) -> list[str]:
    legacy = _m()
    hardening = _HARDENING
    assert hardening is not None

    prlimit = legacy._resolve_system_tool("prlimit")
    process_limit = _effective_nproc_limit()["absolute_limit"]
    assert isinstance(process_limit, int)
    cpu_seconds = max(2, int(math.ceil(timeout_seconds)) + 2)
    return [
        str(prlimit),
        f"--as={hardening._MAX_ADDRESS_SPACE_BYTES}",
        f"--fsize={hardening._MAX_COMMAND_FILE_BYTES}",
        f"--nproc={process_limit}:{process_limit}",
        f"--nofile={hardening._MAX_COMMAND_OPEN_FILES}",
        f"--cpu={cpu_seconds}",
        "--",
        *argv,
    ]


def _producer_digest() -> str:
    legacy = _m()
    hardening = _HARDENING
    host_readback = _HOST_READBACK
    wrapper_path = _WRAPPER_PATH
    if hardening is None or host_readback is None or wrapper_path is None:
        raise RuntimeError("process-budget producer identity is incomplete")

    digest = hashlib.sha256()
    paths = {
        Path(legacy.__file__).resolve(),
        Path(hardening.__file__).resolve(),
        Path(host_readback.__file__).resolve(),
        Path(__file__).resolve(),
        wrapper_path.resolve(),
    }
    for path in sorted(paths, key=str):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def apply_process_budget(
    legacy: Any,
    hardening: Any,
    host_readback: Any,
    *,
    wrapper_path: str | Path,
) -> None:
    """Install the process-budget overlay after the other sidecar overlays."""

    global _LEGACY, _HARDENING, _HOST_READBACK, _WRAPPER_PATH
    _LEGACY = legacy
    _HARDENING = hardening
    _HOST_READBACK = host_readback
    _WRAPPER_PATH = Path(wrapper_path)

    hardening._limited_sandbox_argv = _limited_sandbox_argv
    legacy._limited_sandbox_argv = _limited_sandbox_argv
    hardening._producer_digest = _producer_digest
    legacy._producer_digest = _producer_digest
