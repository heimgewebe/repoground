"""Bound import and module-boundary contracts for the Pythonista build frontend."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import merger.repoground.frontends.pythonista.build as repo_ground
from merger.repoground.frontends.pythonista.cli_args import parse_args


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHONISTA_DIR = REPO_ROOT / "merger" / "repoground" / "frontends" / "pythonista"
BUILD_SCRIPT = PYTHONISTA_DIR / "build.py"
NEW_PORTABLE_MODULES = [
    PYTHONISTA_DIR / "import_contract.py",
    PYTHONISTA_DIR / "source_mode.py",
    PYTHONISTA_DIR / "cli_args.py",
    PYTHONISTA_DIR / "cli_output.py",
    PYTHONISTA_DIR / "cli_runner.py",
]


def _run_python(args: list[str], *, cwd: Path, env: dict[str, str] | None = None):
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_package_import_does_not_reorder_sys_path(tmp_path):
    code = """
import json
import sys
before = list(sys.path)
import merger.repoground.frontends.pythonista.build as build
assert sys.path == before, (before, sys.path)
assert build.IMPORT_PATHS.package_mode is True
print(json.dumps({"script_dir": str(build.SCRIPT_DIR), "package_mode": True}))
"""
    result = _run_python(["-c", code], cwd=REPO_ROOT)
    assert result.returncode == 0, result.stderr
    assert '"package_mode": true' in result.stdout.lower()


def test_direct_script_help_bootstraps_from_unrelated_cwd(tmp_path):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = _run_python([str(BUILD_SCRIPT), "--help"], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    assert "RepoGround build" in result.stdout
    assert "--source-mode" in result.stdout


def test_package_and_flat_modes_expose_the_same_cli_defaults(tmp_path):
    package_args = parse_args(
        [],
        default_level=repo_ground.DEFAULT_LEVEL,
        default_mode=repo_ground.DEFAULT_MODE,
        default_max_file_bytes=repo_ground.DEFAULT_MAX_FILE_BYTES,
        default_split_size=repo_ground.DEFAULT_SPLIT_SIZE,
        default_extras=repo_ground.DEFAULT_EXTRAS,
    )
    assert package_args.level == repo_ground.DEFAULT_LEVEL
    assert package_args.mode == repo_ground.DEFAULT_MODE
    assert package_args.split_size == repo_ground.DEFAULT_SPLIT_SIZE
    assert package_args.extras == repo_ground.DEFAULT_EXTRAS

    code = f"""
import json
import runpy
import sys
sys.path.insert(0, {str(PYTHONISTA_DIR)!r})
ns = runpy.run_path({str(BUILD_SCRIPT)!r}, run_name='repoground_flat_contract_probe')
args = ns['parse_cli_args'](
    [],
    default_level=ns['DEFAULT_LEVEL'],
    default_mode=ns['DEFAULT_MODE'],
    default_max_file_bytes=ns['DEFAULT_MAX_FILE_BYTES'],
    default_split_size=ns['DEFAULT_SPLIT_SIZE'],
    default_extras=ns['DEFAULT_EXTRAS'],
)
print(json.dumps([args.level, args.mode, args.split_size, args.extras]))
"""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = _run_python(["-c", code], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    expected = [
        package_args.level,
        package_args.mode,
        package_args.split_size,
        package_args.extras,
    ]
    assert result.stdout.strip().endswith(__import__("json").dumps(expected))


def test_new_modules_use_only_standard_library_at_top_level():
    allowed_stdlib = {"argparse", "pathlib", "sys", "typing", "uuid"}
    for path in NEW_PORTABLE_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        external = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                external.extend(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                external.append(node.module.split(".", 1)[0])
        assert set(external) <= allowed_stdlib, (path.name, sorted(set(external)))


def test_extracted_functions_report_their_new_owners():
    assert repo_ground.resolve_headless_source_mode.__module__.endswith("source_mode")
    assert repo_ground.resolve_scan_options.__module__.endswith("cli_output")
    assert repo_ground.run_main_cli.__module__.endswith("cli_runner")
    assert repo_ground.parse_cli_args.__module__.endswith("cli_args")
