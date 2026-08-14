from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest

import scripts.release.compile_dependency_locks as compiler
from scripts.release.compile_dependency_locks import (
    LOCK_NAMES,
    ContractError,
    ToolchainObservation,
    environment_findings,
    generate_bootstrap_tool_lock,
    generate_locks,
    load_contract,
    load_locked_toolchain,
    report_environment,
    toolchain_install_source,
)

ROOT = Path(__file__).resolve().parents[3]
SUPPORTED = ToolchainObservation(
    implementation="CPython",
    python="3.12.3",
    pip="26.1.2",
    pip_tools="7.6.0",
)


def _fixture_repo(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    repo = tmp_path / "repo"
    (repo / "requirements").mkdir(parents=True)
    (repo / "merger/repoground").mkdir(parents=True)
    (repo / "requirements/repoground-lock-tools.in").write_text(
        "# lock-python==3.12.3\npip==26.1.2\npip-tools==7.6.0\n",
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


def _write_tool_lock(repo: Path, *, pip: str, pip_tools: str) -> None:
    (repo / "requirements/repoground-lock-tools.lock.txt").write_text(
        f"pip-tools=={pip_tools} " + "\\" + "\n"
        + f"pip=={pip} " + "\\" + "\n",
        encoding="utf-8",
    )


def test_repository_contract_binds_python_pip_and_pip_tools() -> None:
    contract = load_contract(ROOT)
    assert contract.python == "3.12.3"
    assert contract.pip == "26.1.2"
    assert contract.pip_tools == "7.6.0"
    assert environment_findings(contract, SUPPORTED) == []


def test_toolchain_install_source_uses_hashed_lock_when_direct_pins_match(
    tmp_path: Path,
) -> None:
    repo, _original = _fixture_repo(tmp_path)
    _write_tool_lock(repo, pip="26.1.2", pip_tools="7.6.0")

    locked = load_locked_toolchain(repo)
    assert locked.pip == "26.1.2"
    assert locked.pip_tools == "7.6.0"
    assert toolchain_install_source(repo) == "lock"


@pytest.mark.parametrize(
    ("pip", "pip_tools"),
    (("25.3", "7.6.0"), ("26.1.2", "7.5.0")),
)
def test_toolchain_install_source_bootstraps_exact_input_when_direct_pin_differs(
    tmp_path: Path,
    pip: str,
    pip_tools: str,
) -> None:
    repo, _original = _fixture_repo(tmp_path)
    _write_tool_lock(repo, pip=pip, pip_tools=pip_tools)

    assert toolchain_install_source(repo) == "bootstrap"


def test_toolchain_install_source_rejects_missing_direct_tool_pin(
    tmp_path: Path,
) -> None:
    repo, _original = _fixture_repo(tmp_path)
    (repo / "requirements/repoground-lock-tools.lock.txt").write_text(
        "pip-tools==7.6.0 " + "\\" + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match="expected exactly pip and pip-tools"):
        toolchain_install_source(repo)


def test_toolchain_install_source_rejects_ambiguous_tool_lock(
    tmp_path: Path,
) -> None:
    repo, _original = _fixture_repo(tmp_path)
    path = repo / "requirements/repoground-lock-tools.lock.txt"
    path.write_text(
        "pip==26.1.2 " + "\\" + "\n"
        + "pip==25.3 " + "\\" + "\n"
        + "pip-tools==7.6.0 " + "\\" + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match="duplicate pin for pip"):
        toolchain_install_source(repo)


def test_bootstrap_tool_lock_is_derived_by_the_current_hashed_compiler(
    tmp_path: Path,
) -> None:
    repo, _original = _fixture_repo(tmp_path)
    _write_tool_lock(repo, pip="25.3", pip_tools="7.6.0")
    checked_in = (repo / "requirements/repoground-lock-tools.lock.txt").read_bytes()

    def bootstrap_runner(
        args: list[str],
        *,
        cwd: Path,
        check: bool,
        stdout: io.StringIO,
        stderr: io.StringIO,
    ) -> subprocess.CompletedProcess:
        assert check is False
        assert "--allow-unsafe" in args
        assert stdout is stderr
        output = cwd / args[args.index("--output-file") + 1]
        output.write_text(
            "pip-tools==7.6.0 " + "\\" + "\n"
            + "pip==26.1.2 " + "\\" + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 0)

    candidate = generate_bootstrap_tool_lock(
        repo,
        observation=ToolchainObservation(
            implementation="CPython",
            python="3.12.3",
            pip="25.3",
            pip_tools="7.6.0",
        ),
        runner=bootstrap_runner,
        stderr=io.StringIO(),
    )

    assert b"pip==26.1.2" in candidate
    assert b"pip-tools==7.6.0" in candidate
    assert (repo / "requirements/repoground-lock-tools.lock.txt").read_bytes() == checked_in


def test_bootstrap_tool_lock_rejects_an_environment_not_bound_by_old_lock(
    tmp_path: Path,
) -> None:
    repo, _original = _fixture_repo(tmp_path)
    _write_tool_lock(repo, pip="25.3", pip_tools="7.6.0")

    def unexpected_runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess:
        raise AssertionError("bootstrap compiler must not run after environment drift")

    with pytest.raises(ContractError, match="pip bootstrap version mismatch"):
        generate_bootstrap_tool_lock(
            repo,
            observation=SUPPORTED,
            runner=unexpected_runner,
            stderr=io.StringIO(),
        )


def test_bootstrap_tool_lock_rejects_candidate_with_wrong_direct_pins(
    tmp_path: Path,
) -> None:
    repo, _original = _fixture_repo(tmp_path)
    _write_tool_lock(repo, pip="25.3", pip_tools="7.6.0")

    def wrong_candidate_runner(
        args: list[str],
        *,
        cwd: Path,
        check: bool,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess:
        assert check is False
        output = cwd / args[args.index("--output-file") + 1]
        output.write_text(
            "pip-tools==7.6.0 " + "\\" + "\n"
            + "pip==25.3 " + "\\" + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 0)

    with pytest.raises(ContractError, match="does not bind the requested direct pins"):
        generate_bootstrap_tool_lock(
            repo,
            observation=ToolchainObservation(
                implementation="CPython",
                python="3.12.3",
                pip="25.3",
                pip_tools="7.6.0",
            ),
            runner=wrong_candidate_runner,
            stderr=io.StringIO(),
        )


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
    assert "pip: expected=26.1.2 observed=26.2" in report
    assert "pip-tools: expected=7.6.0 observed=7.6.0" in report
    assert environment_findings(contract, observed) == [
        "pip version mismatch: expected=26.1.2 observed=26.2"
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
