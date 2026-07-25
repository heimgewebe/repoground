from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
MODULE = TOOLS / "patch_evaluation_systemd_runner.py"
SPEC = importlib.util.spec_from_file_location("patch_evaluation_systemd_runner", MODULE)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)
support = runner._support


def limits() -> runner.Limits:
    return runner.Limits(2 * 1024**3, 4 * 1024**3, 0, 200, 256, 30, 1000, 500)


def args(**changes: int) -> argparse.Namespace:
    values = {
        "workspace_max_bytes": 2 * 1024**3,
        "memory_max_bytes": 4 * 1024**3,
        "memory_swap_max_bytes": 0,
        "cpu_quota_percent": 200,
        "tasks_max": 256,
        "runtime_max_seconds": 30,
        "io_read_bandwidth_bps": 1000,
        "io_write_bandwidth_bps": 500,
    }
    values.update(changes)
    return argparse.Namespace(**values)


def prepared(tmp_path: Path) -> runner.Run:
    source = tmp_path / "source"
    source.mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()
    request = staging / "request.json"
    patch = staging / "patch.diff"
    request.write_text("{}\n", encoding="utf-8")
    patch.write_text("diff\n", encoding="utf-8")
    output_root = tmp_path / "out"
    output_root.mkdir(mode=0o700)
    output_root.chmod(0o700)
    source_request = tmp_path / "source-request.json"
    source_request.write_text("{}\n", encoding="utf-8")
    return runner.Run(
        "repoground-patch-evaluation-" + "a" * 32 + ".service",
        request,
        patch,
        staging,
        support._identity(staging),
        output_root / "evaluation.json",
        output_root / "receipt.json",
        support._identity(output_root),
        source,
        (Path("/dev/sda"), Path("/dev/sdb")),
        source_request,
        hashlib.sha256(b"{}\n").hexdigest(),
        hashlib.sha256(b"{}\n").hexdigest(),
        hashlib.sha256(b"diff\n").hexdigest(),
    )


def test_limits_derive_aggregate_cpu_and_multidevice_io() -> None:
    value = limits()
    assert value.cpu_time_usec == 60_000_000
    assert value.read_total(2) == 60_000
    assert value.write_total(2) == 30_000


def test_limits_reject_bool_and_out_of_range() -> None:
    with pytest.raises(runner.RunnerError, match="workspace_max_bytes"):
        support._limits(args(workspace_max_bytes=True))
    with pytest.raises(runner.RunnerError, match="tasks_max"):
        support._limits(args(tasks_max=1))


def test_snapshot_binds_bytes_mode_and_limit(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"payload")
    assert support._snapshot(source, target, 7) == hashlib.sha256(b"payload").hexdigest()
    assert target.read_bytes() == b"payload"
    assert stat.S_IMODE(target.stat().st_mode) == 0o400
    with pytest.raises(runner.RunnerError, match="snapshot exceeds"):
        support._snapshot(source, tmp_path / "too-small", 6)


def test_prepare_snapshots_request_and_patch_into_exclusive_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    patch = tmp_path / "change.diff"
    patch.write_text("diff\n", encoding="utf-8")
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"repository": str(repository), "patch_path": str(patch)}),
        encoding="utf-8",
    )
    output_root = tmp_path / "out"
    output_root.mkdir(mode=0o700)
    output_root.chmod(0o700)
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    runtime.chmod(0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(support, "_device", lambda path: Path("/dev/sda"))
    value = support._prepare(
        request, output_root / "evaluation.json", output_root / "receipt.json"
    )
    rewritten = json.loads(value.request.read_text(encoding="utf-8"))
    assert rewritten["patch_path"] == str(value.patch)
    assert value.patch.read_text(encoding="utf-8") == "diff\n"
    assert value.source_request_sha256 == hashlib.sha256(request.read_bytes()).hexdigest()
    assert stat.S_IMODE(value.staging.stat().st_mode) == 0o700


def test_prepare_rejects_nonempty_or_permissive_output_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    patch = tmp_path / "change.diff"
    patch.write_text("diff\n", encoding="utf-8")
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"repository": str(repository), "patch_path": str(patch)}),
        encoding="utf-8",
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    runtime.chmod(0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    root = tmp_path / "out"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    (root / "foreign").write_text("x", encoding="utf-8")
    with pytest.raises(runner.RunnerError, match="must be empty"):
        support._prepare(request, root / "evaluation.json", root / "receipt.json")


def test_unit_argv_contains_aggregate_and_namespace_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = prepared(tmp_path)
    tools = {"systemd-run": "/usr/bin/systemd-run", "env": "/usr/bin/env"}
    monkeypatch.setattr(support, "_tool", lambda name: Path(tools[name]))
    argv = support._argv(
        value, limits(), Path("/repo/tools/patch_evaluation_sidecar.py")
    )
    joined = "\n".join(argv)
    for expected in (
        "MemoryMax=4294967296",
        "MemorySwapMax=0",
        "CPUQuota=200%",
        "TasksMax=256",
        "RuntimeMaxSec=30",
        "TemporaryFileSystem=/tmp:rw,size=2147483648,mode=0700",
        "PrivateNetwork=yes",
        "ProtectSystem=strict",
        "RemainAfterExit=yes",
        "ReadOnlyPaths=" + str(value.repository),
        "BindPaths=" + str(value.output.parent) + ":/run/repoground-output",
        "IOReadBandwidthMax=/dev/sda 1000",
        "IOWriteBandwidthMax=/dev/sdb 500",
    ):
        assert expected in joined
    assert "-i" in argv and "PYTHONNOUSERSITE=1" in argv


def test_cgroup_readback_verifies_kernel_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = prepared(tmp_path)
    root = tmp_path / "cgroup"
    directory = root / "user.slice" / "unit.service"
    directory.mkdir(parents=True)
    (directory / "memory.max").write_text(str(limits().memory), encoding="ascii")
    (directory / "memory.swap.max").write_text("0", encoding="ascii")
    (directory / "pids.max").write_text("256", encoding="ascii")
    (directory / "cpu.max").write_text("200000 100000", encoding="ascii")
    (directory / "io.max").write_text(
        "8:1 rbps=1000 wbps=500\n8:2 rbps=1000 wbps=500\n", encoding="ascii"
    )
    ids = {Path("/dev/sda"): "8:1", Path("/dev/sdb"): "8:2"}
    monkeypatch.setattr(support, "_device_major_minor", lambda device: ids[device])
    result = support._cgroup(
        {"ControlGroup": "/user.slice/unit.service"}, value, limits(), root
    )
    assert result["memory_max_bytes"] == limits().memory
    assert len(result["io"]) == 2


def test_policy_binds_systemd_and_kernel_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = prepared(tmp_path)
    unit = {
        "MemoryMax": str(limits().memory),
        "MemorySwapMax": "0",
        "TasksMax": "256",
        "PrivateNetwork": "yes",
        "ProtectSystem": "strict",
        "NoNewPrivileges": "yes",
        "KillMode": "control-group",
        "OOMPolicy": "stop",
        "RemainAfterExit": "yes",
        "CPUQuotaPerSecUSec": "2s",
        "RuntimeMaxUSec": "30s",
        "TemporaryFileSystem": f"/tmp:rw,size={limits().workspace},mode=0700",
        "ReadOnlyPaths": f"{value.repository} {value.staging}",
        "BindPaths": f"{value.output.parent}:/run/repoground-output",
        "IOReadBandwidthMax": "/dev/sda 1000 /dev/sdb 1000",
        "IOWriteBandwidthMax": "/dev/sda 500 /dev/sdb 500",
    }
    monkeypatch.setattr(
        support, "_cgroup", lambda unit, run, limits: {"path": "/sys/fs/cgroup/x"}
    )
    digest, readback = support._policy(unit, value, limits())
    assert len(digest) == 64
    assert readback["systemd"]["PrivateNetwork"] == "yes"


def test_atomic_receipt_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    path.write_text("foreign\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        runner._atomic(path, {"status": "passed"})
    assert path.read_text(encoding="utf-8") == "foreign\n"


def test_producer_digest_binds_wrapper_support_and_sidecar(tmp_path: Path) -> None:
    sidecar = tmp_path / "sidecar.py"
    sidecar.write_text("pass\n", encoding="utf-8")
    before = runner._producer(sidecar)
    original = Path(support.__file__).read_text(encoding="utf-8")
    try:
        Path(support.__file__).write_text(original + "\n", encoding="utf-8")
        assert runner._producer(sidecar) != before
    finally:
        Path(support.__file__).write_text(original, encoding="utf-8")


def test_device_resolution_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.write_text("x", encoding="utf-8")
    monkeypatch.setattr(support.os, "major", lambda value: 8)
    monkeypatch.setattr(support.os, "minor", lambda value: 1)
    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        if str(path) == "/dev/block/8:1":
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)
    with pytest.raises(runner.RunnerError, match="block device"):
        support._device(target)


def test_example_receipt_conforms_to_schema() -> None:
    import jsonschema

    schema = json.loads(
        (
            ROOT
            / "merger"
            / "repoground"
            / "contracts"
            / "patch-evaluation-runner-receipt.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    example = json.loads(
        (
            ROOT
            / "merger"
            / "repoground"
            / "contracts"
            / "examples"
            / "patch-evaluation-runner-receipt.v1.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.Draft7Validator(schema).validate(example)
