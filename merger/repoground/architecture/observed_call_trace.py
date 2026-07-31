"""Run-bound recording of observed Python calls (S2 evidence).

The recorder watches one execution of one command with :func:`sys.setprofile`
and keeps the raw runtime coordinates of every call whose *callee* lives inside
the observed repository. Nothing here resolves symbols, compares against the
static call graph or interprets absence; that separation keeps the executing
part of the overlay as small and as dumb as possible.

RepoGround does not execute target code as part of bundle generation. This
module is an explicitly operator-invoked producer: it runs only when somebody
asks for a trace of a named command, and its output is a separate artifact that
never enters the static bundle pipeline.

Tracing is necessarily in-process, because ``sys.setprofile`` only observes the
interpreter it is installed in. The traced command therefore runs with this
interpreter's side effects: the working directory, ``sys.argv`` and ``sys.path``
are restored afterwards, but whatever the command imported stays in
``sys.modules``, and whatever it wrote stays written. A second trace in the same
process would see cached modules instead of re-executing their bodies, so each
overlay should be produced by a fresh ``repoground observed-calls produce``
invocation.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import runpy
import subprocess
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Iterator, Sequence

from .observed_call_overlay_contract import MAX_SKIPPED_ERRORS

MODULE_FRAME_NAME = "<module>"


@dataclass(frozen=True)
class ObservedEdgeKey:
    """Raw runtime coordinates of one observed caller/callee pair."""

    caller_path: str | None
    caller_name: str
    caller_first_line: int
    call_line: int
    callee_path: str
    callee_name: str
    callee_first_line: int

    def sort_key(self) -> tuple[Any, ...]:
        return (
            self.callee_path,
            self.callee_first_line,
            self.callee_name,
            self.caller_path or "",
            self.caller_first_line,
            self.call_line,
            self.caller_name,
        )


@dataclass(frozen=True)
class TraceResult:
    """Everything one traced execution establishes."""

    edges: dict[ObservedEdgeKey, int]
    command: list[str]
    exit_status: str
    exit_code: int | None
    frame_event_count: int
    skipped_errors: tuple[str, ...]
    skipped_errors_total_count: int


def _repo_relative(repo_root: Path, filename: str) -> str | None:
    """Return the repo-relative POSIX path of ``filename`` or ``None``.

    Runtime code objects carry whatever path the importer used, so the value is
    normalised before comparison. Anything outside the repository (stdlib, site
    packages, generated temporaries) is deliberately dropped rather than guessed
    into the repository namespace.
    """

    if not filename or filename.startswith("<"):
        return None
    try:
        resolved = Path(filename).resolve()
        relative = resolved.relative_to(repo_root)
    except (OSError, ValueError):
        return None
    return relative.as_posix()


class _CallObserver:
    """``sys.setprofile`` callback that aggregates repo-local call edges.

    CPython disables profiling while the profile callback itself runs, so the
    work done here never observes itself and never recurses within a thread.
    Threads started by the traced command run the same callback concurrently,
    so the aggregation is guarded: the read-modify-write of an edge counter is
    not atomic under the GIL and would otherwise undercount.
    """

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root
        self._path_cache: dict[str, str | None] = {}
        self._lock = Lock()
        self.edges: dict[ObservedEdgeKey, int] = {}
        self.frame_event_count = 0

    def _relative(self, filename: str) -> str | None:
        if filename not in self._path_cache:
            self._path_cache[filename] = _repo_relative(self._repo_root, filename)
        return self._path_cache[filename]

    def __call__(self, frame: Any, event: str, arg: Any) -> None:
        # 'c_call' events describe builtins, which have no repository symbol to
        # bind to. Only Python frames can carry S2 evidence for this repository.
        if event != "call":
            return
        callee_code = frame.f_code
        with self._lock:
            callee_path = self._relative(callee_code.co_filename)
        if callee_path is None:
            return
        caller_frame = frame.f_back
        if caller_frame is None:
            caller_path: str | None = None
            caller_name = MODULE_FRAME_NAME
            caller_first_line = 0
            call_line = 0
        else:
            caller_code = caller_frame.f_code
            with self._lock:
                caller_path = self._relative(caller_code.co_filename)
            caller_name = caller_code.co_name
            caller_first_line = caller_code.co_firstlineno
            call_line = caller_frame.f_lineno
        key = ObservedEdgeKey(
            caller_path=caller_path,
            caller_name=caller_name,
            caller_first_line=caller_first_line,
            call_line=call_line,
            callee_path=callee_path,
            callee_name=callee_code.co_name,
            callee_first_line=callee_code.co_firstlineno,
        )
        with self._lock:
            self.frame_event_count += 1
            self.edges[key] = self.edges.get(key, 0) + 1


@contextmanager
def _profiling(observer: _CallObserver) -> Iterator[None]:
    """Profile this thread and every thread the traced command starts.

    ``threading.setprofile`` only reaches threads created *after* it is
    installed. Threads that were already running when the trace began, and
    frames executed inside native extensions, stay unobserved; both limits are
    named in the overlay's non-claims.
    """

    previous = sys.getprofile()
    sys.setprofile(observer)
    threading.setprofile(observer)
    try:
        yield
    finally:
        threading.setprofile(None)
        sys.setprofile(previous)


@contextmanager
def _process_context(repo_root: Path, argv: Sequence[str]) -> Iterator[None]:
    previous_cwd = Path.cwd()
    previous_argv = list(sys.argv)
    previous_path = list(sys.path)
    os.chdir(repo_root)
    sys.argv = list(argv)
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        yield
    finally:
        sys.path[:] = previous_path
        sys.argv = previous_argv
        os.chdir(previous_cwd)


def _run_command(repo_root: Path, command: Sequence[str]) -> tuple[str, int | None, str | None]:
    """Execute ``command`` in-process and report how it ended.

    Supported forms are ``["-m", "module", ...]`` and ``["script.py", ...]``.
    A non-zero exit or an escaping exception is recorded, never raised: a
    partially exercised command still produced real observations, and hiding
    the failure would be the dishonest option.
    """

    if not command:
        raise ValueError("command must not be empty")
    if command[0] == "-m":
        if len(command) < 2:
            raise ValueError("command '-m' requires a module name")
        target_module = command[1]
        argv = [target_module, *command[2:]]
        runner = lambda: runpy.run_module(  # noqa: E731 - one call site, kept local
            target_module, run_name="__main__", alter_sys=True
        )
    else:
        script = (repo_root / command[0]).resolve()
        argv = [str(script), *command[1:]]
        runner = lambda: runpy.run_path(str(script), run_name="__main__")  # noqa: E731
    with _process_context(repo_root, argv):
        try:
            runner()
        except SystemExit as exc:
            code = exc.code
            if code is None:
                return "exited", 0, None
            if isinstance(code, int):
                return "exited", code, None
            return "exited", 1, f"SystemExit: {code}"
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            # KeyboardInterrupt and GeneratorExit deliberately propagate: an
            # operator aborting a long trace must abort it, not record it.
            return "failed", None, f"{type(exc).__name__}: {exc}"
    return "completed", 0, None


def trace_command(repo_root: Path, command: Sequence[str]) -> TraceResult:
    """Observe one execution of ``command`` rooted at ``repo_root``."""

    repo_root = repo_root.resolve()
    observer = _CallObserver(repo_root)
    skipped_errors: list[str] = []
    with _profiling(observer):
        status, exit_code, failure = _run_command(repo_root, command)
    if failure is not None:
        skipped_errors.append(failure)
    return TraceResult(
        edges=dict(observer.edges),
        command=list(command),
        exit_status=status,
        exit_code=exit_code,
        frame_event_count=observer.frame_event_count,
        skipped_errors=tuple(skipped_errors[:MAX_SKIPPED_ERRORS]),
        skipped_errors_total_count=len(skipped_errors),
    )


def source_revision(repo_root: Path) -> dict[str, Any]:
    """Return the Git revision the observation is bound to.

    An observation that cannot name its source revision is not an S2 record,
    so an unresolvable revision is reported as such and the caller decides.
    """

    def _git(*args: str) -> str | None:
        try:
            completed = subprocess.run(
                ["git", "-C", str(repo_root), *args],
                capture_output=True,
                text=True,
                check=False,
            )
        except (OSError, ValueError):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip()

    commit = _git("rev-parse", "HEAD")
    if commit is None or len(commit) != 40:
        return {"vcs": "git", "commit": None, "dirty": None, "status": "unavailable"}
    porcelain = _git("status", "--porcelain")
    if porcelain is None:
        return {"vcs": "git", "commit": commit, "dirty": None, "status": "unavailable"}
    dirty = bool(porcelain)
    return {
        "vcs": "git",
        "commit": commit,
        "dirty": dirty,
        "status": "dirty" if dirty else "clean",
    }


def environment_identity() -> dict[str, Any]:
    """Return the interpreter environment the observation was made in."""

    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(terse=True),
        "executable": sys.executable,
        "hash_randomization_seed": os.environ.get("PYTHONHASHSEED"),
    }


def observation_identity(
    *,
    command: Sequence[str],
    environment: dict[str, Any],
    revision: dict[str, Any],
    observed_at: str | None = None,
    observation_run_id: str | None = None,
) -> dict[str, Any]:
    """Bind one observation to command, environment, run identity and revision."""

    moment = observed_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "command": list(command),
                "environment": environment,
                "revision": revision,
                "observed_at": moment,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "observation_run_id": observation_run_id or f"OBS-{moment}-{fingerprint[:12]}",
        "observed_at": moment,
        "command": list(command),
        "command_string": " ".join(command),
        "environment": environment,
        "source_revision": revision,
        "observation_fingerprint_sha256": fingerprint,
    }
