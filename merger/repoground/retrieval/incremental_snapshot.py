"""Explicit, publish-only incremental snapshots for local retrieval.

This module intentionally has no import-time work and no read-side fallback to a
builder.  A caller must invoke :meth:`IncrementalRetrievalSnapshot.build` (or a
separate watcher) to create a generation.  Readers only follow the committed
``current.json`` pointer and open its SQLite database immutable/read-only.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import time
import uuid
from typing import Any, Iterable, Mapping, Optional

from ..core.chunker import Chunker
from . import index_db, query_core


SNAPSHOT_SCHEMA = "repoground.incremental-retrieval-snapshot.v1"
_GENERATION_DIR = "generations"
_STAGING_DIR = ".staging"
_CURRENT = "current.json"
_WATCHER_STATUS = "watcher-status.json"
_BUILD_LOCK = ".build.lock"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(_canonical_json(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _fsync_dir(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


@dataclass(frozen=True)
class SnapshotConfig:
    """The chunking contract.  A changed configuration invalidates reuse."""

    repo_id: str = "local"
    max_size: int = 8192
    max_lines: int = 400
    min_size: int = 2048
    min_lines: int = 200
    include_extensions: tuple[str, ...] = ()

    def fingerprint(self) -> str:
        payload = asdict(self)
        payload["include_extensions"] = sorted(payload["include_extensions"])
        payload["snapshot_schema"] = SNAPSHOT_SCHEMA
        return _sha256(_canonical_json(payload))


@dataclass(frozen=True)
class SnapshotBuildResult:
    generation_id: str
    published: bool
    no_op: bool
    receipt: Mapping[str, Any]


class IncrementalRetrievalSnapshot:
    """Build and read immutable retrieval generations rooted at ``storage_root``."""

    def __init__(self, source_root: Path, storage_root: Path, config: SnapshotConfig = SnapshotConfig()):
        self.source_root = Path(source_root).resolve()
        self.storage_root = Path(storage_root).resolve()
        if (
            self.source_root == self.storage_root
            or self.storage_root.is_relative_to(self.source_root)
            or self.source_root.is_relative_to(self.storage_root)
        ):
            raise ValueError("source and storage roots must not overlap")
        self.config = config

    @property
    def build_lock_path(self) -> Path:
        return self.storage_root / _BUILD_LOCK

    @contextmanager
    def _exclusive_build_lock(self):
        self.storage_root.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.build_lock_path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "a+b", closefd=True) as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                yield
        finally:
            # fdopen owns the descriptor on the normal path; close only if setup
            # failed before ownership transferred.
            try:
                os.close(descriptor)
            except OSError:
                pass

    @property
    def current_pointer_path(self) -> Path:
        return self.storage_root / _CURRENT

    def recover(self) -> int:
        """Remove abandoned staging directories; committed generations are immutable."""
        staging = self.storage_root / _STAGING_DIR
        if not staging.exists():
            return 0
        removed = 0
        for candidate in staging.iterdir():
            if candidate.is_dir() and not candidate.is_symlink():
                shutil.rmtree(candidate)
                removed += 1
        return removed

    @property
    def watcher_status_path(self) -> Path:
        """The atomically replaced, externally visible watcher state."""
        return self.storage_root / _WATCHER_STATUS

    def status(self) -> Optional[Mapping[str, Any]]:
        """Return the last successfully published generation without mutating state."""
        if not self.current_pointer_path.exists():
            return None
        pointer = json.loads(self.current_pointer_path.read_text(encoding="utf-8"))
        generation = self.storage_root / _GENERATION_DIR / pointer["generation_id"] / "snapshot.json"
        if not generation.exists():
            raise RuntimeError("current retrieval snapshot points to a missing generation")
        return json.loads(generation.read_text(encoding="utf-8"))

    def full_verify(self) -> Mapping[str, Any]:
        """Compare the committed generation with a from-scratch chunk build.

        This is explicitly a write-side operation: it may create a new generation
        if source content changed.  Read commands deliberately never call it.
        """
        result = self.build(verify_full_build=True)
        comparison = result.receipt.get("full_build_comparison")
        if comparison is None:
            current = self.status()
            assert current is not None
            expected: list[dict[str, Any]] = []
            for relative_path, content in self._source_files():
                expected.extend(self._chunk_file(relative_path, content, _sha256(content)))
            expected.sort(key=lambda row: (row["path"], row["start_byte"], row["chunk_id"]))
            chunk_path = self.storage_root / _GENERATION_DIR / current["generation_id"] / "chunks.jsonl"
            with chunk_path.open(encoding="utf-8") as handle:
                actual = [json.loads(line) for line in handle]
            comparison = {"result": "equal" if expected == actual else "different", "full_chunk_count": len(expected)}
        if comparison and comparison["result"] != "equal":
            raise RuntimeError("incremental retrieval snapshot differs from full build")
        return {"build": result.receipt, "verified": comparison}

    def query(self, query_text: str, **kwargs: Any) -> Mapping[str, Any]:
        """Query the last committed generation only; this method never builds."""
        current = self.status()
        if current is None:
            raise FileNotFoundError("no published retrieval snapshot")
        index_path = self.storage_root / _GENERATION_DIR / current["generation_id"] / "chunks.index.sqlite"
        return query_core.execute_query(index_path.resolve(), query_text, read_only=True, **kwargs)

    def build(
        self,
        *,
        crash_before_publish: bool = False,
        verify_full_build: bool = False,
    ) -> SnapshotBuildResult:
        """Serialize writers, stage one generation, then switch the pointer."""
        with self._exclusive_build_lock():
            return self._build_unlocked(
                crash_before_publish=crash_before_publish,
                verify_full_build=verify_full_build,
            )

    def _build_unlocked(
        self,
        *,
        crash_before_publish: bool = False,
        verify_full_build: bool = False,
    ) -> SnapshotBuildResult:
        self.recover()
        previous = self.status()
        config_fingerprint = self.config.fingerprint()
        files = list(self._source_files())
        source_files = {path: _sha256(data) for path, data in files}
        content_fingerprint = _sha256(_canonical_json(source_files))

        if previous and previous["config_fingerprint"] == config_fingerprint and previous["content_fingerprint"] == content_fingerprint:
            receipt = {
                "schema": SNAPSHOT_SCHEMA,
                "generation_id": previous["generation_id"],
                "result": "no_op",
                "content_fingerprint": content_fingerprint,
                "config_fingerprint": config_fingerprint,
            }
            return SnapshotBuildResult(previous["generation_id"], False, True, receipt)

        previous_rows = self._rows_for_reuse(previous, config_fingerprint)
        rows: list[dict[str, Any]] = []
        added, changed, reused = [], [], []
        old_files = (previous or {}).get("source_files", {})
        for relative_path, content in files:
            file_sha = source_files[relative_path]
            if previous and previous.get("config_fingerprint") == config_fingerprint and old_files.get(relative_path) == file_sha:
                # Empty or non-chunked files intentionally have no prior rows but
                # are still reusable according to the source-file content hash.
                rows.extend(previous_rows.get(relative_path, ()))
                reused.append(relative_path)
                continue
            (changed if relative_path in old_files else added).append(relative_path)
            rows.extend(self._chunk_file(relative_path, content, file_sha))
        deleted = sorted(set(old_files) - set(source_files))
        rows.sort(key=lambda row: (row["path"], row["start_byte"], row["chunk_id"]))

        generation_id = f"g-{uuid.uuid4().hex}"
        stage = self.storage_root / _STAGING_DIR / generation_id
        final = self.storage_root / _GENERATION_DIR / generation_id
        stage.mkdir(parents=True, exist_ok=False)
        try:
            chunk_path = stage / "chunks.jsonl"
            with chunk_path.open("w", encoding="utf-8", newline="\n") as handle:
                for row in rows:
                    handle.write(_canonical_json(row).decode("utf-8") + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            # index_db uses its established schema/FTS builder. Inline content keeps
            # this snapshot self-contained; dump_index is provenance, not a copier.
            dump_path = stage / "dump_index.json"
            _atomic_json(dump_path, {"schema": SNAPSHOT_SCHEMA, "generation_id": generation_id})
            index_path = stage / "chunks.index.sqlite"
            index_db.build_index(dump_path, chunk_path, index_path, {
                "config_sha256": config_fingerprint,
                "snapshot_schema": SNAPSHOT_SCHEMA,
            })
            _fsync_file(index_path)
            receipt = {
                "schema": SNAPSHOT_SCHEMA,
                "generation_id": generation_id,
                "result": "published",
                "content_fingerprint": content_fingerprint,
                "config_fingerprint": config_fingerprint,
                "files": {"added": sorted(added), "changed": sorted(changed), "deleted": deleted, "reused": sorted(reused)},
                "chunks": {"total": len(rows), "reused_files": len(reused)},
                "artifacts": {name: _sha256((stage / name).read_bytes()) for name in ("chunks.jsonl", "chunks.index.sqlite")},
            }
            if verify_full_build:
                full_rows = []
                for relative_path, content in files:
                    full_rows.extend(self._chunk_file(relative_path, content, source_files[relative_path]))
                full_rows.sort(key=lambda row: (row["path"], row["start_byte"], row["chunk_id"]))
                receipt["full_build_comparison"] = {
                    "result": "equal" if full_rows == rows else "different",
                    "full_chunk_count": len(full_rows),
                }
            snapshot = dict(receipt)
            snapshot["source_files"] = source_files
            _atomic_json(stage / "receipt.json", receipt)
            _atomic_json(stage / "snapshot.json", snapshot)
            _fsync_dir(stage)
            if crash_before_publish:
                raise RuntimeError("simulated crash before retrieval snapshot publication")
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage, final)
            _fsync_dir(final.parent)
            _atomic_json(self.current_pointer_path, {"generation_id": generation_id})
            return SnapshotBuildResult(generation_id, True, False, receipt)
        except Exception:
            # A failed staging tree is deliberately not published.  It is removed by
            # this process or the next explicit build/watcher recovery.
            if stage.exists():
                shutil.rmtree(stage)
            raise

    def _source_files(self) -> Iterable[tuple[str, bytes]]:
        if not self.source_root.is_dir():
            raise NotADirectoryError(self.source_root)
        extensions = {extension.lower() for extension in self.config.include_extensions}
        for path in sorted(self.source_root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(self.source_root).as_posix()
            if relative.startswith(".git/"):
                continue
            if extensions and path.suffix.lower() not in extensions:
                continue
            content = path.read_bytes()
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            yield relative, content

    def _rows_for_reuse(self, previous: Optional[Mapping[str, Any]], config_fingerprint: str) -> dict[str, list[dict[str, Any]]]:
        if not previous or previous.get("config_fingerprint") != config_fingerprint:
            return {}
        path = self.storage_root / _GENERATION_DIR / previous["generation_id"] / "chunks.jsonl"
        result: dict[str, list[dict[str, Any]]] = {}
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                result.setdefault(row["path"], []).append(row)
        return result

    def _chunk_file(self, relative_path: str, data: bytes, file_sha: str) -> list[dict[str, Any]]:
        content = data.decode("utf-8")
        chunks = Chunker(self.config.min_size, self.config.max_size, self.config.min_lines, self.config.max_lines).chunk_file(
            f"file:{file_sha}", content, file_path=relative_path
        )
        records = []
        for chunk in chunks:
            excerpt = data[chunk.start_byte:chunk.end_byte].decode("utf-8")
            records.append({
                "chunk_id": chunk.chunk_id, "repo_id": self.config.repo_id, "path": relative_path,
                "layer": "source", "artifact_type": "source_file", "start_byte": chunk.start_byte,
                "end_byte": chunk.end_byte, "start_line": chunk.start_line, "end_line": chunk.end_line,
                "sha256": chunk.sha256, "size": chunk.size, "language": Path(relative_path).suffix.lstrip("."),
                "source_file": relative_path, "content": excerpt,
            })
        return records


@dataclass
class SnapshotWatcher:
    """Optional external-event watcher with debounce, bounded queue and backoff.

    Hosts provide filesystem events through ``notify_change`` and call ``tick``;
    this keeps observing separate from the retrieval read path and avoids an
    optional platform watcher dependency.
    """

    snapshot: IncrementalRetrievalSnapshot
    debounce_seconds: float = 0.25
    queue_limit: int = 128
    base_backoff_seconds: float = 1.0
    _events: list[float] = field(default_factory=list)
    _retry_at: float = 0.0
    _failures: int = 0
    last_successful_generation: Optional[str] = None

    def __post_init__(self) -> None:
        self.snapshot.recover()
        current = self.snapshot.status()
        self.last_successful_generation = current and current["generation_id"]

    def notify_change(self, now: Optional[float] = None) -> bool:
        if len(self._events) >= self.queue_limit:
            return False
        self._events.append(time.monotonic() if now is None else now)
        return True

    def tick(self, now: Optional[float] = None) -> Optional[SnapshotBuildResult]:
        now = time.monotonic() if now is None else now
        if not self._events or now < self._retry_at or now - self._events[-1] < self.debounce_seconds:
            return None
        # Coalesce all events into one explicit incremental build.  Keep one event
        # on failure so the process retries without requiring a new FS event.
        self._events.clear()
        try:
            result = self.snapshot.build()
        except Exception:
            self._failures += 1
            self._retry_at = now + self.base_backoff_seconds * (2 ** (self._failures - 1))
            self._events.append(now)
            raise
        self._failures = 0
        self._retry_at = 0.0
        self.last_successful_generation = result.generation_id
        return result


def source_poll_marker(source_root: Path, config: SnapshotConfig) -> str:
    """Cheap polling marker; content hashing remains the build correctness check."""
    root = Path(source_root)
    extensions = {extension.lower() for extension in config.include_extensions}
    entries: list[tuple[str, int, int]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(".git/") or (extensions and path.suffix.lower() not in extensions):
            continue
        stat = path.stat()
        entries.append((relative, stat.st_size, stat.st_mtime_ns))
    return _sha256(_canonical_json(entries))


def _install_stop_handlers(callback: Any) -> dict[int, Any]:
    """Install bounded watcher stop handlers when called from the main thread."""
    previous: dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[signum] = signal.signal(signum, callback)
        except ValueError:  # called from a non-main test thread
            continue
    return previous


def _restore_signal_handlers(previous: Mapping[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def run_polling_watcher(
    snapshot: IncrementalRetrievalSnapshot,
    *,
    poll_seconds: float = 1.0,
    debounce_seconds: float = 0.25,
    queue_limit: int = 128,
    base_backoff_seconds: float = 1.0,
    max_backoff_seconds: float = 60.0,
    stop_after: Optional[float] = None,
) -> int:
    """Run the optional stdlib-only watcher until SIGINT/SIGTERM.

    It is intentionally invoked only by the explicit CLI ``watch`` command and
    is not installed or started by the package.
    """
    if poll_seconds <= 0 or debounce_seconds < 0 or queue_limit < 1 or base_backoff_seconds <= 0:
        raise ValueError("invalid watcher timing or queue configuration")
    recovered = snapshot.recover()
    watcher = SnapshotWatcher(snapshot, debounce_seconds, queue_limit, base_backoff_seconds)
    started = time.time()
    stopped = False
    marker = source_poll_marker(snapshot.source_root, snapshot.config)

    def publish(state: str, **extra: Any) -> None:
        _atomic_json(snapshot.watcher_status_path, {
            "schema": SNAPSHOT_SCHEMA,
            "state": state,
            "pid": os.getpid(),
            "started_at_epoch": started,
            "updated_at_epoch": time.time(),
            "source_root": str(snapshot.source_root),
            "storage_root": str(snapshot.storage_root),
            "last_successful_generation": watcher.last_successful_generation,
            "queued_events": len(watcher._events),
            "failures": watcher._failures,
            "recovered_staging_directories": recovered,
            **extra,
        })

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal stopped
        stopped = True

    previous_handlers = _install_stop_handlers(stop)
    # A newly started watcher requests one explicit initial build; it never makes
    # a read-side operation build implicitly.
    watcher.notify_change()
    publish("running", initial_build_queued=True)
    try:
        while not stopped:
            if stop_after is not None and time.monotonic() >= stop_after:
                break
            time.sleep(poll_seconds)
            next_marker = source_poll_marker(snapshot.source_root, snapshot.config)
            if next_marker != marker:
                marker = next_marker
                accepted = watcher.notify_change()
                publish("running", event_accepted=accepted)
            try:
                result = watcher.tick()
                if result is not None:
                    publish("running", last_result=result.receipt)
            except Exception as exc:
                delay = min(max_backoff_seconds, base_backoff_seconds * (2 ** (watcher._failures - 1)))
                watcher._retry_at = time.monotonic() + delay
                publish("backing_off", last_error=str(exc), retry_at_monotonic=watcher._retry_at)
        publish("stopped")
        return 0
    except BaseException as exc:
        publish("crashed", last_error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        _restore_signal_handlers(previous_handlers)
