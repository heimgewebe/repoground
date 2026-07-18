import fcntl
import json
import os
from pathlib import Path
import threading

import pytest

from merger.repoground.retrieval.incremental_snapshot import (
    IncrementalRetrievalSnapshot,
    SnapshotConfig,
    SnapshotWatcher,
)
from merger.repoground.cli.main import main


def _snapshot(tmp_path: Path) -> tuple[Path, IncrementalRetrievalSnapshot]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "alpha.py").write_text("def alpha():\n    return 'needle alpha'\n", encoding="utf-8")
    (source / "beta.py").write_text("def beta():\n    return 'needle beta'\n", encoding="utf-8")
    return source, IncrementalRetrievalSnapshot(source, tmp_path / "snapshots", SnapshotConfig(repo_id="test"))


def _rows(snapshot: IncrementalRetrievalSnapshot) -> list[dict]:
    current = snapshot.status()
    assert current
    path = snapshot.storage_root / "generations" / current["generation_id"] / "chunks.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]



def test_source_and_storage_roots_must_not_overlap(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="must not overlap"):
        IncrementalRetrievalSnapshot(source, source / "snapshots")
    storage = tmp_path / "storage"
    storage.mkdir()
    nested_source = storage / "source"
    nested_source.mkdir()
    with pytest.raises(ValueError, match="must not overlap"):
        IncrementalRetrievalSnapshot(nested_source, storage)


def test_parallel_build_waits_for_exclusive_writer_lock(tmp_path: Path) -> None:
    _, snapshot = _snapshot(tmp_path)
    snapshot.storage_root.mkdir(parents=True, exist_ok=True)
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def build() -> None:
        started.set()
        try:
            snapshot.build()
        except BaseException as exc:  # preserve the worker failure for the main assertion
            errors.append(exc)
        finally:
            finished.set()

    with snapshot.build_lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        worker = threading.Thread(target=build, daemon=True)
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    worker.join(5)
    assert not worker.is_alive()
    assert errors == []
    assert snapshot.status() is not None


def test_build_lock_rejects_symlink(tmp_path: Path) -> None:
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("O_NOFOLLOW is required for this boundary test")
    _, snapshot = _snapshot(tmp_path)
    snapshot.storage_root.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.lock"
    outside.write_text("unchanged", encoding="utf-8")
    snapshot.build_lock_path.symlink_to(outside)

    with pytest.raises(OSError):
        snapshot.build()

    assert outside.read_text(encoding="utf-8") == "unchanged"

def test_noop_reuses_current_generation(tmp_path: Path) -> None:
    _, snapshot = _snapshot(tmp_path)
    first = snapshot.build()
    second = snapshot.build()
    assert first.published
    assert second.no_op
    assert second.generation_id == first.generation_id


def test_change_reuses_unchanged_file_chunks(tmp_path: Path) -> None:
    source, snapshot = _snapshot(tmp_path)
    snapshot.build()
    original_beta = [row for row in _rows(snapshot) if row["path"] == "beta.py"]
    (source / "alpha.py").write_text("def alpha():\n    return 'changed token'\n", encoding="utf-8")
    result = snapshot.build()
    current_beta = [row for row in _rows(snapshot) if row["path"] == "beta.py"]
    assert result.receipt["files"]["changed"] == ["alpha.py"]
    assert result.receipt["files"]["reused"] == ["beta.py"]
    assert current_beta == original_beta
    assert snapshot.query("changed")["results"][0]["path"] == "alpha.py"


def test_change_reuses_unchunked_empty_files(tmp_path: Path) -> None:
    source, snapshot = _snapshot(tmp_path)
    (source / "empty.py").write_text("", encoding="utf-8")
    snapshot.build()
    (source / "alpha.py").write_text("def alpha(): return 'changed'\n", encoding="utf-8")
    result = snapshot.build()
    assert "empty.py" in result.receipt["files"]["reused"]
    assert "empty.py" not in result.receipt["files"]["changed"]


def test_delete_and_rename_remove_old_paths(tmp_path: Path) -> None:
    source, snapshot = _snapshot(tmp_path)
    snapshot.build()
    (source / "alpha.py").unlink()
    (source / "beta.py").rename(source / "renamed.py")
    result = snapshot.build()
    paths = {row["path"] for row in _rows(snapshot)}
    assert paths == {"renamed.py"}
    assert result.receipt["files"]["deleted"] == ["alpha.py", "beta.py"]
    assert result.receipt["files"]["added"] == ["renamed.py"]
    assert snapshot.query("alpha")["count"] == 0


def test_crash_before_publication_keeps_previous_generation_visible(tmp_path: Path) -> None:
    source, snapshot = _snapshot(tmp_path)
    first = snapshot.build()
    (source / "alpha.py").write_text("def alpha(): return 'new'\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="before retrieval snapshot publication"):
        snapshot.build(crash_before_publish=True)
    assert snapshot.status()["generation_id"] == first.generation_id
    assert snapshot.query("needle")["count"] == 2


def test_incremental_equals_full_build_and_retrieval(tmp_path: Path) -> None:
    source, incremental = _snapshot(tmp_path)
    incremental.build(verify_full_build=True)
    (source / "alpha.py").write_text("def alpha():\n    return 'needle changed'\n", encoding="utf-8")
    checked = incremental.build(verify_full_build=True)
    full = IncrementalRetrievalSnapshot(source, tmp_path / "full", SnapshotConfig(repo_id="test"))
    full.build()
    assert _rows(incremental) == _rows(full)
    assert checked.receipt["full_build_comparison"]["result"] == "equal"
    assert incremental.query("needle")["results"] == full.query("needle")["results"]


def test_reader_never_builds_when_no_snapshot_exists(tmp_path: Path) -> None:
    _, snapshot = _snapshot(tmp_path)
    with pytest.raises(FileNotFoundError):
        snapshot.query("needle")
    assert not snapshot.current_pointer_path.exists()


def test_full_verify_checks_the_current_noop_generation(tmp_path: Path) -> None:
    _, snapshot = _snapshot(tmp_path)
    snapshot.build()
    verified = snapshot.full_verify()
    assert verified["build"]["result"] == "no_op"
    assert verified["verified"]["result"] == "equal"


def test_watcher_debounce_queue_backoff_and_last_successful_generation(tmp_path: Path, monkeypatch) -> None:
    _, snapshot = _snapshot(tmp_path)
    watcher = SnapshotWatcher(snapshot, debounce_seconds=2, queue_limit=2, base_backoff_seconds=3)
    assert watcher.notify_change(now=10)
    assert watcher.notify_change(now=11)
    assert not watcher.notify_change(now=12)
    assert watcher.tick(now=12) is None
    first = watcher.tick(now=13)
    assert first and watcher.last_successful_generation == first.generation_id
    assert watcher.notify_change(now=20)
    monkeypatch.setattr(snapshot, "build", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        watcher.tick(now=22)
    assert watcher.tick(now=24) is None


def test_cli_status_is_read_only_and_watcher_writes_visible_atomic_status(tmp_path: Path, capsys) -> None:
    source, snapshot = _snapshot(tmp_path)
    assert main(["retrieval-snapshot", "status", "--storage", str(snapshot.storage_root)]) == 0
    assert json.loads(capsys.readouterr().out) == {"pointer": None, "snapshot": None, "watcher": None}
    assert not snapshot.current_pointer_path.exists()
    assert main([
        "retrieval-snapshot", "watch", "--source", str(source), "--storage", str(snapshot.storage_root),
        "--repo-id", "test", "--poll-seconds", "0.01", "--debounce-seconds", "0", "--run-seconds", "0.05",
    ]) == 0
    watcher_status = json.loads(snapshot.watcher_status_path.read_text(encoding="utf-8"))
    assert watcher_status["state"] == "stopped"
    assert watcher_status["last_successful_generation"] == snapshot.status()["generation_id"]


def test_cli_build_full_verify_and_measurement_report(tmp_path: Path, capsys) -> None:
    source, snapshot = _snapshot(tmp_path)
    common = ["--source", str(source), "--storage", str(snapshot.storage_root), "--repo-id", "test"]
    assert main(["retrieval-snapshot", "build", *common]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "published"
    assert main(["retrieval-snapshot", "full-verify", *common]) == 0
    assert json.loads(capsys.readouterr().out)["verified"]["result"] == "equal"
    report = tmp_path / "measurement.json"
    assert main(["retrieval-snapshot", "measure", *common, "--report", str(report)]) == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["results"]["no_op"] is True
    assert data["repository"]["source"] == "."
    assert data["repository"]["absolute_source_path_persisted"] is False
    assert str(source) not in report.read_text(encoding="utf-8")
    assert set(data["runs"]) == {"full_build", "incremental_change", "no_op"}


def test_committed_measurement_binds_inputs_configuration_and_all_runs() -> None:
    root = Path(__file__).resolve().parents[3]
    report = json.loads((root / "docs/proofs/repoground-incremental-retrieval-snapshot-v1.measurement.json").read_text(encoding="utf-8"))
    assert report["schema"] == "repoground.incremental-retrieval-measurement.v1"
    assert report["repository"]["commit"]
    assert report["repository"]["source"] == "."
    assert report["repository"]["absolute_source_path_persisted"] is False
    assert "/home/" not in json.dumps(report["repository"])
    assert len(report["repository"]["input_tree_sha256"]) == 64
    assert len(report["configuration"]["sha256"]) == 64
    assert report["results"]["freshness_latency_seconds"] >= 0
    for timing in report["runs"].values():
        assert timing["wall_seconds"] >= 0
        assert timing["cpu_seconds"] >= 0
        assert timing["io_method"] in {"linux_proc_self_io", "output_tree_bytes_delta_only"}
