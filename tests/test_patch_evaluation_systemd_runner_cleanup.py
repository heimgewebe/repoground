from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
MODULE = TOOLS / "patch_evaluation_systemd_runner.py"
SPEC = importlib.util.spec_from_file_location(
    "patch_evaluation_systemd_runner_cleanup_cases", MODULE
)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)
support = runner._support


def _prepared(tmp_path: Path) -> runner.Run:
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
        unit="repoground-patch-evaluation-" + "a" * 32 + ".service",
        request=request,
        patch=patch,
        staging=staging,
        staging_identity=support._identity(staging),
        output=output_root / "evaluation.json",
        receipt=output_root / "receipt.json",
        output_identity=support._identity(output_root),
        repository=source,
        devices=(Path("/dev/sda"),),
        source_request=source_request,
        source_request_sha256="0" * 64,
        effective_request_sha256="1" * 64,
        patch_sha256="2" * 64,
    )


def test_cleanup_refuses_changed_invocation_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _prepared(tmp_path)
    calls: list[object] = []
    monkeypatch.setattr(
        runner,
        "_show",
        lambda systemctl, unit: {"InvocationID": "foreign"},
    )
    monkeypatch.setattr(
        runner,
        "_run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    cleaned, error = runner._cleanup_transient(
        Path("/usr/bin/systemctl"),
        run,
        {"InvocationID": "owned"},
    )

    assert cleaned is False
    assert error == "unit InvocationID changed; cleanup refused"
    assert calls == []


def test_cleanup_readback_failure_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _prepared(tmp_path)

    def fail_show(systemctl: Path, unit: str) -> dict[str, str]:
        raise runner.RunnerError("readback unavailable")

    monkeypatch.setattr(runner, "_show", fail_show)

    cleaned, error = runner._cleanup_transient(
        Path("/usr/bin/systemctl"),
        run,
        {"InvocationID": "owned"},
    )

    assert cleaned is False
    assert error == "unit cleanup readback failed: readback unavailable"


def test_unit_absence_requires_explicit_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "_run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=b"Failed to connect to bus",
        ),
    )

    assert (
        runner._unit_absent(
            Path("/usr/bin/systemctl"),
            "repoground-patch-evaluation-" + "a" * 32 + ".service",
            timeout=0.01,
        )
        is False
    )


def test_cleanup_accepts_explicit_absence_after_bound_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _prepared(tmp_path)
    monkeypatch.setattr(
        runner,
        "_show",
        lambda systemctl, unit: {"InvocationID": "owned"},
    )
    monkeypatch.setattr(
        runner,
        "_run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=b"",
            stderr=b"",
        ),
    )
    monkeypatch.setattr(runner, "_unit_absent", lambda *args, **kwargs: True)

    cleaned, error = runner._cleanup_transient(
        Path("/usr/bin/systemctl"),
        run,
        {"InvocationID": "owned"},
    )

    assert cleaned is True
    assert error is None
