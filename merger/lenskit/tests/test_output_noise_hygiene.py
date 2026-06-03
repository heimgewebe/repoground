import json

import pytest
from pathlib import Path

from merger.lenskit.core.constants import ArtifactRole
from merger.lenskit.core.merge import ExtrasConfig, scan_repo, write_reports_v2
from merger.lenskit.core.post_emit_health import compute_post_emit_health
from merger.lenskit.tests._test_constants import make_generator_info


LEAK_PATH = ".tmp/forensic-preflight-ci-canary/artifacts/forensic-preflight-canary.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _artifact_path(bundle_manifest: Path, role: str) -> Path:
    data = json.loads(bundle_manifest.read_text(encoding="utf-8"))
    entry = next(item for item in data["artifacts"] if item["role"] == role)
    return bundle_manifest.parent / entry["path"]


def test_standard_dump_excludes_tmp_noise_but_keeps_repo_dotdirs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "guard.yml").write_text("name: guard\n", encoding="utf-8")
    (repo / ".wgx").mkdir()
    (repo / ".wgx" / "profile.yml").write_text("profile: demo\n", encoding="utf-8")

    leak = repo / LEAK_PATH
    leak.parent.mkdir(parents=True)
    leak.write_text('{"canary": true}\n', encoding="utf-8")
    (repo / ".pytest_cache").mkdir()
    (repo / ".pytest_cache" / "cache.txt").write_text("pytest\n", encoding="utf-8")
    (repo / ".ruff_cache").mkdir()
    (repo / ".ruff_cache" / "cache.txt").write_text("ruff\n", encoding="utf-8")
    (repo / ".mypy_cache").mkdir()
    (repo / ".mypy_cache" / "cache.txt").write_text("mypy\n", encoding="utf-8")
    (repo / "src" / "__pycache__").mkdir()
    (repo / "src" / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"pyc")

    summary = scan_repo(repo, calculate_md5=True, include_hidden=True)
    scanned_paths = {fi.rel_path.as_posix() for fi in summary["files"]}
    assert LEAK_PATH not in scanned_paths
    assert ".github/workflows/guard.yml" in scanned_paths
    assert ".wgx/profile.yml" in scanned_paths
    assert summary["excluded_noise"]["count"] >= 5
    assert LEAK_PATH in summary["excluded_noise"]["samples"]

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    hub_dir = tmp_path / "hub"
    hub_dir.mkdir()
    artifacts = write_reports_v2(
        merges_dir=out_dir,
        hub=hub_dir,
        repo_summaries=[summary],
        detail="test",
        mode="gesamt",
        max_bytes=1000,
        plan_only=False,
        code_only=False,
        extras=ExtrasConfig(json_sidecar=True),
        output_mode="dual",
        generator_info=make_generator_info(),
    )

    assert artifacts.canonical_md is not None
    assert artifacts.chunk_index is not None
    assert artifacts.bundle_manifest is not None
    assert artifacts.agent_reading_pack is not None

    assert LEAK_PATH not in _read(artifacts.canonical_md)
    assert LEAK_PATH not in _read(artifacts.chunk_index)
    assert LEAK_PATH not in _read(_artifact_path(artifacts.bundle_manifest, ArtifactRole.INDEX_SIDECAR_JSON.value))
    assert LEAK_PATH not in _read(artifacts.agent_reading_pack)

    # Dot-directories with repository meaning are not hidden by the scratch/cache filter.
    assert ".github/workflows/guard.yml" in _read(artifacts.canonical_md)
    assert ".wgx/profile.yml" in _read(artifacts.canonical_md)

    output_health = json.loads(artifacts.output_health.read_text(encoding="utf-8"))
    excluded = output_health["checks"]["excluded_noise"]
    hygiene = output_health["checks"]["noise_hygiene"]
    assert excluded["count"] >= 5
    assert LEAK_PATH in excluded["samples"]
    assert ".tmp/" in excluded["patterns"]
    assert hygiene["available"] is True
    assert hygiene["excluded_noise_count"] == excluded["count"]

    post_emit = compute_post_emit_health(str(artifacts.bundle_manifest))
    assert post_emit["noise_hygiene"]["available"] is True
    assert post_emit["noise_hygiene"]["excluded_noise_count"] == excluded["count"]


def test_symlinked_tmp_noise_diagnostic_does_not_enumerate_external_target(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Demo\n", encoding="utf-8")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "external-secret.txt").write_text("secret name should not leak\n", encoding="utf-8")

    tmp_link = repo / ".tmp"
    try:
        tmp_link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is not available: {exc}")

    summary = scan_repo(repo, calculate_md5=True, include_hidden=True)
    scanned_paths = {fi.rel_path.as_posix() for fi in summary["files"]}
    samples = summary["excluded_noise"]["samples"]

    assert "external-secret.txt" not in scanned_paths
    assert all("external-secret.txt" not in sample for sample in samples)
    assert ".tmp/" in samples
    assert summary["excluded_noise"]["count"] == 1
