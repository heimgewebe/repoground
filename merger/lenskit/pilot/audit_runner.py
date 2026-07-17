"""Isolated, bounded execution for a small audit-lane pilot.

The runner requires a locally present, digest-pinned container image. It gives that
container a read-only repository mount, no network, no inherited host environment and
no writable host mount. The container may return candidate findings only through capped
stdout; Lenskit then binds them through the audit-finding adapter.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - Lenskit pilot execution is Linux-oriented.
    resource = None  # type: ignore[assignment]

from merger.lenskit.retrieval.audit_finding import adapt_audit_findings

_IMAGE_RE = re.compile(r"^[A-Za-z0-9._:/-]+@sha256:[a-f0-9]{64}$")
_REVISION_RE = re.compile(r"^[a-f0-9]{40}$")
_LANE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_RUN_RE = re.compile(r"^pilot_[a-f0-9]{16}$")
_FORBIDDEN_ENTRYPOINTS = frozenset(
    {"bash", "cmd", "dash", "fish", "powershell", "pwsh", "sh", "zsh"}
)
_SPEC_KEYS = frozenset(
    {
        "version",
        "run_id",
        "reviewed_revision",
        "repository_root",
        "output_root",
        "runtime",
        "image",
        "entrypoint",
        "arguments",
        "lanes",
        "limits",
        "isolation",
        "does_not_prove",
    }
)
_LANE_RESULT_KEYS = frozenset(
    {"version", "run_id", "lane_id", "reviewed_revision", "candidates"}
)
_MAX_LANE_CANDIDATES = 50
_MAX_TOTAL_CANDIDATES = 200


class AuditPilotError(RuntimeError):
    """Raised when the pilot cannot execute without crossing its safety contract."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    elapsed_seconds: float


CommandRunner = Callable[[Sequence[str], bytes, int, int], CommandResult]
GitProbe = Callable[[Path], tuple[str, bool]]
RuntimeResolver = Callable[[str], str | None]


def _require_revision(value: Any) -> str:
    if not isinstance(value, str) or _REVISION_RE.fullmatch(value) is None:
        raise AuditPilotError("reviewed_revision must be a lowercase 40-hex revision")
    return value


def _require_plan_lanes(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(plan, Mapping) or plan.get("version") != "audit_lane_plan.v1":
        raise AuditPilotError("plan must be an audit_lane_plan.v1 object")
    if plan.get("authority") != "navigation_index" or plan.get("risk_class") != "diagnostic":
        raise AuditPilotError("plan authority and risk class do not match audit_lane_plan.v1")
    lanes = plan.get("lanes")
    if not isinstance(lanes, Sequence) or isinstance(lanes, (str, bytes)):
        raise AuditPilotError("plan lanes must be an array")
    if not 5 <= len(lanes) <= 8:
        raise AuditPilotError("the pilot requires between five and eight selected lanes")

    normalized: list[dict[str, Any]] = []
    lane_ids: set[str] = set()
    for lane in lanes:
        if not isinstance(lane, Mapping):
            raise AuditPilotError("plan lanes must contain objects")
        lane_id = lane.get("id")
        if not isinstance(lane_id, str) or _LANE_RE.fullmatch(lane_id) is None:
            raise AuditPilotError("plan lane id has an invalid format")
        if lane_id in lane_ids:
            raise AuditPilotError("plan lane ids must be unique")
        lane_ids.add(lane_id)
        normalized.append(json.loads(json.dumps(lane, sort_keys=True)))
    return normalized


def _require_repository_root(value: os.PathLike[str] | str) -> Path:
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise AuditPilotError("repository_root must be an existing directory")
    if any(character in str(path) for character in (",", "\n", "\r", "\x00")):
        raise AuditPilotError("repository_root cannot be represented by the bind-mount contract")
    return path


def _require_output_root(value: os.PathLike[str] | str, repository_root: Path) -> Path:
    raw = Path(value).expanduser()
    parent = raw.parent.resolve(strict=True)
    path = parent / raw.name
    if not raw.name or raw.name in {".", ".."}:
        raise AuditPilotError("output_root must name a dedicated directory")
    if path == repository_root or repository_root in path.parents:
        raise AuditPilotError("output_root must be outside the source repository")
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise AuditPilotError("existing output_root must be a real directory")
    return path


def _require_image(value: Any) -> str:
    if not isinstance(value, str) or _IMAGE_RE.fullmatch(value) is None:
        raise AuditPilotError("image must be pinned as name@sha256:<64 lower-hex>")
    return value


def _require_command(value: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise AuditPilotError("command must be a non-empty argv array")
    if len(value) > 64:
        raise AuditPilotError("command must contain at most 64 argv elements")
    checked: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or len(item) > 1024:
            raise AuditPilotError("command argv elements must be non-empty bounded strings")
        if any(character in item for character in ("\x00", "\n", "\r")):
            raise AuditPilotError("command argv elements cannot contain control separators")
        checked.append(item)
    entrypoint = checked[0]
    pure = PurePosixPath(entrypoint)
    if not pure.is_absolute() or ".." in pure.parts:
        raise AuditPilotError("container entrypoint must be an absolute normalized path")
    if pure.name.lower() in _FORBIDDEN_ENTRYPOINTS:
        raise AuditPilotError("shell entrypoints are forbidden in the pilot")
    return entrypoint, tuple(checked[1:])


def _require_limits(timeout_seconds: int, max_output_bytes: int) -> dict[str, Any]:
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise AuditPilotError("timeout_seconds must be an integer")
    if not 30 <= timeout_seconds <= 1800:
        raise AuditPilotError("timeout_seconds must be between 30 and 1800")
    if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int):
        raise AuditPilotError("max_output_bytes must be an integer")
    if not 1024 <= max_output_bytes <= 8 * 1024 * 1024:
        raise AuditPilotError("max_output_bytes must be between 1 KiB and 8 MiB")
    return {
        "calls_per_lane": 1,
        "parallelism": 1,
        "timeout_seconds": timeout_seconds,
        "max_output_bytes": max_output_bytes,
        "max_candidates_per_lane": _MAX_LANE_CANDIDATES,
        "max_candidates_total": _MAX_TOTAL_CANDIDATES,
        "memory": "2g",
        "cpus": "2",
        "pids": 64,
    }


def _run_id_payload(
    *,
    revision: str,
    runtime: str,
    image: str,
    entrypoint: str,
    arguments: Sequence[str],
    lanes: Sequence[Mapping[str, Any]],
    limits: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "version": "audit_pilot_spec.v1",
        "reviewed_revision": revision,
        "runtime": runtime,
        "image": image,
        "entrypoint": entrypoint,
        "arguments": list(arguments),
        "lanes": list(lanes),
        "limits": dict(limits),
    }


def _make_run_id(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"pilot_{hashlib.sha256(encoded).hexdigest()[:16]}"


def build_audit_pilot_spec(
    plan: Mapping[str, Any],
    *,
    repository_root: os.PathLike[str] | str,
    output_root: os.PathLike[str] | str,
    reviewed_revision: str,
    image: str,
    command: Sequence[str],
    runtime: str = "docker",
    timeout_seconds: int = 900,
    max_output_bytes: int = 2 * 1024 * 1024,
) -> dict[str, Any]:
    """Build a deterministic, non-executing pilot specification."""

    lanes = _require_plan_lanes(plan)
    repository = _require_repository_root(repository_root)
    output = _require_output_root(output_root, repository)
    revision = _require_revision(reviewed_revision)
    pinned_image = _require_image(image)
    entrypoint, arguments = _require_command(command)
    if runtime not in {"docker", "podman"}:
        raise AuditPilotError("runtime must be docker or podman")
    limits = _require_limits(timeout_seconds, max_output_bytes)
    identity = _run_id_payload(
        revision=revision,
        runtime=runtime,
        image=pinned_image,
        entrypoint=entrypoint,
        arguments=arguments,
        lanes=lanes,
        limits=limits,
    )
    return {
        "version": "audit_pilot_spec.v1",
        "run_id": _make_run_id(identity),
        "reviewed_revision": revision,
        "repository_root": str(repository),
        "output_root": str(output),
        "runtime": runtime,
        "image": pinned_image,
        "entrypoint": entrypoint,
        "arguments": list(arguments),
        "lanes": lanes,
        "limits": limits,
        "isolation": {
            "pull": "never",
            "network": "none",
            "root_filesystem": "read_only",
            "repository_mount": "read_only",
            "host_environment": "empty",
            "capabilities": "drop_all",
            "no_new_privileges": True,
            "container_user": "65534:65534",
            "writable_host_mounts": 0,
            "result_channel": "capped_stdout_json",
        },
        "does_not_prove": [
            "container image trustworthiness beyond its pinned digest",
            "kernel-level sandbox escape resistance",
            "candidate correctness",
            "review completeness",
            "permission to create issues, patches, commits, pushes, or merges",
        ],
    }


def _container_name(run_id: str, lane_id: str) -> str:
    lane_digest = hashlib.sha256(lane_id.encode()).hexdigest()[:8]
    return f"lk-audit-{run_id.removeprefix('pilot_')[:8]}-{lane_digest}"


def build_container_argv(
    spec: Mapping[str, Any], lane_id: str, runtime_executable: str
) -> list[str]:
    """Compile one shell-free container invocation from a validated spec."""

    _validate_spec_shape(spec)
    lane_ids = {lane["id"] for lane in spec["lanes"]}
    if lane_id not in lane_ids:
        raise AuditPilotError(f"lane is not selected by the pilot spec: {lane_id}")
    runtime_path = Path(runtime_executable)
    if not runtime_path.is_absolute():
        raise AuditPilotError("runtime executable must be an absolute path")

    name = _container_name(spec["run_id"], lane_id)
    mount = (
        f"type=bind,src={spec['repository_root']},"
        "dst=/workspace/repo,readonly"
    )
    limits = spec["limits"]
    return [
        str(runtime_path),
        "run",
        "--rm",
        f"--name={name}",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        f"--pids-limit={limits['pids']}",
        f"--memory={limits['memory']}",
        f"--cpus={limits['cpus']}",
        "--user=65534:65534",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m",
        f"--mount={mount}",
        "--workdir=/workspace/repo",
        "--hostname=lenskit-audit",
        f"--label=org.heimgewebe.lenskit.audit-run={spec['run_id']}",
        f"--label=org.heimgewebe.lenskit.audit-lane={lane_id}",
        f"--env=LENSKIT_AUDIT_RUN_ID={spec['run_id']}",
        f"--env=LENSKIT_AUDIT_LANE_ID={lane_id}",
        f"--env=LENSKIT_REVIEWED_REVISION={spec['reviewed_revision']}",
        f"--entrypoint={spec['entrypoint']}",
        spec["image"],
        *spec["arguments"],
    ]


def _validate_spec_shape(spec: Mapping[str, Any]) -> None:
    if not isinstance(spec, Mapping) or set(spec) != _SPEC_KEYS:
        raise AuditPilotError("pilot spec has unexpected root fields")
    if spec.get("version") != "audit_pilot_spec.v1":
        raise AuditPilotError("unsupported pilot spec version")
    if not isinstance(spec.get("run_id"), str) or _RUN_RE.fullmatch(spec["run_id"]) is None:
        raise AuditPilotError("pilot spec run_id is invalid")
    rebuilt = build_audit_pilot_spec(
        {
            "version": "audit_lane_plan.v1",
            "authority": "navigation_index",
            "risk_class": "diagnostic",
            "lanes": spec["lanes"],
        },
        repository_root=spec["repository_root"],
        output_root=spec["output_root"],
        reviewed_revision=spec["reviewed_revision"],
        image=spec["image"],
        command=[spec["entrypoint"], *spec["arguments"]],
        runtime=spec["runtime"],
        timeout_seconds=spec["limits"]["timeout_seconds"],
        max_output_bytes=spec["limits"]["max_output_bytes"],
    )
    if rebuilt != dict(spec):
        raise AuditPilotError("pilot spec is not canonical")


def _lane_request(spec: Mapping[str, Any], lane: Mapping[str, Any]) -> bytes:
    payload = {
        "version": "audit_pilot_lane_request.v1",
        "run_id": spec["run_id"],
        "reviewed_revision": spec["reviewed_revision"],
        "repository_root": "/workspace/repo",
        "lane": lane,
        "output_contract": {
            "version": "audit_pilot_lane_result.v1",
            "maximum_candidates": _MAX_LANE_CANDIDATES,
            "candidate_fields": ["lane_id", "claim", "citation_ids"],
            "stdout": "one JSON object and no surrounding prose",
        },
        "does_not_authorize": [
            "network access",
            "repository writes",
            "issue creation",
            "patches",
            "commits",
            "pushes",
            "merges",
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _output_limiter(max_output_bytes: int) -> Callable[[], None] | None:
    if resource is None:
        return None

    def apply_limit() -> None:
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_output_bytes, max_output_bytes))

    return apply_limit


def _cleanup_container(runtime_executable: str, name: str) -> None:
    subprocess.run(
        [runtime_executable, "rm", "-f", name],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
        env={},
    )


def _default_command_runner(
    argv: Sequence[str], request: bytes, timeout_seconds: int, max_output_bytes: int
) -> CommandResult:
    start = time.monotonic()
    name = next(
        (argument.removeprefix("--name=") for argument in argv if argument.startswith("--name=")),
        "",
    )
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            completed = subprocess.run(
                list(argv),
                input=request,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=timeout_seconds,
                check=False,
                env={},
                start_new_session=True,
                preexec_fn=_output_limiter(max_output_bytes),
            )
        except subprocess.TimeoutExpired as exc:
            if name:
                _cleanup_container(argv[0], name)
            raise AuditPilotError("pilot lane exceeded its wall-clock limit") from exc
        stdout_size = stdout_file.tell()
        stderr_size = stderr_file.tell()
        if stdout_size > max_output_bytes or stderr_size > max_output_bytes:
            raise AuditPilotError("pilot lane exceeded its output limit")
        stdout_file.seek(0)
        stderr_file.seek(0)
        return CommandResult(
            returncode=completed.returncode,
            stdout=stdout_file.read(),
            stderr=stderr_file.read(),
            elapsed_seconds=time.monotonic() - start,
        )


def _default_runtime_resolver(runtime: str) -> str | None:
    return shutil.which(runtime, path="/usr/local/bin:/usr/bin:/bin")


def _git_command(repository: Path, *arguments: str) -> bytes:
    executable = shutil.which("git", path="/usr/local/bin:/usr/bin:/bin")
    if executable is None:
        raise AuditPilotError("git is required for source-identity checks")
    completed = subprocess.run(
        [executable, "-C", str(repository), *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
        env={},
    )
    if completed.returncode != 0:
        detail = completed.stderr[:1000].decode("utf-8", errors="replace")
        raise AuditPilotError(f"git source-identity probe failed: {detail}")
    if len(completed.stdout) > 1024 * 1024:
        raise AuditPilotError("git source-identity output exceeded its limit")
    return completed.stdout


def _default_git_probe(repository: Path) -> tuple[str, bool]:
    revision = _git_command(repository, "rev-parse", "--verify", "HEAD").decode().strip()
    _require_revision(revision)
    dirty = bool(
        _git_command(repository, "status", "--porcelain=v1", "--untracked-files=normal").strip()
    )
    return revision, dirty


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as tmp:
        temporary = Path(tmp.name)
        os.chmod(temporary, 0o600)
        tmp.write(encoded)
        tmp.flush()
        os.fsync(tmp.fileno())
    try:
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json_file(path: Path, max_bytes: int) -> dict[str, Any]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
        raise AuditPilotError(f"pilot artifact is not a bounded regular file: {path.name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AuditPilotError(f"pilot artifact must contain one JSON object: {path.name}")
    return payload


def _prepare_output(spec: Mapping[str, Any]) -> Path:
    root = Path(spec["output_root"])
    if root.exists():
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or root.is_symlink():
            raise AuditPilotError("output_root changed into a non-directory or symlink")
    else:
        root.mkdir(mode=0o700)
    spec_path = root / "pilot_spec.json"
    if spec_path.exists():
        if _read_json_file(spec_path, 1024 * 1024) != dict(spec):
            raise AuditPilotError("existing pilot_spec.json does not match this run")
    else:
        _atomic_write_json(spec_path, spec)
    return root


def _validate_lane_result(
    payload: Mapping[str, Any], spec: Mapping[str, Any], lane_id: str
) -> dict[str, Any]:
    if set(payload) != _LANE_RESULT_KEYS:
        raise AuditPilotError("lane result has unexpected fields")
    expected = {
        "version": "audit_pilot_lane_result.v1",
        "run_id": spec["run_id"],
        "lane_id": lane_id,
        "reviewed_revision": spec["reviewed_revision"],
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise AuditPilotError("lane result identity does not match the pilot spec")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > _MAX_LANE_CANDIDATES:
        raise AuditPilotError("lane result candidates are not a bounded array")
    for candidate in candidates:
        if not isinstance(candidate, Mapping) or set(candidate) != {
            "lane_id",
            "claim",
            "citation_ids",
        }:
            raise AuditPilotError("lane candidate has unexpected fields")
        if candidate.get("lane_id") != lane_id:
            raise AuditPilotError("lane candidate escaped its selected lane")
    return json.loads(json.dumps(payload, sort_keys=True))


def _load_or_execute_lane(
    *,
    root: Path,
    spec: Mapping[str, Any],
    lane: Mapping[str, Any],
    runtime_executable: str | None,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any], bool, float]:
    lane_id = lane["id"]
    result_path = root / f"lane-{lane_id}.json"
    if result_path.exists():
        payload = _read_json_file(result_path, spec["limits"]["max_output_bytes"])
        return _validate_lane_result(payload, spec, lane_id), True, 0.0
    if runtime_executable is None:
        raise AuditPilotError("container runtime is unavailable for an incomplete pilot")
    argv = build_container_argv(spec, lane_id, runtime_executable)
    result = command_runner(
        argv,
        _lane_request(spec, lane),
        spec["limits"]["timeout_seconds"],
        spec["limits"]["max_output_bytes"],
    )
    if result.returncode != 0:
        detail = result.stderr[:2000].decode("utf-8", errors="replace")
        raise AuditPilotError(f"pilot lane failed with exit {result.returncode}: {detail}")
    try:
        decoded = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditPilotError("pilot lane stdout is not one UTF-8 JSON object") from exc
    if not isinstance(decoded, Mapping):
        raise AuditPilotError("pilot lane stdout must contain one JSON object")
    payload = _validate_lane_result(decoded, spec, lane_id)
    _atomic_write_json(result_path, payload)
    return payload, False, result.elapsed_seconds


def _validate_plan_matches_spec(plan: Mapping[str, Any], spec: Mapping[str, Any]) -> None:
    if _require_plan_lanes(plan) != spec["lanes"]:
        raise AuditPilotError("pilot plan does not match the immutable spec")


def _receipt(
    spec: Mapping[str, Any],
    *,
    status: str,
    calls_executed: int,
    lanes_reused: int,
    elapsed_seconds: float,
    current_revision: str,
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": "audit_pilot_receipt.v1",
        "run_id": spec["run_id"],
        "status": status,
        "reviewed_revision": spec["reviewed_revision"],
        "current_revision": current_revision,
        "calls_executed": calls_executed,
        "lanes_reused": lanes_reused,
        "lane_count": len(spec["lanes"]),
        "elapsed_seconds": round(elapsed_seconds, 6),
        "cost": {
            "usd": 0.0,
            "basis": "offline digest-pinned image with network disabled",
        },
        "does_not_prove": [
            "candidate correctness",
            "review completeness",
            "container image safety",
            "absence of sandbox escape",
        ],
    }
    if error is not None:
        payload["error"] = error[:2000]
    return payload


def run_audit_pilot(
    plan: Mapping[str, Any],
    spec: Mapping[str, Any],
    *,
    resolvable_citation_ids: Iterable[str],
    command_runner: CommandRunner = _default_command_runner,
    git_probe: GitProbe = _default_git_probe,
    runtime_resolver: RuntimeResolver = _default_runtime_resolver,
) -> dict[str, Any]:
    """Execute or resume one sequential, isolated pilot run."""

    _validate_spec_shape(spec)
    _validate_plan_matches_spec(plan, spec)
    root = _prepare_output(spec)
    start = time.monotonic()
    calls_executed = 0
    lanes_reused = 0
    current_revision = spec["reviewed_revision"]
    try:
        current_revision, dirty = git_probe(Path(spec["repository_root"]))
        if dirty or current_revision != spec["reviewed_revision"]:
            raise AuditPilotError("source repository is dirty or not at the reviewed revision")
        missing = any(not (root / f"lane-{lane['id']}.json").exists() for lane in spec["lanes"])
        runtime_executable = runtime_resolver(spec["runtime"]) if missing else None
        lane_results: list[dict[str, Any]] = []
        elapsed_lane_seconds = 0.0
        for lane in spec["lanes"]:
            result, reused, elapsed = _load_or_execute_lane(
                root=root,
                spec=spec,
                lane=lane,
                runtime_executable=runtime_executable,
                command_runner=command_runner,
            )
            lane_results.append(result)
            lanes_reused += int(reused)
            calls_executed += int(not reused)
            elapsed_lane_seconds += elapsed

        final_revision, dirty = git_probe(Path(spec["repository_root"]))
        current_revision = final_revision
        if dirty or final_revision != spec["reviewed_revision"]:
            raise AuditPilotError("source repository changed during the pilot")
        candidates = [
            candidate
            for result in lane_results
            for candidate in result["candidates"]
        ]
        if len(candidates) > _MAX_TOTAL_CANDIDATES:
            raise AuditPilotError("pilot produced more than 200 candidates in total")
        finding_set = adapt_audit_findings(
            plan,
            candidates,
            reviewed_revision=spec["reviewed_revision"],
            current_revision=final_revision,
            resolvable_citation_ids=resolvable_citation_ids,
        )
        _atomic_write_json(root / "finding_set.json", finding_set)
        receipt = _receipt(
            spec,
            status="complete",
            calls_executed=calls_executed,
            lanes_reused=lanes_reused,
            elapsed_seconds=time.monotonic() - start,
            current_revision=final_revision,
        )
        receipt["lane_elapsed_seconds"] = round(elapsed_lane_seconds, 6)
        _atomic_write_json(root / "pilot_receipt.json", receipt)
        return {"spec": dict(spec), "receipt": receipt, "finding_set": finding_set}
    except Exception as exc:
        error = str(exc) if isinstance(exc, AuditPilotError) else type(exc).__name__
        failure = _receipt(
            spec,
            status="failed",
            calls_executed=calls_executed,
            lanes_reused=lanes_reused,
            elapsed_seconds=time.monotonic() - start,
            current_revision=current_revision,
            error=error,
        )
        _atomic_write_json(root / "pilot_receipt.json", failure)
        if isinstance(exc, AuditPilotError):
            raise
        raise AuditPilotError("pilot failed unexpectedly") from exc
