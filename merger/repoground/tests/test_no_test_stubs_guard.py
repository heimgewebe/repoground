import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
GUARD_SOURCE = REPO_ROOT / "scripts" / "check_no_test_stubs.py"
STUBS_RELATIVE = Path("merger/repoground/tests/stubs")


def install_guard(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repository"
    script = repo / "scripts" / "check_no_test_stubs.py"
    script.parent.mkdir(parents=True)
    shutil.copyfile(GUARD_SOURCE, script)
    return repo, script


def run_guard(script: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_rejects_stubs_in_current_repoground_namespace(tmp_path: Path) -> None:
    repo, script = install_guard(tmp_path)
    stub = repo / STUBS_RELATIVE / "fastapi" / "__init__.py"
    stub.parent.mkdir(parents=True)
    stub.write_text("# forbidden shadow package\n", encoding="utf-8")

    result = run_guard(script, repo)

    assert result.returncode == 1
    assert f"ERROR: Forbidden path found: {repo / STUBS_RELATIVE}" in result.stdout


def test_accepts_repository_without_test_stubs(tmp_path: Path) -> None:
    repo, script = install_guard(tmp_path)

    result = run_guard(script, repo)

    assert result.returncode == 0
    assert result.stdout == "OK: No forbidden 'tests/stubs' directory found.\n"


def test_resolves_repository_from_script_location_not_working_directory(
    tmp_path: Path,
) -> None:
    repo, script = install_guard(tmp_path)
    (repo / STUBS_RELATIVE).mkdir(parents=True)
    unrelated_cwd = tmp_path / "unrelated"
    unrelated_cwd.mkdir()

    result = run_guard(script, unrelated_cwd)

    assert result.returncode == 1
    assert str(repo / STUBS_RELATIVE) in result.stdout


def test_rejects_dangling_symlink_at_forbidden_path(tmp_path: Path) -> None:
    repo, script = install_guard(tmp_path)
    stubs = repo / STUBS_RELATIVE
    stubs.parent.mkdir(parents=True)
    stubs.symlink_to(repo / "missing-stub-target", target_is_directory=True)

    result = run_guard(script, repo)

    assert result.returncode == 1
    assert f"ERROR: Forbidden path found: {stubs}" in result.stdout
