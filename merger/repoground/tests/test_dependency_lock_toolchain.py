from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest

import scripts.release.compile_dependency_locks as compiler
from scripts.release.compile_dependency_locks import (
    LOCK_NAMES,
    ToolchainObservation,
    environment_findings,
    generate_locks,
    load_contract,
    report_environment,
)

ROOT = Path(__file__).resolve().parents[3]
SUPPORTED = ToolchainObservation(
    implementation="CPython",
    python="3.12.3",
    pip="25.3",
    pip_tools="7.6.0",
)


def _fixture_repo(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    repo = tmp_path / "repo"
    (repo / "requirements").mkdir(parents=True)
    (repo / "merger/repoground").mkdir(parents=True)
    (repo / "requirements/repoground-lock-tools.in").write_text(
        "# lock-python==3.12.3\npip==25.3\npip-tools==7.6.0\n",
        encoding="utf-8",
    )
    for name in ("runtime", "dev", "browser"):
        (repo / f"requirements/repoground-{name}.in").write_text(
            f"# {name}\n", encoding="utf-8"
        )
    (repo / "requirements-dev.txt").write_text("pytest==9.1.1\n", encoding="utf-8")
    (repo / "requirements-browser.txt").write_text(
        "playwright==1.62.0\n", encoding="utf-8"
    )
    (repo / "merger/repoground/requirements.txt").write_text(
        "jsonschema>=4\n", encoding="utf-8"
    )
    original = {}
    for name in LOCK_NAMES:
        path = repo / f"requirements/repoground-{name}.lock.txt"
        payload = f"original-{name}\n".encode()
        path.write_bytes(payload)
        original[name] = payload
    return repo, original


def _assert_locks(repo: Path, expected: dict[str, bytes]) -> None:
    assert {
        name: (repo / f"requirements/repoground-{name}.lock.txt").read_bytes()
        for name in LOCK_NAMES
    } == expected


def test_repository_contract_binds_python_pip_and_pip_tools() -> None:
    contract = load_contract(ROOT)
    assert contract.python == "3.12.3"
    assert contract.pip == "25.3"
    assert contract.pip_tools == "7.6.0"
    assert environment_findings(contract, SUPPORTED) == []


def test_mismatch_report_includes_every_expected_and_observed_version() -> None:
    contract = load_contract(ROOT)
    observed = ToolchainObservation(
        implementation="CPython",
        python="3.12.3",
        pip="26.2",
        pip_tools="7.6.0",
    )
    stream = io.StringIO()
    report_environment(contract, observed, stream)
    report = stream.getvalue()
    assert "Python: expected=3.12.3 observed=3.12.3" in report
    assert "pip: expected=25.3 observed=26.2" in report
    assert "pip-tools: expected=7.6.0 observed=7.6.0" in report
    assert environment_findings(contract, observed) == [
        "pip version mismatch: expected=25.3 observed=26.2"
    ]


def test_environment_failure_precedes_generation_and_preserves_all_locks(
    tmp_path: Path,
) -> None:
    repo, original = _fixture_repo(tmp_path)

    def unexpected_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess:
        raise AssertionError("compiler must not run after an environment mismatch")

    stderr = io.StringIO()
    result = generate_locks(
        repo,
        check=False,
        observation=ToolchainObservation(
            implementation="CPython",
            python="3.12.3",
            pip="26.2",
            pip_tools="7.6.0",
        ),
        runner=unexpected_runner,
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert result == 2
    assert "No lockfile was generated or rewritten." in stderr.getvalue()
    _assert_locks(repo, original)


def test_compile_failure_from_staging_preserves_all_locks(tmp_path: Path) -> None:
    repo, original = _fixture_repo(tmp_path)
    calls = 0

    def failing_runner(
        args: list[str], *, cwd: Path, check: bool
    ) -> subprocess.CompletedProcess:
        nonlocal calls
        assert check is False
        calls += 1
        output = cwd / args[args.index("--output-file") + 1]
        output.write_text(f"staged-{calls}\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 1 if calls == 2 else 0)

    result = generate_locks(
        repo,
        check=False,
        observation=SUPPORTED,
        runner=failing_runner,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert result == 1
    assert calls == 2
    _assert_locks(repo, original)


def test_supported_generation_publishes_only_after_all_four_locks_exist(
    tmp_path: Path,
) -> None:
    repo, _original = _fixture_repo(tmp_path)

    def successful_runner(
        args: list[str], *, cwd: Path, check: bool
    ) -> subprocess.CompletedProcess:
        assert check is False
        output = cwd / args[args.index("--output-file") + 1]
        output.write_text(f"generated-{output.name}\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    result = generate_locks(
        repo,
        check=False,
        observation=SUPPORTED,
        runner=successful_runner,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert result == 0
    assert {
        name: (repo / f"requirements/repoground-{name}.lock.txt").read_text(
            encoding="utf-8"
        )
        for name in LOCK_NAMES
    } == {
        name: f"generated-repoground-{name}.lock.txt\n" for name in LOCK_NAMES
    }


def test_publish_failure_rolls_back_already_replaced_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, original = _fixture_repo(tmp_path)

    def successful_runner(
        args: list[str], *, cwd: Path, check: bool
    ) -> subprocess.CompletedProcess:
        assert check is False
        output = cwd / args[args.index("--output-file") + 1]
        output.write_text(f"generated-{output.name}\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    real_replace = compiler.os.replace
    replacements = 0

    def fail_second_replace(source: Path, target: Path) -> None:
        nonlocal replacements
        if ".new." in Path(source).name:
            replacements += 1
            if replacements == 2:
                raise OSError("synthetic publish failure")
        real_replace(source, target)

    monkeypatch.setattr(compiler.os, "replace", fail_second_replace)
    with pytest.raises(OSError, match="synthetic publish failure"):
        generate_locks(
            repo,
            check=False,
            observation=SUPPORTED,
            runner=successful_runner,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    _assert_locks(repo, original)
