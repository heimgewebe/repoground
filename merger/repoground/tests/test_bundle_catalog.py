import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from merger.repoground.core import bundle_catalog as bundle_catalog_module
from merger.repoground.core.bundle_catalog import (
    discover_bundle_catalog,
    manifest_repo_aliases,
    manifest_repo_identities,
    normalize_repo_remote,
    select_bundle_manifest,
)


def _write_json(path: Path, value: dict) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return len(raw), hashlib.sha256(raw).hexdigest()


def _write_bundle(
    root: Path,
    *,
    directory: str,
    stem: str,
    created_at: str,
    run_id: str,
    output_status: str = "pass",
    remote: str = "git@github.com:heimgewebe/repoground.git",
) -> Path:
    bundle_dir = root / directory
    output_path = bundle_dir / f"{stem}.output_health.json"
    output_bytes, output_sha = _write_json(
        output_path,
        {"verdict": output_status},
    )
    post_path = bundle_dir / f"{stem}.bundle_health.post.json"
    manifest = bundle_dir / f"{stem}.bundle.manifest.json"
    _, manifest_sha = _write_json(
        manifest,
        {
            "kind": "repoground.bundle.manifest",
            "version": "2.0",
            "run_id": run_id,
            "created_at": created_at,
            "snapshot_provenance": {
                "repositories": [
                    {
                        "name": "heimgewebe__repoground__main",
                        "repo_remote": remote,
                        "git_commit": "a" * 40,
                        "git_dirty": False,
                        "provenance_status": "present",
                    }
                ]
            },
            "artifacts": [
                {
                    "role": "output_health",
                    "path": output_path.name,
                    "bytes": output_bytes,
                    "sha256": output_sha,
                }
            ],
            "links": {
                "post_emit_health_path": post_path.name,
                "bundle_surface_validation_status": "pass",
                "agent_export_gate_status": "pass",
                "export_safety_report_status": "pass",
            },
        },
    )
    _write_json(
        post_path,
        {
            "status": "pass",
            "bundle_manifest_path": str(manifest.resolve()),
            "bundle_run_id": run_id,
            "bundle_manifest_sha256": manifest_sha,
        },
    )
    return manifest


def test_normalize_repo_remote_accepts_common_github_forms():
    assert normalize_repo_remote("git@github.com:heimgewebe/repoground.git") == (
        "heimgewebe/repoground"
    )
    assert normalize_repo_remote("https://github.com/heimgewebe/repoground.git") == (
        "heimgewebe/repoground"
    )


def test_manifest_repo_aliases_include_canonical_and_short_identity():
    aliases = manifest_repo_aliases(
        {
            "snapshot_provenance": {
                "repositories": [
                    {
                        "name": "heimgewebe__repoground__main",
                        "repo_remote": "git@github.com:heimgewebe/repoground.git",
                    }
                ]
            }
        }
    )

    assert aliases == [
        "heimgewebe/repoground",
        "heimgewebe__repoground",
        "heimgewebe__repoground__main",
        "repoground",
    ]


def test_manifest_repo_identities_prefer_explicit_remote():
    identities = manifest_repo_identities(
        {
            "snapshot_provenance": {
                "repositories": [
                    {
                        "name": "wrong-owner__repoground__main",
                        "repo_remote": "git@github.com:right-owner/repoground.git",
                    }
                ]
            }
        }
    )
    assert identities == ["right-owner/repoground"]


def test_short_repo_selector_fails_closed_across_owners(tmp_path):
    first = _write_bundle(
        tmp_path,
        directory="owner-a/main/run",
        stem="owner-a",
        created_at="2026-07-25T20:00:00Z",
        run_id="owner-a-run",
        remote="git@github.com:owner-a/repoground.git",
    )
    second = _write_bundle(
        tmp_path,
        directory="owner-b/main/run",
        stem="owner-b",
        created_at="2026-07-25T21:00:00Z",
        run_id="owner-b-run",
        remote="git@github.com:owner-b/repoground.git",
    )

    short = select_bundle_manifest(tmp_path, repo="repoground")
    qualified = select_bundle_manifest(tmp_path, repo="owner-a/repoground")
    underscored = select_bundle_manifest(tmp_path, repo="owner-b__repoground")

    assert short["status"] == "ambiguous"
    assert short["reason"] == "repository_identity_ambiguous"
    assert short["repo_identity_groups"] == [
        "owner-a/repoground",
        "owner-b/repoground",
    ]
    assert qualified["selected"]["manifest_path"] == str(first.resolve())
    assert underscored["selected"]["manifest_path"] == str(second.resolve())


def test_selector_orders_created_at_by_normalized_utc_and_rejects_invalid(tmp_path):
    earlier = _write_bundle(
        tmp_path,
        directory="repo/main/earlier",
        stem="earlier",
        created_at="2026-07-25T23:30:00+02:00",
        run_id="earlier-run",
    )
    later = _write_bundle(
        tmp_path,
        directory="repo/main/later",
        stem="later",
        created_at="2026-07-25T22:00:00Z",
        run_id="later-run",
    )
    _write_bundle(
        tmp_path,
        directory="repo/main/invalid",
        stem="invalid",
        created_at="zzzz",
        run_id="invalid-run",
    )

    catalog = discover_bundle_catalog(tmp_path)
    selection = select_bundle_manifest(tmp_path, repo="heimgewebe/repoground")

    assert selection["status"] == "available"
    assert selection["selected"]["manifest_path"] == str(later.resolve())
    assert selection["selected"]["manifest_path"] != str(earlier.resolve())
    assert selection["selected"]["created_at_utc"] == "2026-07-25T22:00:00.000000Z"
    invalid = next(item for item in catalog["candidates"] if item["stem"] == "invalid")
    assert invalid["timestamp_status"] == "invalid"
    assert invalid["selection_eligible"] is False
    assert "created_at" in invalid["timestamp_reason"]
    invalid_only = select_bundle_manifest(
        invalid["manifest_path"],
        repo="heimgewebe/repoground",
        require_healthy=False,
    )
    assert invalid_only["status"] == "missing"


def test_catalog_ignores_hidden_generation_copy_and_selects_publication(tmp_path):
    public = _write_bundle(
        tmp_path,
        directory="heimgewebe__repoground/main/run-1",
        stem="repoground-main",
        created_at="2026-07-25T21:09:13Z",
        run_id="run-1",
    )
    _write_bundle(
        tmp_path,
        directory=(
            "heimgewebe__repoground/main/run-1/.repoground-generations/repoground-main/hash"
        ),
        stem="repoground-main",
        created_at="2026-07-25T21:09:13Z",
        run_id="run-1",
    )

    catalog = discover_bundle_catalog(tmp_path)
    selection = select_bundle_manifest(tmp_path, repo="heimgewebe/repoground")

    assert catalog["candidate_count"] == 1
    assert selection["status"] == "available"
    assert selection["selected"]["manifest_path"] == str(public.resolve())


@pytest.mark.parametrize("candidate_kind", ("regular", "internal_symlink"))
def test_catalog_accepts_regular_file_and_internal_manifest_symlink(
    tmp_path, candidate_kind
):
    root = tmp_path / "catalog"
    directory = (
        "repo/main/run" if candidate_kind == "regular" else ".storage/repo/main/run"
    )
    manifest = _write_bundle(
        root,
        directory=directory,
        stem="internal",
        created_at="2026-07-25T21:00:00Z",
        run_id=f"{candidate_kind}-run",
    )
    if candidate_kind == "internal_symlink":
        publication = root / "repo" / "main" / "internal.bundle.manifest.json"
        publication.parent.mkdir(parents=True)
        publication.symlink_to(manifest)

    catalog = discover_bundle_catalog(root)

    assert catalog["candidate_count"] == 1
    assert catalog["candidates"][0]["manifest_path"] == str(manifest.resolve())
    assert catalog["candidates"][0]["health_status"] == "pass"


def test_catalog_bounded_reads_use_portable_open_fallback(tmp_path, monkeypatch):
    manifest = _write_bundle(
        tmp_path,
        directory="repo/main/run",
        stem="portable",
        created_at="2026-07-25T21:00:00Z",
        run_id="portable-run",
    )
    monkeypatch.setattr(bundle_catalog_module.os, "O_NONBLOCK", 0, raising=False)

    catalog = discover_bundle_catalog(tmp_path)

    assert catalog["candidate_count"] == 1
    assert catalog["candidates"][0]["manifest_path"] == str(manifest.resolve())
    assert catalog["candidates"][0]["health_status"] == "pass"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO requires POSIX support")
@pytest.mark.parametrize("via_symlink", (False, True))
def test_catalog_fifo_candidate_without_writer_terminates_and_is_rejected(
    tmp_path, via_symlink
):
    root = tmp_path / "catalog"
    healthy = _write_bundle(
        root,
        directory="repo/main/healthy",
        stem="healthy",
        created_at="2026-07-25T20:00:00Z",
        run_id="healthy-run",
    )
    if via_symlink:
        fifo = root / ".storage" / "blocked.fifo"
        fifo.parent.mkdir(parents=True)
        os.mkfifo(fifo)
        candidate = root / "blocked.bundle.manifest.json"
        candidate.symlink_to(fifo)
    else:
        candidate = root / "blocked.bundle.manifest.json"
        os.mkfifo(candidate)

    script = (
        "import json,sys;"
        "from merger.repoground.core.bundle_catalog import discover_bundle_catalog;"
        "print(json.dumps(discover_bundle_catalog(sys.argv[1])))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(root)],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    catalog = json.loads(completed.stdout)

    assert catalog["candidate_count"] == 1
    assert catalog["candidates"][0]["manifest_path"] == str(healthy.resolve())
    assert catalog["rejected_count"] == 1
    assert catalog["rejected"][0]["manifest_path"] == str(candidate)
    assert "not regular" in catalog["rejected"][0]["reason"]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO requires POSIX support")
@pytest.mark.parametrize("via_symlink", (False, True))
def test_catalog_direct_fifo_root_is_one_rejected_candidate(tmp_path, via_symlink):
    fifo = tmp_path / "blocked.fifo"
    os.mkfifo(fifo)
    if via_symlink:
        candidate = tmp_path / "blocked.bundle.manifest.json"
        candidate.symlink_to(fifo)
    else:
        candidate = tmp_path / "blocked.bundle.manifest.json"
        fifo.rename(candidate)

    script = (
        "import json,sys;"
        "from merger.repoground.core.bundle_catalog import discover_bundle_catalog;"
        "print(json.dumps(discover_bundle_catalog(sys.argv[1])))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(candidate)],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    catalog = json.loads(completed.stdout)

    assert catalog["candidate_count"] == 0
    assert catalog["rejected_count"] == 1
    assert catalog["rejected"][0]["manifest_path"] == str(candidate)
    assert "not regular" in catalog["rejected"][0]["reason"]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO requires POSIX support")
@pytest.mark.parametrize("portable_fallback", (False, True))
def test_catalog_rejects_regular_to_fifo_open_race_as_one_candidate(
    tmp_path, monkeypatch, portable_fallback
):
    root = tmp_path / "catalog"
    healthy = _write_bundle(
        root,
        directory="repo/main/healthy",
        stem="healthy",
        created_at="2026-07-25T20:00:00Z",
        run_id="healthy-run",
    )
    raced = _write_bundle(
        root,
        directory="repo/main/raced",
        stem="raced",
        created_at="2026-07-25T21:00:00Z",
        run_id="raced-run",
    )
    backup = raced.with_name("raced.original")
    exchanged = False

    def exchange_target() -> None:
        nonlocal exchanged
        exchanged = True
        raced.replace(backup)
        os.mkfifo(raced)

    def restore_target() -> None:
        raced.unlink(missing_ok=True)
        backup.replace(raced)

    if portable_fallback:
        original_portable = bundle_catalog_module._read_bounded_portable
        monkeypatch.setattr(bundle_catalog_module.os, "O_NONBLOCK", 0)
        monkeypatch.setattr(bundle_catalog_module, "_OPEN_TIMEOUT_SECONDS", 0.05)

        def exchange_portable(path, max_bytes, expected_identity):
            if not exchanged and Path(path) == raced:
                exchange_target()
                try:
                    return original_portable(path, max_bytes, expected_identity)
                finally:
                    restore_target()
            return original_portable(path, max_bytes, expected_identity)

        monkeypatch.setattr(
            bundle_catalog_module,
            "_read_bounded_portable",
            exchange_portable,
        )
    else:
        original_open = bundle_catalog_module._open_binary

        def exchange_open(path):
            if not exchanged and Path(path) == raced:
                exchange_target()
                try:
                    return original_open(path)
                finally:
                    restore_target()
            return original_open(path)

        monkeypatch.setattr(bundle_catalog_module, "_open_binary", exchange_open)

    catalog = discover_bundle_catalog(root)

    assert exchanged is True
    assert catalog["candidate_count"] == 1
    assert catalog["candidates"][0]["manifest_path"] == str(healthy.resolve())
    assert catalog["rejected_count"] == 1
    assert catalog["rejected"][0]["manifest_path"] == str(raced)
    expected_reason = (
        "open exceeded time bound" if portable_fallback else "not regular"
    )
    assert expected_reason in catalog["rejected"][0]["reason"]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO requires POSIX support")
def test_portable_fifo_timeouts_leave_no_threads_or_children(tmp_path, monkeypatch):
    candidate = _write_bundle(
        tmp_path,
        directory="repo/main/raced",
        stem="raced",
        created_at="2026-07-25T21:00:00Z",
        run_id="raced-run",
    )
    original_portable = bundle_catalog_module._read_bounded_portable
    original_popen = subprocess.Popen
    processes = []

    class RecordingPopen(original_popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            processes.append(self)

    monkeypatch.setattr(bundle_catalog_module.os, "O_NONBLOCK", 0)
    monkeypatch.setattr(bundle_catalog_module, "_OPEN_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(bundle_catalog_module.subprocess, "Popen", RecordingPopen)

    baseline_threads = len(threading.enumerate())
    for attempt in range(3):
        backup = candidate.with_name(f"raced.original.{attempt}")
        candidate.replace(backup)
        os.mkfifo(candidate)
        expected_identity = bundle_catalog_module._file_identity(backup.stat())
        try:
            with pytest.raises(
                bundle_catalog_module.BundleCatalogError,
                match="open exceeded time bound",
            ):
                original_portable(candidate, 4 * 1024 * 1024, expected_identity)
        finally:
            candidate.unlink(missing_ok=True)
            backup.replace(candidate)

    assert len(threading.enumerate()) == baseline_threads
    assert len(processes) == 3
    assert all(process.poll() is not None for process in processes)


@pytest.mark.parametrize("nested", (False, True))
def test_catalog_rejects_manifest_symlink_escape_without_hiding_healthy_candidates(
    tmp_path, monkeypatch, nested
):
    root = tmp_path / "catalog"
    root.mkdir()
    healthy = _write_bundle(
        root,
        directory="repo/main/healthy",
        stem="healthy",
        created_at="2026-07-25T20:00:00Z",
        run_id="healthy-run",
    )
    external = _write_bundle(
        tmp_path / "outside",
        directory="run",
        stem="external",
        created_at="2026-07-25T21:00:00Z",
        run_id="external-run",
    )
    escape = (
        root / "repo" / "main" / "nested" / "escape.bundle.manifest.json"
        if nested
        else root / "escape.bundle.manifest.json"
    )
    escape.parent.mkdir(parents=True, exist_ok=True)
    escape.symlink_to(external)
    opened_paths = []
    original_open = bundle_catalog_module._open_binary

    def record_open(path):
        opened_paths.append(Path(path))
        return original_open(path)

    monkeypatch.setattr(bundle_catalog_module, "_open_binary", record_open)

    catalog = discover_bundle_catalog(root)

    assert catalog["candidate_count"] == 1
    assert catalog["candidates"][0]["manifest_path"] == str(healthy.resolve())
    assert catalog["rejected_count"] == 1
    assert catalog["rejected"][0]["manifest_path"] == str(escape)
    assert "outside catalog root" in catalog["rejected"][0]["reason"]
    assert external.resolve() not in opened_paths
    assert str(external.resolve()) not in json.dumps(catalog, sort_keys=True)


def test_catalog_rejects_open_time_escape_exchange_and_restore_before_read(
    tmp_path, monkeypatch
):
    root = tmp_path / "catalog"
    healthy = _write_bundle(
        root,
        directory="repo/main/healthy",
        stem="healthy",
        created_at="2026-07-25T20:00:00Z",
        run_id="healthy-run",
    )
    internal = _write_bundle(
        root,
        directory=".storage/run",
        stem="selected",
        created_at="2026-07-25T21:00:00Z",
        run_id="internal-run",
    )
    publication = root / "repo" / "selected.bundle.manifest.json"
    publication.parent.mkdir(parents=True, exist_ok=True)
    publication.symlink_to(internal)
    external = _write_bundle(
        tmp_path / "outside",
        directory="run",
        stem="external",
        created_at="2026-07-25T22:00:00Z",
        run_id="external-run",
    )
    original_open = bundle_catalog_module._open_binary
    backup = internal.with_name("selected.original")
    exchanged = False
    external_bytes_read = False

    class TrackingHandle:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.handle.close()
            return False

        def fileno(self):
            return self.handle.fileno()

        def read(self, size):
            nonlocal external_bytes_read
            external_bytes_read = True
            return self.handle.read(size)

    def exchange_around_open(path):
        nonlocal exchanged
        if not exchanged and Path(path) == internal:
            exchanged = True
            internal.replace(backup)
            internal.symlink_to(external)
            try:
                handle = original_open(path)
            finally:
                internal.unlink()
                backup.replace(internal)
            return TrackingHandle(handle)
        return original_open(path)

    monkeypatch.setattr(bundle_catalog_module, "_open_binary", exchange_around_open)

    catalog = discover_bundle_catalog(root)

    assert exchanged is True
    assert external_bytes_read is False
    assert catalog["candidate_count"] == 1
    assert catalog["candidates"][0]["manifest_path"] == str(healthy.resolve())
    assert catalog["rejected_count"] == 1
    assert catalog["rejected"][0]["manifest_path"] == str(publication)
    assert any(
        text in catalog["rejected"][0]["reason"]
        for text in ("cannot be read", "identity changed")
    )
    assert str(external.resolve()) not in json.dumps(catalog, sort_keys=True)


def test_selector_skips_newer_unhealthy_bundle(tmp_path):
    healthy = _write_bundle(
        tmp_path,
        directory="repo/main/healthy",
        stem="healthy",
        created_at="2026-07-25T20:00:00Z",
        run_id="healthy-run",
    )
    _write_bundle(
        tmp_path,
        directory="repo/main/unhealthy",
        stem="unhealthy",
        created_at="2026-07-25T21:00:00Z",
        run_id="unhealthy-run",
        output_status="fail",
    )

    selection = select_bundle_manifest(tmp_path, repo="repoground")

    assert selection["status"] == "available"
    assert selection["selected"]["manifest_path"] == str(healthy.resolve())
    assert selection["match_count"] == 1


def test_selector_rejects_output_health_without_valid_integrity_metadata(tmp_path):
    cases = (
        ("missing-bytes", lambda artifact: artifact.pop("bytes")),
        ("missing-sha", lambda artifact: artifact.pop("sha256")),
        ("malformed-sha", lambda artifact: artifact.update({"sha256": "bad"})),
    )
    for label, mutate in cases:
        manifest = _write_bundle(
            tmp_path,
            directory=f"repo/main/{label}",
            stem=label,
            created_at="2026-07-25T21:00:00Z",
            run_id=f"{label}-run",
        )
        document = json.loads(manifest.read_text(encoding="utf-8"))
        artifact = next(
            item for item in document["artifacts"] if item["role"] == "output_health"
        )
        mutate(artifact)
        _write_json(manifest, document)

    catalog = discover_bundle_catalog(tmp_path)
    selection = select_bundle_manifest(tmp_path, repo="repoground")

    assert selection["status"] == "missing"
    assert {item["stem"] for item in catalog["candidates"]} == {
        "missing-bytes",
        "missing-sha",
        "malformed-sha",
    }
    assert all(item["selection_eligible"] is False for item in catalog["candidates"])
    reasons = " ".join(
        reason for item in catalog["candidates"] for reason in item["health_reasons"]
    )
    assert "byte size missing or invalid" in reasons
    assert "sha256 missing or invalid" in reasons


def test_selector_rejects_post_health_bound_to_another_publication(tmp_path):
    manifest = _write_bundle(
        tmp_path,
        directory="repo/main/stale-post",
        stem="stale-post",
        created_at="2026-07-25T21:00:00Z",
        run_id="stale-post-run",
    )
    document = json.loads(manifest.read_text(encoding="utf-8"))
    post_path = manifest.parent / document["links"]["post_emit_health_path"]
    stale = json.loads(post_path.read_text(encoding="utf-8"))
    stale.update(
        {
            "bundle_manifest_path": str(
                (tmp_path / "other.bundle.manifest.json").resolve()
            ),
            "bundle_run_id": "other-run",
            "bundle_manifest_sha256": "0" * 64,
        }
    )
    _write_json(post_path, stale)

    catalog = discover_bundle_catalog(tmp_path)
    selection = select_bundle_manifest(tmp_path, repo="repoground")

    assert selection["status"] == "missing"
    candidate = next(
        item for item in catalog["candidates"] if item["stem"] == "stale-post"
    )
    assert candidate["selection_eligible"] is False
    assert candidate["health_status"] == "invalid"
    assert any("does not match" in reason for reason in candidate["health_reasons"])


def test_selector_fails_closed_for_equal_newest_identity(tmp_path):
    for directory in ("repo/main/a", "repo/main/b"):
        _write_bundle(
            tmp_path,
            directory=directory,
            stem=Path(directory).name,
            created_at="2026-07-25T21:00:00Z",
            run_id="same-run",
        )

    selection = select_bundle_manifest(tmp_path, repo="heimgewebe/repoground")

    assert selection["status"] == "ambiguous"
    assert selection["reason"] == "newest_bundle_identity_ambiguous"
    assert selection["selected"] is None
