"""Support functions for the systemd patch-evaluation runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

KIND = "repoground.patch_evaluation_runner_receipt"
VERSION = "v1"
AUTHORITY = "external_runtime_evidence"
PRODUCER_NAME = "repoground-systemd-patch-evaluation-runner"
PRODUCER_VERSION = "0.1.0"
_REQUIRED_CONTROLLERS = frozenset({"cpu", "memory", "pids", "io"})
_RESOURCE_RESULTS = frozenset(
    {"oom-kill", "timeout", "watchdog", "resources", "signal", "core-dump"}
)
_MAX_REQUEST_BYTES = 1_000_000
_MAX_PATCH_BYTES = 100_000_000
_SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


class RunnerError(RuntimeError):
    """The production runner could not establish trustworthy evidence."""


@dataclass(frozen=True)
class Limits:
    workspace: int
    memory: int
    swap: int
    cpu_percent: int
    tasks: int
    runtime: int
    read_bps: int
    write_bps: int

    @property
    def cpu_time_usec(self) -> int:
        return self.runtime * self.cpu_percent * 10_000

    def read_total(self, devices: int) -> int:
        return self.runtime * self.read_bps * devices

    def write_total(self, devices: int) -> int:
        return self.runtime * self.write_bps * devices


@dataclass(frozen=True)
class Run:
    unit: str
    request: Path
    patch: Path
    staging: Path
    staging_identity: tuple[int, int]
    output: Path
    receipt: Path
    output_identity: tuple[int, int]
    repository: Path
    devices: tuple[Path, ...]
    source_request: Path
    source_request_sha256: str
    effective_request_sha256: str
    patch_sha256: str


def _bounded(value: int, name: str, low: int, high: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not low <= value <= high
    ):
        raise RunnerError(f"{name} must be an integer between {low} and {high}")
    return value


def _limits(args: argparse.Namespace) -> Limits:
    return Limits(
        _bounded(
            args.workspace_max_bytes,
            "workspace_max_bytes",
            64 * 1024**2,
            64 * 1024**3,
        ),
        _bounded(
            args.memory_max_bytes,
            "memory_max_bytes",
            128 * 1024**2,
            128 * 1024**3,
        ),
        _bounded(
            args.memory_swap_max_bytes,
            "memory_swap_max_bytes",
            0,
            128 * 1024**3,
        ),
        _bounded(args.cpu_quota_percent, "cpu_quota_percent", 1, 1600),
        _bounded(args.tasks_max, "tasks_max", 16, 4096),
        _bounded(args.runtime_max_seconds, "runtime_max_seconds", 10, 7200),
        _bounded(
            args.io_read_bandwidth_bps,
            "io_read_bandwidth_bps",
            1024,
            16 * 1024**3,
        ),
        _bounded(
            args.io_write_bandwidth_bps,
            "io_write_bandwidth_bps",
            1024,
            16 * 1024**3,
        ),
    )


def _tool(name: str) -> Path:
    found = shutil.which(name, path=_SYSTEM_PATH)
    if not found or not Path(found).is_file():
        raise RunnerError(f"required system tool is unavailable: {name}")
    return Path(found).resolve()


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> tuple[int, int]:
    value = path.stat(follow_symlinks=False)
    return value.st_dev, value.st_ino


def _owned(path: Path, identity: tuple[int, int]) -> bool:
    try:
        return path.exists() and _identity(path) == identity
    except OSError:
        return False


def _json(path: Path, maximum: int) -> Mapping[str, Any]:
    if not path.is_file() or path.stat().st_size > maximum:
        raise RunnerError(f"invalid or oversized JSON input: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunnerError(f"JSON input could not be read: {exc}") from exc
    if not isinstance(value, Mapping):
        raise RunnerError("JSON input must be an object")
    return value


def _snapshot(source: Path, target: Path, maximum: int) -> str:
    digest = hashlib.sha256()
    copied = 0
    with source.open("rb") as reader, target.open("xb") as writer:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            copied += len(chunk)
            if copied > maximum:
                raise RunnerError(f"snapshot exceeds {maximum} bytes: {source}")
            digest.update(chunk)
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    target.chmod(0o400)
    return digest.hexdigest()


def _device(path: Path) -> Path:
    value = path.stat()
    link = Path("/dev/block") / f"{os.major(value.st_dev)}:{os.minor(value.st_dev)}"
    if not link.exists():
        raise RunnerError(f"block device could not be resolved for {path}")
    resolved = link.resolve()
    if not stat.S_ISBLK(resolved.stat().st_mode):
        raise RunnerError(f"resolved IO device is not a block device: {resolved}")
    return resolved


def _environment() -> dict[str, str]:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        raise RunnerError("XDG_RUNTIME_DIR is required")
    root = Path(runtime).expanduser().resolve()
    root_stat = root.stat(follow_symlinks=False) if root.exists() else None
    if (
        root_stat is None
        or not stat.S_ISDIR(root_stat.st_mode)
        or root_stat.st_uid != os.getuid()
        or stat.S_IMODE(root_stat.st_mode) & 0o077
    ):
        raise RunnerError("XDG_RUNTIME_DIR is unavailable, foreign, or too permissive")
    result = {
        "PATH": _SYSTEM_PATH,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": str(Path.home()),
        "XDG_RUNTIME_DIR": str(root),
    }
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        result["DBUS_SESSION_BUS_ADDRESS"] = os.environ["DBUS_SESSION_BUS_ADDRESS"]
    return result


def _run(
    argv: Sequence[str], timeout: float = 30
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
        timeout=timeout,
        env=_environment(),
    )


def _prepare(request: Path, output: Path, receipt: Path) -> Run:
    request, output, receipt = (
        item.expanduser().resolve() for item in (request, output, receipt)
    )
    source_digest = _sha(request)
    data = _json(request, _MAX_REQUEST_BYTES)
    if not isinstance(data.get("repository"), str) or not isinstance(
        data.get("patch_path"), str
    ):
        raise RunnerError("request must contain string repository and patch_path")
    repository = Path(data["repository"]).expanduser().resolve()
    patch = Path(data["patch_path"]).expanduser().resolve()
    if not repository.is_dir() or not patch.is_file():
        raise RunnerError("repository or patch is unavailable")
    if output == receipt or output.parent != receipt.parent:
        raise RunnerError(
            "output and receipt must be different files in one dedicated root"
        )
    for candidate in (output, receipt):
        if candidate == repository or repository in candidate.parents or candidate.exists():
            raise RunnerError("output paths must be new and outside the source repository")
    root = output.parent
    root_stat = root.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or root_stat.st_uid != os.getuid()
        or stat.S_IMODE(root_stat.st_mode) != 0o700
        or any(root.iterdir())
    ):
        raise RunnerError(
            "persistent output root must be empty, current-user-owned, and mode 0700"
        )
    runtime = Path(_environment()["XDG_RUNTIME_DIR"]) / (
        "repoground-patch-evaluation-runner"
    )
    runtime.mkdir(mode=0o700, exist_ok=True)
    runtime.chmod(0o700)
    staging = runtime / uuid.uuid4().hex
    staging.mkdir(mode=0o700)
    staging_identity = _identity(staging)
    try:
        patch_copy = staging / "patch.diff"
        patch_digest = _snapshot(patch, patch_copy, _MAX_PATCH_BYTES)
        rewritten = dict(data)
        rewritten["patch_path"] = str(patch_copy)
        raw = (
            json.dumps(
                rewritten,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        ).encode()
        if len(raw) > _MAX_REQUEST_BYTES:
            raise RunnerError("rewritten request exceeds request limit")
        request_copy = staging / "request.json"
        with request_copy.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        request_copy.chmod(0o400)
        devices = tuple(sorted({_device(repository), _device(root)}, key=str))
        return Run(
            unit=f"repoground-patch-evaluation-{staging.name}.service",
            request=request_copy,
            patch=patch_copy,
            staging=staging,
            staging_identity=staging_identity,
            output=output,
            receipt=receipt,
            output_identity=_identity(root),
            repository=repository,
            devices=devices,
            source_request=request,
            source_request_sha256=source_digest,
            effective_request_sha256=hashlib.sha256(raw).hexdigest(),
            patch_sha256=patch_digest,
        )
    except Exception:
        if _owned(staging, staging_identity):
            shutil.rmtree(staging)
        raise


def _prop(name: str, value: str | int) -> str:
    return f"--property={name}={value}"


def _argv(run: Run, limits: Limits, sidecar: Path) -> list[str]:
    argv = [
        str(_tool("systemd-run")),
        "--user",
        "--quiet",
        f"--unit={run.unit}",
        _prop("Type", "exec"),
        _prop("RemainAfterExit", "yes"),
        _prop("KillMode", "control-group"),
        _prop("SendSIGKILL", "yes"),
        _prop("OOMPolicy", "stop"),
        _prop("NoNewPrivileges", "yes"),
        _prop("PrivateNetwork", "yes"),
        _prop("ProtectSystem", "strict"),
        _prop("ProtectHome", "read-only"),
        _prop("PrivateDevices", "yes"),
        _prop("ProtectKernelTunables", "yes"),
        _prop("ProtectKernelModules", "yes"),
        _prop("ProtectControlGroups", "yes"),
        _prop("RestrictSUIDSGID", "yes"),
        _prop("CPUAccounting", "yes"),
        _prop("MemoryAccounting", "yes"),
        _prop("TasksAccounting", "yes"),
        _prop("IOAccounting", "yes"),
        _prop("MemoryMax", limits.memory),
        _prop("MemorySwapMax", limits.swap),
        _prop("TasksMax", limits.tasks),
        _prop("CPUQuota", f"{limits.cpu_percent}%"),
        _prop("RuntimeMaxSec", limits.runtime),
        _prop(
            "TemporaryFileSystem",
            f"/tmp:rw,size={limits.workspace},mode=0700",
        ),
        _prop("ReadOnlyPaths", str(run.repository)),
        _prop("ReadOnlyPaths", str(run.staging)),
        _prop("BindPaths", f"{run.output.parent}:/run/repoground-output"),
    ]
    for device in run.devices:
        argv.extend(
            (
                _prop(
                    "IOReadBandwidthMax",
                    f"{device} {limits.read_bps}",
                ),
                _prop(
                    "IOWriteBandwidthMax",
                    f"{device} {limits.write_bps}",
                ),
            )
        )
    argv.extend(
        (
            "--",
            str(_tool("env")),
            "-i",
            f"PATH={_SYSTEM_PATH}",
            "LANG=C.UTF-8",
            "LC_ALL=C.UTF-8",
            "PYTHONNOUSERSITE=1",
            "HOME=/tmp",
            "TMPDIR=/tmp",
            str(Path(sys.executable).resolve()),
            str(sidecar),
            "--request",
            str(run.request),
            "--output",
            f"/run/repoground-output/{run.output.name}",
            "--workspace-root",
            "/tmp/sidecar-workspaces",
        )
    )
    return argv


def _show(systemctl: Path, unit: str) -> dict[str, str]:
    names = (
        "InvocationID",
        "ControlGroup",
        "ActiveState",
        "SubState",
        "Result",
        "ExecMainCode",
        "ExecMainStatus",
        "CPUUsageNSec",
        "MemoryPeak",
        "MemoryCurrent",
        "TasksCurrent",
        "IOReadBytes",
        "IOWriteBytes",
        "MemoryMax",
        "MemorySwapMax",
        "TasksMax",
        "CPUQuotaPerSecUSec",
        "RuntimeMaxUSec",
        "PrivateNetwork",
        "ProtectSystem",
        "NoNewPrivileges",
        "KillMode",
        "OOMPolicy",
        "RemainAfterExit",
        "IOReadBandwidthMax",
        "IOWriteBandwidthMax",
        "TemporaryFileSystem",
        "ReadOnlyPaths",
        "BindPaths",
    )
    argv = [str(systemctl), "--user", "show", unit]
    for name in names:
        argv.extend(("--property", name))
    result = _run(argv, 20)
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip()
        raise RunnerError(detail or "unit readback failed")
    return dict(
        line.split("=", 1)
        for line in result.stdout.decode(errors="replace").splitlines()
        if "=" in line
    )


def _wait(systemctl: Path, unit: str, seconds: int) -> dict[str, str]:
    deadline = time.monotonic() + seconds + 30
    while time.monotonic() < deadline:
        try:
            value = _show(systemctl, unit)
        except RunnerError:
            time.sleep(0.1)
            continue
        if value.get("ActiveState") in {"inactive", "failed"} or value.get(
            "SubState"
        ) == "exited":
            return value
        time.sleep(0.1)
    raise RunnerError("unit did not reach a terminal state")


def _num(value: str | None) -> int | None:
    if not value or value in {"[not set]", "infinity"}:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _duration(value: str | None) -> int | None:
    if not value:
        return None
    if value.isdigit():
        return int(value)
    for suffix, factor in (
        ("min", 60_000_000),
        ("ms", 1_000),
        ("us", 1),
        ("s", 1_000_000),
        ("h", 3_600_000_000),
    ):
        if value.endswith(suffix):
            try:
                return int(float(value[: -len(suffix)]) * factor)
            except ValueError:
                return None
    return None


def _device_major_minor(device: Path) -> str:
    info = device.stat()
    if not stat.S_ISBLK(info.st_mode):
        raise RunnerError(f"IO policy device is not a block device: {device}")
    return f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}"


def _cgroup(
    unit: Mapping[str, str],
    run: Run,
    limits: Limits,
    root: Path = Path("/sys/fs/cgroup"),
) -> dict[str, Any]:
    control = unit.get("ControlGroup", "")
    if not control.startswith("/") or ".." in Path(control).parts:
        raise RunnerError("unsafe cgroup path")
    canonical_root = root.resolve()
    directory = (canonical_root / control.lstrip("/")).resolve()
    if canonical_root not in directory.parents or not directory.is_dir():
        raise RunnerError("cgroup directory is unavailable")

    def read(name: str) -> str:
        return (directory / name).read_text(encoding="ascii").strip()

    def limited(name: str, maximum: int) -> int:
        raw = read(name)
        if raw == "max" or not raw.isdigit() or int(raw) > maximum:
            raise RunnerError(f"kernel {name} does not enforce the requested limit")
        return int(raw)

    cpu = read("cpu.max").split()
    if (
        len(cpu) != 2
        or cpu[0] == "max"
        or int(cpu[0]) * 100 != limits.cpu_percent * int(cpu[1])
    ):
        raise RunnerError("kernel cpu.max does not match requested quota")
    io_lines = {
        line.split()[0]: line.split()[1:]
        for line in read("io.max").splitlines()
        if line.split()
    }
    io: list[dict[str, Any]] = []
    for device in run.devices:
        key = _device_major_minor(device)
        fields = dict(
            item.split("=", 1)
            for item in io_lines.get(key, ())
            if "=" in item
        )
        read_bps = _num(fields.get("rbps"))
        write_bps = _num(fields.get("wbps"))
        if (
            read_bps is None
            or write_bps is None
            or read_bps > limits.read_bps
            or write_bps > limits.write_bps
        ):
            raise RunnerError(
                f"kernel io.max does not enforce requested limits for {device}"
            )
        io.append(
            {
                "device": str(device),
                "major_minor": key,
                "read_bandwidth_bps": read_bps,
                "write_bandwidth_bps": write_bps,
            }
        )
    return {
        "path": str(directory),
        "memory_max_bytes": limited("memory.max", limits.memory),
        "memory_swap_max_bytes": limited("memory.swap.max", limits.swap),
        "tasks_max": limited("pids.max", limits.tasks),
        "cpu_quota_usec": int(cpu[0]),
        "cpu_period_usec": int(cpu[1]),
        "io": io,
    }


def _policy(
    unit: Mapping[str, str], run: Run, limits: Limits
) -> tuple[str, dict[str, Any]]:
    exact: dict[str, str | int] = {
        "MemoryMax": limits.memory,
        "MemorySwapMax": limits.swap,
        "TasksMax": limits.tasks,
        "PrivateNetwork": "yes",
        "ProtectSystem": "strict",
        "NoNewPrivileges": "yes",
        "KillMode": "control-group",
        "OOMPolicy": "stop",
        "RemainAfterExit": "yes",
    }
    for name, expected in exact.items():
        if str(unit.get(name)) != str(expected):
            raise RunnerError(f"systemd policy mismatch for {name}")
    if _duration(unit.get("CPUQuotaPerSecUSec")) != limits.cpu_percent * 10_000:
        raise RunnerError("systemd CPU policy mismatch")
    if _duration(unit.get("RuntimeMaxUSec")) != limits.runtime * 1_000_000:
        raise RunnerError("systemd runtime policy mismatch")
    required = {
        "TemporaryFileSystem": (
            "/tmp",
            f"size={limits.workspace}",
            "mode=0700",
        ),
        "ReadOnlyPaths": (str(run.repository), str(run.staging)),
        "BindPaths": (str(run.output.parent), "/run/repoground-output"),
    }
    for name, parts in required.items():
        if not unit.get(name) or not all(part in unit[name] for part in parts):
            raise RunnerError(f"systemd policy mismatch for {name}")
    for device in run.devices:
        if str(device) not in unit.get("IOReadBandwidthMax", "") or str(
            limits.read_bps
        ) not in unit.get("IOReadBandwidthMax", ""):
            raise RunnerError("systemd read IO policy mismatch")
        if str(device) not in unit.get("IOWriteBandwidthMax", "") or str(
            limits.write_bps
        ) not in unit.get("IOWriteBandwidthMax", ""):
            raise RunnerError("systemd write IO policy mismatch")
    systemd_names = set(exact) | set(required) | {
        "CPUQuotaPerSecUSec",
        "RuntimeMaxUSec",
        "IOReadBandwidthMax",
        "IOWriteBandwidthMax",
    }
    systemd = {key: unit.get(key) for key in sorted(systemd_names)}
    readback = {
        "systemd": systemd,
        "cgroup": _cgroup(unit, run, limits),
    }
    raw = json.dumps(readback, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest(), readback
