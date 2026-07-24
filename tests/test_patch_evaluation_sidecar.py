from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from merger.repoground.core.patch_evaluation import validate_patch_evaluation

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "patch_evaluation_sidecar.py"
SPEC = importlib.util.spec_from_file_location("patch_evaluation_sidecar", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
sidecar = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sidecar
SPEC.loader.exec_module(sidecar)


def _run(*argv: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    _run("git", "init", "-q", cwd=repo)
    _run("git", "config", "user.email", "test@example.invalid", cwd=repo)
    _run("git", "config", "user.name", "Patch Evaluation Test", cwd=repo)
    (repo / "message.txt").write_text("before\n", encoding="utf-8")
    _run("git", "add", "message.txt", cwd=repo)
    _run("git", "commit", "-qm", "initial", cwd=repo)
    return repo


def _patch(repo: Path, tmp_path: Path, content: str = "after\n") -> Path:
    path = repo / "message.txt"
    path.write_text(content, encoding="utf-8")
    patch = tmp_path / "change.diff"
    patch.write_text(_run("git", "diff", "--binary", cwd=repo).stdout, encoding="utf-8")
    _run("git", "checkout", "--", "message.txt", cwd=repo)
    return patch


def _request(
    repo: Path,
    patch: Path,
    commands: list[dict[str, object]],
    *,
    max_log_bytes: int = 4096,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "repository": str(repo),
        "base_commit": _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip(),
        "patch_path": str(patch),
        "patch_format": "git-diff",
        "commands": commands,
        "global_timeout_seconds": 30,
        "max_log_bytes": max_log_bytes,
        "repobrief_context": {
            "workbench_outputs": ["symbol-index"],
            "citations": ["message.txt:1"],
        },
    }


def _evaluate(
    tmp_path: Path, request: dict[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    request_path = tmp_path / "request.json"
    output = tmp_path / "out" / "evaluation.json"
    workspace_root = tmp_path / "workspaces"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    result = sidecar.evaluate(request_path, output, workspace_root=workspace_root)
    return result, json.loads(output.read_text(encoding="utf-8"))


def _source_state(repo: Path) -> tuple[str, str]:
    return (
        _run("git", "rev-parse", "HEAD", cwd=repo).stdout,
        _run(
            "git", "status", "--porcelain=v1", "--untracked-files=all", cwd=repo
        ).stdout,
    )


def test_success_isolated_schema_valid_source_unchanged_and_cleaned(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    before = _source_state(repo)
    request = _request(
        repo,
        patch,
        [
            {
                "argv": [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; assert Path('message.txt').read_text() == 'after\\n'",
                ],
                "cwd": ".",
                "timeout_seconds": 10,
            }
        ],
    )
    result, artifact = _evaluate(tmp_path, request)
    assert artifact["status"] == "passed"
    assert artifact["authority"] == "external_evaluation_evidence"
    assert artifact["workspace"]["isolated"] is True
    assert artifact["patch"]["applied"] is True
    assert artifact["patch"]["changed_files"] == [
        {"change": "modified", "path": "message.txt"}
    ]
    assert artifact["commands_run"][0]["status"] == "passed"
    assert result["workspace_cleaned"] is True
    assert result["source_unchanged"] is True
    assert _source_state(repo) == before
    assert not any((tmp_path / "workspaces").iterdir())
    assert validate_patch_evaluation(artifact)["status"] == "pass"


def test_failing_command_is_evidence_not_approval(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    _, artifact = _evaluate(
        tmp_path,
        _request(
            repo,
            patch,
            [
                {
                    "argv": [sys.executable, "-c", "raise SystemExit(7)"],
                    "cwd": ".",
                    "timeout_seconds": 10,
                }
            ],
        ),
    )
    assert artifact["status"] == "failed"
    assert artifact["commands_run"][0]["status"] == "failed"
    assert artifact["commands_run"][0]["exit_code"] == 7
    assert "merge_authorization" in artifact["does_not_establish"]
    assert "correctness" in artifact["does_not_establish"]
    assert validate_patch_evaluation(artifact)["status"] == "pass"


def test_path_traversal_and_unknown_request_fields_fail_closed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    traversal = _request(
        repo,
        patch,
        [
            {
                "argv": [sys.executable, "-c", "pass"],
                "cwd": "../outside",
                "timeout_seconds": 10,
            }
        ],
    )
    request_path = tmp_path / "traversal.json"
    request_path.write_text(json.dumps(traversal), encoding="utf-8")
    with pytest.raises(sidecar.RequestError, match="inside the isolated repository"):
        sidecar.load_request(request_path)
    unknown = _request(repo, patch, [])
    unknown["approve"] = True
    request_path.write_text(json.dumps(unknown), encoding="utf-8")
    with pytest.raises(sidecar.RequestError, match="unsupported field"):
        sidecar.load_request(request_path)

    option_shaped = _request(repo, patch, [])
    option_shaped["base_commit"] = "--help"
    request_path.write_text(json.dumps(option_shaped), encoding="utf-8")
    with pytest.raises(sidecar.RequestError, match="must not begin"):
        sidecar.load_request(request_path)

    null_format = _request(repo, patch, [])
    null_format["patch_format"] = None
    request_path.write_text(json.dumps(null_format), encoding="utf-8")
    with pytest.raises(sidecar.RequestError, match="patch_format must be"):
        sidecar.load_request(request_path)


def test_patch_apply_failure_runs_no_commands_and_cleans_workspace(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    invalid_patch = tmp_path / "invalid.diff"
    invalid_patch.write_text("this is not a patch\n", encoding="utf-8")
    marker = tmp_path / "must-not-exist"
    request = _request(
        repo,
        invalid_patch,
        [
            {
                "argv": [
                    sys.executable,
                    "-c",
                    f"from pathlib import Path; Path({str(marker)!r}).touch()",
                ],
                "cwd": ".",
                "timeout_seconds": 10,
            }
        ],
    )
    result, artifact = _evaluate(tmp_path, request)
    assert artifact["status"] == "error"
    assert artifact["patch"]["applied"] is False
    assert artifact["commands_run"] == []
    assert result["workspace_cleaned"] is True
    assert not marker.exists()
    assert validate_patch_evaluation(artifact)["status"] == "pass"


def test_logs_are_bounded_and_marked_truncated(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    _, artifact = _evaluate(
        tmp_path,
        _request(
            repo,
            patch,
            [
                {
                    "argv": [sys.executable, "-c", "print('x' * 20000)"],
                    "cwd": ".",
                    "timeout_seconds": 10,
                }
            ],
            max_log_bytes=512,
        ),
    )
    command = artifact["commands_run"][0]
    log_path = tmp_path / "out" / command["log_ref"]
    assert command["truncated"] is True
    assert log_path.stat().st_size <= 512


def test_timeout_is_bounded_and_reported_without_leaving_repository(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    request = _request(
        repo,
        patch,
        [
            {
                "argv": [sys.executable, "-c", "import time; time.sleep(30)"],
                "cwd": ".",
                "timeout_seconds": 1,
            }
        ],
    )
    result, artifact = _evaluate(tmp_path, request)
    assert artifact["status"] == "error"
    assert artifact["commands_run"][0]["status"] == "timeout"
    assert result["workspace_cleaned"] is True
    assert result["source_unchanged"] is True
    assert validate_patch_evaluation(artifact)["status"] == "pass"


def test_cli_emits_passed_artifact_and_machine_readable_summary(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    request_path = tmp_path / "cli-request.json"
    output = tmp_path / "cli-out" / "evaluation.json"
    workspace_root = tmp_path / "cli-workspaces"
    request_path.write_text(
        json.dumps(
            _request(
                repo,
                patch,
                [
                    {
                        "argv": [sys.executable, "-c", "raise SystemExit(0)"],
                        "cwd": ".",
                        "timeout_seconds": 10,
                    }
                ],
            )
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            "--request",
            str(request_path),
            "--output",
            str(output),
            "--workspace-root",
            str(workspace_root),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert summary["status"] == "passed"
    assert summary["workspace_cleaned"] is True
    assert artifact["status"] == "passed"


def test_internal_git_ignores_repository_hook_configuration(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    hook_directory = tmp_path / "hooks"
    hook_directory.mkdir()
    marker = tmp_path / "hook-ran"
    hook = hook_directory / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    hook.chmod(0o755)
    _run("git", "config", "core.hooksPath", str(hook_directory), cwd=repo)

    _, artifact = _evaluate(
        tmp_path,
        _request(
            repo,
            patch,
            [
                {
                    "argv": [sys.executable, "-c", "raise SystemExit(0)"],
                    "cwd": ".",
                    "timeout_seconds": 10,
                }
            ],
        ),
    )

    assert artifact["status"] == "passed"
    assert not marker.exists()


def test_patch_snapshot_binds_hash_and_applied_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path, "after\n")
    original_bytes = patch.read_bytes()
    replacement = _patch(repo, tmp_path, "replacement\n").read_bytes()
    patch.write_bytes(original_bytes)
    original_create = sidecar._create_isolated_repository
    mutated = False

    def mutating_create(setup: object, state: object) -> None:
        nonlocal mutated
        patch.write_bytes(replacement)
        mutated = True
        original_create(setup, state)

    monkeypatch.setattr(sidecar, "_create_isolated_repository", mutating_create)
    _, artifact = _evaluate(
        tmp_path,
        _request(
            repo,
            patch,
            [
                {
                    "argv": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; assert Path('message.txt').read_text() == 'after\\n'",
                    ],
                    "cwd": ".",
                    "timeout_seconds": 10,
                }
            ],
        ),
    )

    expected_sha256 = hashlib.sha256(original_bytes).hexdigest()
    assert mutated is True
    assert artifact["status"] == "passed"
    assert artifact["patch"]["sha256"] == expected_sha256
    assert artifact["patch"]["patch_id"] == expected_sha256


def test_skipped_commands_roll_up_as_incomplete() -> None:
    records = [
        {"status": "passed"},
        {"status": "skipped"},
    ]
    assert (
        sidecar._rollup_status(records, patch_applied=True, infrastructure_error=False)
        == "incomplete"
    )


def test_allowlisted_environment_does_not_inherit_secret_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    monkeypatch.setenv("PATCH_EVALUATION_TEST_SECRET", "must-not-leak")
    _, artifact = _evaluate(
        tmp_path,
        _request(
            repo,
            patch,
            [
                {
                    "argv": [
                        sys.executable,
                        "-c",
                        "import os; print(os.environ.get('PATCH_EVALUATION_TEST_SECRET', 'absent'))",
                    ],
                    "cwd": ".",
                    "timeout_seconds": 10,
                }
            ],
        ),
    )
    command = artifact["commands_run"][0]
    log_path = tmp_path / "out" / command["log_ref"]
    assert "must-not-leak" not in log_path.read_text(encoding="utf-8")
    assert "absent" in log_path.read_text(encoding="utf-8")
    assert artifact["command_policy"]["secrets_policy"] == "unknown"


def test_source_checkout_is_not_visible_to_declared_commands(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("source-only.txt\n", encoding="utf-8")
    _run("git", "add", ".gitignore", cwd=repo)
    _run("git", "commit", "-qm", "ignore source-only file", cwd=repo)
    patch = _patch(repo, tmp_path)
    source_only = repo / "source-only.txt"
    source_only.write_text("before command\n", encoding="utf-8")
    request = _request(
        repo,
        patch,
        [
            {
                "argv": [
                    sys.executable,
                    "-c",
                    f"from pathlib import Path; Path({str(source_only)!r}).write_text('tampered\\n')",
                ],
                "cwd": ".",
                "timeout_seconds": 10,
            }
        ],
    )
    result, artifact = _evaluate(tmp_path, request)
    assert result["source_unchanged"] is True
    assert source_only.read_text(encoding="utf-8") == "before command\n"
    assert artifact["status"] == "failed"
    assert validate_patch_evaluation(artifact)["status"] == "pass"


def test_source_fingerprint_includes_staged_index_content(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "message.txt").write_text("staged-one\n", encoding="utf-8")
    _run("git", "add", "message.txt", cwd=repo)
    before = sidecar._source_snapshot(repo)[1]

    replacement = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=repo,
        input="staged-two\n",
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    _run(
        "git",
        "update-index",
        "--cacheinfo",
        f"100644,{replacement},message.txt",
        cwd=repo,
    )

    after = sidecar._source_snapshot(repo)[1]
    assert after != before


def test_non_utf8_changed_path_is_json_safe(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    encoded_path = bytes(repo) + b"/invalid-\xff.txt"
    descriptor = __import__("os").open(
        encoded_path, __import__("os").O_WRONLY | __import__("os").O_CREAT, 0o600
    )
    __import__("os").write(descriptor, b"content\n")
    __import__("os").close(descriptor)

    changed = sidecar._parse_changed_files(repo)
    assert changed == [{"path": "invalid-\\xff.txt", "change": "added"}]
    json.dumps(changed, ensure_ascii=False)


def test_all_mandatory_non_claims_are_always_emitted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    _, artifact = _evaluate(tmp_path, _request(repo, patch, []))
    assert set(sidecar.MANDATORY_NON_CLAIMS).issubset(artifact["does_not_establish"])
    assert artifact["status"] == "incomplete"
    assert validate_patch_evaluation(artifact)["status"] == "pass"


def test_declared_git_config_mutates_only_independent_repository(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    _, artifact = _evaluate(
        tmp_path,
        _request(
            repo,
            patch,
            [
                {
                    "argv": ["git", "config", "sidecar.pwned", "yes"],
                    "cwd": ".",
                    "timeout_seconds": 10,
                }
            ],
        ),
    )
    source_value = subprocess.run(
        ["git", "config", "--get", "sidecar.pwned"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    assert artifact["status"] == "passed"
    assert artifact["workspace"]["isolated"] is True
    assert source_value.returncode == 1


def test_declared_git_ref_mutation_does_not_reach_source(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    _, artifact = _evaluate(
        tmp_path,
        _request(
            repo,
            patch,
            [
                {
                    "argv": ["git", "tag", "sidecar-only"],
                    "cwd": ".",
                    "timeout_seconds": 10,
                }
            ],
        ),
    )
    tags = _run("git", "tag", "--list", "sidecar-only", cwd=repo).stdout
    assert artifact["status"] == "passed"
    assert tags == ""


def test_repository_smudge_filter_is_not_executed_by_sidecar(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    marker = tmp_path / "filter-ran"
    filter_script = tmp_path / "filter.py"
    filter_script.write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).touch()\n"
        "sys.stdout.buffer.write(sys.stdin.buffer.read())\n",
        encoding="utf-8",
    )
    _run(
        "git",
        "config",
        "filter.sidecar-test.smudge",
        f"{sys.executable} {filter_script}",
        cwd=repo,
    )
    _run("git", "config", "filter.sidecar-test.clean", "cat", cwd=repo)
    (repo / ".gitattributes").write_text(
        "message.txt filter=sidecar-test\n", encoding="utf-8"
    )
    _run("git", "add", ".gitattributes", cwd=repo)
    _run("git", "commit", "-qm", "attributes", cwd=repo)
    patch = _patch(repo, tmp_path)
    marker.unlink(missing_ok=True)

    _, artifact = _evaluate(tmp_path, _request(repo, patch, []))

    assert artifact["status"] == "incomplete"
    assert not marker.exists()


def test_successful_command_cannot_leave_background_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    observed_after_delay = False
    original_cleanup = sidecar._cleanup_workspace

    def delayed_cleanup(setup: object, state: object) -> None:
        nonlocal observed_after_delay
        time.sleep(1.3)
        observed_after_delay = (setup.workspace / "late-marker").exists()
        original_cleanup(setup, state)

    monkeypatch.setattr(sidecar, "_cleanup_workspace", delayed_cleanup)
    child = (
        "import time; from pathlib import Path; "
        "time.sleep(0.7); Path('late-marker').write_text('survived')"
    )
    parent = (
        "import subprocess, sys; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL, start_new_session=True)"
    )
    _, artifact = _evaluate(
        tmp_path,
        _request(
            repo,
            patch,
            [
                {
                    "argv": [sys.executable, "-c", parent],
                    "cwd": ".",
                    "timeout_seconds": 10,
                }
            ],
        ),
    )
    assert artifact["status"] == "passed"
    assert observed_after_delay is False


def test_rename_reports_destination_path(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _run("git", "mv", "message.txt", "renamed.txt", cwd=repo)
    assert sidecar._parse_changed_files(repo) == [
        {"path": "renamed.txt", "change": "renamed"}
    ]


def test_fail_fast_marks_remaining_commands_skipped(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    request = _request(
        repo,
        patch,
        [
            {
                "argv": [sys.executable, "-c", "raise SystemExit(3)"],
                "cwd": ".",
                "timeout_seconds": 10,
            },
            {
                "argv": [sys.executable, "-c", "raise SystemExit(0)"],
                "cwd": ".",
                "timeout_seconds": 10,
            },
        ],
    )
    request["fail_fast"] = True
    _, artifact = _evaluate(tmp_path, request)
    assert [item["status"] for item in artifact["commands_run"]] == [
        "failed",
        "skipped",
    ]
    assert artifact["status"] == "incomplete"


def test_sensitive_argv_is_redacted_from_artifact(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    secret = "artifact-must-not-contain-this"
    command = {
        "argv": [sys.executable, "-c", "import sys; print(sys.argv[1])", secret],
        "cwd": ".",
        "timeout_seconds": 10,
        "redact_argv_indexes": [3],
    }
    _, artifact = _evaluate(tmp_path, _request(repo, patch, [command]))
    serialized = json.dumps(artifact)
    assert artifact["status"] == "passed"
    assert secret not in serialized
    assert "<redacted>" in artifact["commands_run"][0]["command"]
    log_path = tmp_path / "out" / artifact["commands_run"][0]["log_ref"]
    assert secret not in log_path.read_text(encoding="utf-8")
    assert "<redacted>" in log_path.read_text(encoding="utf-8")


def test_empty_command_set_leaves_no_log_directory(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    _, artifact = _evaluate(tmp_path, _request(repo, patch, []))
    assert artifact["status"] == "incomplete"
    assert not (tmp_path / "out" / "evaluation.logs").exists()


def test_repository_clean_filter_is_not_executed_by_source_preflight(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    (repo / ".gitattributes").write_text(
        "message.txt filter=sidecar-clean\n", encoding="utf-8"
    )
    _run("git", "add", ".gitattributes", cwd=repo)
    _run("git", "commit", "-qm", "attributes", cwd=repo)
    patch = _patch(repo, tmp_path)
    marker = tmp_path / "clean-filter-ran"
    script = tmp_path / "clean-filter.py"
    script.write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).touch()\n"
        "sys.stdout.buffer.write(sys.stdin.buffer.read())\n",
        encoding="utf-8",
    )
    _run(
        "git",
        "config",
        "filter.sidecar-clean.clean",
        f"{sys.executable} {script}",
        cwd=repo,
    )
    _run("git", "config", "filter.sidecar-clean.smudge", "cat", cwd=repo)

    _, artifact = _evaluate(tmp_path, _request(repo, patch, []))

    assert artifact["status"] == "incomplete"
    assert not marker.exists()


def test_repository_process_filter_is_not_executed_by_source_preflight(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    (repo / ".gitattributes").write_text(
        "message.txt filter=sidecar-process\n", encoding="utf-8"
    )
    _run("git", "add", ".gitattributes", cwd=repo)
    _run("git", "commit", "-qm", "attributes", cwd=repo)
    patch = _patch(repo, tmp_path)
    marker = tmp_path / "process-filter-ran"
    script = tmp_path / "process-filter.py"
    script.write_text(
        f"import pathlib\npathlib.Path({str(marker)!r}).touch()\nraise SystemExit(1)\n",
        encoding="utf-8",
    )
    _run(
        "git",
        "config",
        "filter.sidecar-process.process",
        f"{sys.executable} {script}",
        cwd=repo,
    )
    _run("git", "config", "filter.sidecar-process.required", "true", cwd=repo)

    _, artifact = _evaluate(tmp_path, _request(repo, patch, []))

    assert artifact["status"] == "incomplete"
    assert not marker.exists()


def test_cleanup_failure_forces_error_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    original_rmtree = sidecar.shutil.rmtree

    def selective_rmtree(path: Path, *args: object, **kwargs: object) -> None:
        if str(path).endswith("-repository"):
            return
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(sidecar.shutil, "rmtree", selective_rmtree)
    result, artifact = _evaluate(
        tmp_path,
        _request(
            repo,
            patch,
            [
                {
                    "argv": [sys.executable, "-c", "raise SystemExit(0)"],
                    "cwd": ".",
                    "timeout_seconds": 10,
                }
            ],
        ),
    )
    assert result["workspace_cleaned"] is False
    assert artifact["status"] == "error"
    for candidate in (tmp_path / "workspaces").glob("*-repository"):
        original_rmtree(candidate)


def test_partial_repository_creation_is_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)

    def fail_import(setup: object, pack_path: Path) -> None:
        raise sidecar.EvaluationError("forced object import failure")

    monkeypatch.setattr(sidecar, "_import_pack_snapshot", fail_import)
    result, artifact = _evaluate(tmp_path, _request(repo, patch, []))
    assert artifact["status"] == "error"
    assert result["workspace_cleaned"] is True
    assert not any((tmp_path / "workspaces").iterdir())


def test_parent_path_cannot_replace_internal_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    marker = tmp_path / "fake-git-ran"
    fake_git = fake_bin / "git"
    fake_git.write_text(
        f"#!/bin/sh\n/usr/bin/touch {marker}\nexit 91\n", encoding="utf-8"
    )
    fake_git.chmod(0o755)
    request = _request(repo, patch, [])
    monkeypatch.setenv("PATH", f"{fake_bin}:")

    _, artifact = _evaluate(tmp_path, request)

    assert artifact["status"] == "incomplete"
    assert not marker.exists()
    assert "/usr/bin/git" in artifact["environment"]["tool_versions"]["git"]


def test_request_and_patch_size_limits_fail_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request(repo, patch, [])), encoding="utf-8")
    monkeypatch.setattr(sidecar, "_MAX_REQUEST_BYTES", 8)
    with pytest.raises(sidecar.RequestError, match="request exceeds"):
        sidecar.load_request(request_path)

    monkeypatch.setattr(sidecar, "_MAX_REQUEST_BYTES", 1_000_000)
    monkeypatch.setattr(sidecar, "_MAX_PATCH_BYTES", 1)
    with pytest.raises(sidecar.RequestError, match="patch_path exceeds"):
        sidecar.load_request(request_path)


def test_atomic_artifact_publication_never_overwrites_existing_path(
    tmp_path: Path,
) -> None:
    output = tmp_path / "artifact.json"
    output.write_text("foreign\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        sidecar._atomic_write_json(output, {"status": "passed"})
    assert output.read_text(encoding="utf-8") == "foreign\n"
    assert not list(tmp_path.glob(".artifact.json.*.tmp"))


def test_log_directory_collision_fails_without_using_foreign_path(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    request_path = tmp_path / "request.json"
    output = tmp_path / "out" / "evaluation.json"
    workspace_root = tmp_path / "workspaces"
    request_path.write_text(
        json.dumps(
            _request(
                repo,
                patch,
                [
                    {
                        "argv": [sys.executable, "-c", "raise SystemExit(0)"],
                        "cwd": ".",
                        "timeout_seconds": 10,
                    }
                ],
            )
        ),
        encoding="utf-8",
    )
    foreign = output.parent / "evaluation.logs"
    foreign.mkdir(parents=True)
    marker = foreign / "foreign"
    marker.write_text("retain\n", encoding="utf-8")
    with pytest.raises(sidecar.RequestError, match="log directory already exists"):
        sidecar.evaluate(request_path, output, workspace_root=workspace_root)
    assert marker.read_text(encoding="utf-8") == "retain\n"
    assert not output.exists()


def test_command_sandbox_does_not_expose_unallowlisted_host_etc(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    patch = _patch(repo, tmp_path)
    _, artifact = _evaluate(
        tmp_path,
        _request(
            repo,
            patch,
            [
                {
                    "argv": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; assert not Path('/etc/machine-id').exists()",
                    ],
                    "cwd": ".",
                    "timeout_seconds": 10,
                }
            ],
        ),
    )
    assert artifact["status"] == "passed"
