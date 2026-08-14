from __future__ import annotations

import argparse
import importlib.metadata
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

CONTRACT_PATH = Path("requirements/repoground-lock-tools.in")
TOOL_LOCK_PATH = Path("requirements/repoground-lock-tools.lock.txt")
LOCK_NAMES = ("runtime", "dev", "browser", "lock-tools")
_LOCK_PATHS = tuple(
    Path(f"requirements/repoground-{name}.lock.txt") for name in LOCK_NAMES
)
_INPUT_PATHS = (
    Path("requirements/repoground-runtime.in"),
    Path("requirements/repoground-dev.in"),
    Path("requirements/repoground-browser.in"),
    CONTRACT_PATH,
    Path("requirements-dev.txt"),
    Path("requirements-browser.txt"),
    Path("merger/repoground/requirements.txt"),
    *_LOCK_PATHS,
)
_PYTHON_PIN_RE = re.compile(r"^# lock-python==([0-9]+\.[0-9]+\.[0-9]+)$")
_PACKAGE_PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s]+)$")
_LOCK_PACKAGE_PIN_RE = re.compile(r"^(pip(?:-tools)?)==([^\s\\]+)\s+\\$")


class ContractError(ValueError):
    """The checked-in lock-generator contract is missing or ambiguous."""


@dataclass(frozen=True)
class ToolchainContract:
    python: str
    pip: str
    pip_tools: str


@dataclass(frozen=True)
class LockedToolchain:
    pip: str
    pip_tools: str


@dataclass(frozen=True)
class ToolchainObservation:
    implementation: str
    python: str
    pip: str
    pip_tools: str


Runner = Callable[..., subprocess.CompletedProcess[object]]


def load_contract(repo_root: Path) -> ToolchainContract:
    """Load the single Python/pip/pip-tools contract from the compiler input."""
    path = repo_root / CONTRACT_PATH
    python_pins: list[str] = []
    package_pins: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        line = raw_line.strip()
        if not line:
            continue
        python_match = _PYTHON_PIN_RE.fullmatch(line)
        if python_match is not None:
            python_pins.append(python_match.group(1))
            continue
        if line.startswith("#"):
            continue
        package_match = _PACKAGE_PIN_RE.fullmatch(line)
        if package_match is None:
            raise ContractError(
                f"{CONTRACT_PATH}:{line_number}: expected an exact package pin"
            )
        name = package_match.group(1).lower().replace("_", "-")
        if name in package_pins:
            raise ContractError(f"{CONTRACT_PATH}: duplicate pin for {name}")
        package_pins[name] = package_match.group(2)

    if len(python_pins) != 1:
        raise ContractError(
            f"{CONTRACT_PATH}: expected exactly one '# lock-python==X.Y.Z' pin"
        )
    if set(package_pins) != {"pip", "pip-tools"}:
        raise ContractError(
            f"{CONTRACT_PATH}: expected exactly pip and pip-tools pins; "
            f"observed={sorted(package_pins)!r}"
        )
    return ToolchainContract(
        python=python_pins[0],
        pip=package_pins["pip"],
        pip_tools=package_pins["pip-tools"],
    )


def load_locked_toolchain(repo_root: Path) -> LockedToolchain:
    """Read the direct pip/pip-tools pins from the checked-in tool lock."""
    path = repo_root / TOOL_LOCK_PATH
    package_pins: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        match = _LOCK_PACKAGE_PIN_RE.fullmatch(raw_line.strip())
        if match is None:
            continue
        name, version = match.groups()
        if name in package_pins:
            raise ContractError(f"{TOOL_LOCK_PATH}:{line_number}: duplicate pin for {name}")
        package_pins[name] = version

    if set(package_pins) != {"pip", "pip-tools"}:
        raise ContractError(
            f"{TOOL_LOCK_PATH}: expected exactly pip and pip-tools direct pins; "
            f"observed={sorted(package_pins)!r}"
        )
    return LockedToolchain(
        pip=package_pins["pip"],
        pip_tools=package_pins["pip-tools"],
    )


def toolchain_install_source(repo_root: Path) -> str:
    """Return lock for steady state or bootstrap for a direct tool-pin drift."""
    contract = load_contract(repo_root)
    locked = load_locked_toolchain(repo_root)
    if contract.pip == locked.pip and contract.pip_tools == locked.pip_tools:
        return "lock"
    return "bootstrap"


def observe_toolchain() -> ToolchainObservation:
    def distribution_version(name: str) -> str:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return "<missing>"

    return ToolchainObservation(
        implementation=platform.python_implementation(),
        python=platform.python_version(),
        pip=distribution_version("pip"),
        pip_tools=distribution_version("pip-tools"),
    )


def environment_findings(
    contract: ToolchainContract,
    observation: ToolchainObservation,
) -> list[str]:
    findings: list[str] = []
    if observation.implementation != "CPython":
        findings.append(
            "Python implementation mismatch: expected=CPython "
            f"observed={observation.implementation}"
        )
    for name, expected, observed in (
        ("Python", contract.python, observation.python),
        ("pip", contract.pip, observation.pip),
        ("pip-tools", contract.pip_tools, observation.pip_tools),
    ):
        if observed != expected:
            findings.append(
                f"{name} version mismatch: expected={expected} observed={observed}"
            )
    return findings


def bootstrap_environment_findings(
    contract: ToolchainContract,
    locked: LockedToolchain,
    observation: ToolchainObservation,
) -> list[str]:
    """Validate the compiler against the checked-in hash-locked toolchain."""
    findings: list[str] = []
    if observation.implementation != "CPython":
        findings.append(
            "Python implementation mismatch: expected=CPython "
            f"observed={observation.implementation}"
        )
    for name, expected, observed in (
        ("Python", contract.python, observation.python),
        ("pip", locked.pip, observation.pip),
        ("pip-tools", locked.pip_tools, observation.pip_tools),
    ):
        if observed != expected:
            findings.append(
                f"{name} bootstrap version mismatch: "
                f"expected={expected} observed={observed}"
            )
    return findings


def report_bootstrap_environment(
    contract: ToolchainContract,
    locked: LockedToolchain,
    observation: ToolchainObservation,
    stream: TextIO,
) -> None:
    print("RepoGround lock-bootstrap environment:", file=stream)
    print(
        "  implementation: expected=CPython "
        f"observed={observation.implementation}",
        file=stream,
    )
    for name, expected, observed in (
        ("Python", contract.python, observation.python),
        ("pip", locked.pip, observation.pip),
        ("pip-tools", locked.pip_tools, observation.pip_tools),
    ):
        print(f"  {name}: expected={expected} observed={observed}", file=stream)
    stream.flush()


def report_environment(
    contract: ToolchainContract,
    observation: ToolchainObservation,
    stream: TextIO,
) -> None:
    print("RepoGround lock-generator environment:", file=stream)
    print(
        "  implementation: expected=CPython "
        f"observed={observation.implementation}",
        file=stream,
    )
    for name, expected, observed in (
        ("Python", contract.python, observation.python),
        ("pip", contract.pip, observation.pip),
        ("pip-tools", contract.pip_tools, observation.pip_tools),
    ):
        print(f"  {name}: expected={expected} observed={observed}", file=stream)
    stream.flush()


def _copy_compiler_inputs(repo_root: Path, staging_root: Path) -> None:
    for relative in _INPUT_PATHS:
        source = repo_root / relative
        target = staging_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _compile_command(name: str) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "piptools",
        "compile",
        "--generate-hashes",
        "--resolver=backtracking",
        "--strip-extras",
        "--no-emit-index-url",
        "--quiet",
    ]
    if name == "lock-tools":
        command.append("--allow-unsafe")
    command.extend(
        (
            "--output-file",
            f"requirements/repoground-{name}.lock.txt",
            f"requirements/repoground-{name}.in",
        )
    )
    return command


def generate_bootstrap_tool_lock(
    repo_root: Path,
    *,
    observation: ToolchainObservation | None = None,
    runner: Runner = subprocess.run,
    stderr: TextIO = sys.stderr,
) -> bytes:
    """Compile a candidate tool lock with the current hash-locked compiler."""
    contract = load_contract(repo_root)
    locked = load_locked_toolchain(repo_root)
    if contract.pip == locked.pip and contract.pip_tools == locked.pip_tools:
        raise ContractError("bootstrap requested without a direct tool-pin drift")

    observed = observation if observation is not None else observe_toolchain()
    report_bootstrap_environment(contract, locked, observed, stderr)
    findings = bootstrap_environment_findings(contract, locked, observed)
    if findings:
        raise ContractError("; ".join(findings))

    with tempfile.TemporaryDirectory(prefix="repoground-tool-bootstrap-") as temp_dir:
        staging_root = Path(temp_dir)
        source = repo_root / CONTRACT_PATH
        target = staging_root / CONTRACT_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        result = runner(
            _compile_command("lock-tools"),
            cwd=staging_root,
            check=False,
            stdout=stderr,
            stderr=stderr,
        )
        if result.returncode != 0:
            raise ContractError("bootstrap tool-lock compilation failed")
        candidate_path = staging_root / TOOL_LOCK_PATH
        candidate = load_locked_toolchain(staging_root)
        if candidate.pip != contract.pip or candidate.pip_tools != contract.pip_tools:
            raise ContractError(
                "bootstrap tool lock does not bind the requested direct pins"
            )
        return candidate_path.read_bytes()


def _publish_locks(
    repo_root: Path,
    staging_root: Path,
    changed_names: Sequence[str],
) -> None:
    prepared: list[tuple[Path, Path, Path]] = []
    try:
        for name in changed_names:
            source = staging_root / f"requirements/repoground-{name}.lock.txt"
            target = repo_root / f"requirements/repoground-{name}.lock.txt"
            mode = target.stat().st_mode & 0o777
            temporary_files: list[Path] = []
            try:
                for kind, data in (
                    ("new", source.read_bytes()),
                    ("rollback", target.read_bytes()),
                ):
                    descriptor, temporary_name = tempfile.mkstemp(
                        dir=target.parent,
                        prefix=f".{target.name}.{kind}.",
                        suffix=".tmp",
                    )
                    temporary = Path(temporary_name)
                    temporary_files.append(temporary)
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    temporary.chmod(mode)
            except BaseException:
                for temporary in temporary_files:
                    temporary.unlink(missing_ok=True)
                raise
            prepared.append((temporary_files[0], temporary_files[1], target))

        replaced: list[tuple[Path, Path]] = []
        try:
            for replacement, rollback, target in prepared:
                os.replace(replacement, target)
                replaced.append((rollback, target))
        except BaseException:
            for rollback, target in reversed(replaced):
                os.replace(rollback, target)
            raise
    finally:
        for replacement, rollback, _target in prepared:
            replacement.unlink(missing_ok=True)
            rollback.unlink(missing_ok=True)


def generate_locks(
    repo_root: Path,
    *,
    check: bool,
    observation: ToolchainObservation | None = None,
    runner: Runner = subprocess.run,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Validate the environment, stage every lock, then compare or publish."""
    contract = load_contract(repo_root)
    observed = observation if observation is not None else observe_toolchain()
    report_environment(contract, observed, stdout)
    findings = environment_findings(contract, observed)
    if findings:
        for finding in findings:
            print(f"ERROR: {finding}", file=stderr)
        print("No lockfile was generated or rewritten.", file=stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="repoground-lock-stage-") as temp_dir:
        staging_root = Path(temp_dir)
        _copy_compiler_inputs(repo_root, staging_root)
        for name in LOCK_NAMES:
            result = runner(_compile_command(name), cwd=staging_root, check=False)
            if result.returncode != 0:
                print(
                    f"ERROR: generation failed for repoground-{name}.lock.txt; "
                    "no checked-in lockfile was rewritten.",
                    file=stderr,
                )
                return 1

        changed_names = [
            name
            for name in LOCK_NAMES
            if (
                staging_root / f"requirements/repoground-{name}.lock.txt"
            ).read_bytes()
            != (
                repo_root / f"requirements/repoground-{name}.lock.txt"
            ).read_bytes()
        ]
        if check:
            if changed_names:
                for name in changed_names:
                    print(
                        f"ERROR: lock drift: requirements/repoground-{name}.lock.txt",
                        file=stderr,
                    )
                print("No checked-in lockfile was rewritten.", file=stderr)
                return 1
            print("All RepoGround dependency locks are reproducible.", file=stdout)
            return 0

        _publish_locks(repo_root, staging_root, changed_names)
        if changed_names:
            for name in changed_names:
                print(
                    f"updated requirements/repoground-{name}.lock.txt",
                    file=stdout,
                )
        else:
            print("All RepoGround dependency locks were already current.", file=stdout)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate all RepoGround hash locks under one pinned toolchain"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare staged generations without rewriting checked-in locks",
    )
    parser.add_argument(
        "--print-install-source",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--emit-bootstrap-tool-lock",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    repo_root = Path(args.root).resolve()
    try:
        if args.print_install_source:
            if args.check or args.emit_bootstrap_tool_lock:
                raise ContractError(
                    "--print-install-source cannot be combined with another mode"
                )
            print(toolchain_install_source(repo_root))
            return 0
        if args.emit_bootstrap_tool_lock:
            if args.check:
                raise ContractError(
                    "--emit-bootstrap-tool-lock cannot be combined with --check"
                )
            sys.stdout.buffer.write(generate_bootstrap_tool_lock(repo_root))
            return 0
        return generate_locks(repo_root, check=args.check)
    except (ContractError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("No lockfile was generated or rewritten.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
