import json
import threading
import itertools
import collections
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
from typing import List, Optional, Dict, Tuple, Callable
from .models import Job, Artifact

from merger.repoground.core.merge import MERGES_DIR_NAME, get_merges_dir
from .source_acquisition import prune_source_snapshots, remove_source_snapshot

logger = logging.getLogger(__name__)


class JobStore:
    def __init__(self, hub_path: Path):
        self.hub_path = hub_path
        self.storage_dir = self.hub_path / MERGES_DIR_NAME / ".repoground-service"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_file = self.storage_dir / "jobs.json"
        self.artifacts_file = self.storage_dir / "artifacts.json"
        self.logs_dir = self.storage_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

        self._jobs_cache: Dict[str, Job] = {}
        self._artifacts_cache: Dict[str, Artifact] = {}
        self._log_subscribers: Dict[str, List[Callable[[], None]]] = collections.defaultdict(list)
        self._snapshot_cleanup_lock = threading.Lock()

        self._load()

    def _load(self) -> None:
        with self._lock:
            if self.jobs_file.exists():
                try:
                    data = json.loads(self.jobs_file.read_text(encoding="utf-8"))
                    for j in data:
                        job = Job(**j)
                        self._jobs_cache[job.id] = job
                except Exception as e:
                    logger.error("Error loading jobs: %s", e)

            if self.artifacts_file.exists():
                try:
                    data = json.loads(self.artifacts_file.read_text(encoding="utf-8"))
                    for a in data:
                        art = Artifact(**a)
                        self._artifacts_cache[art.id] = art
                except Exception as e:
                    logger.error("Error loading artifacts: %s", e)

    def _save_jobs(self) -> None:
        tmp_file = self.jobs_file.with_suffix(".tmp")
        tmp_file.parent.mkdir(parents=True, exist_ok=True)
        data = [j.model_dump() for j in self._jobs_cache.values()]
        tmp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp_file.rename(self.jobs_file)

    def _save_artifacts(self) -> None:
        tmp_file = self.artifacts_file.with_suffix(".tmp")
        tmp_file.parent.mkdir(parents=True, exist_ok=True)
        data = [a.model_dump() for a in self._artifacts_cache.values()]
        tmp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp_file.rename(self.artifacts_file)

    def add_job(self, job: Job):
        with self._lock:
            self._jobs_cache[job.id] = job
            self._save_jobs()

    def subscribe_to_logs(self, job_id: str, callback: Callable[[], None]):
        with self._lock:
            self._log_subscribers[job_id].append(callback)

    def log_subscriber_count(self, job_id: str) -> int:
        with self._lock:
            return len(self._log_subscribers.get(job_id, []))

    def unsubscribe_from_logs(self, job_id: str, callback: Callable[[], None]):
        with self._lock:
            if job_id in self._log_subscribers:
                try:
                    self._log_subscribers[job_id].remove(callback)
                except ValueError:
                    pass
                if not self._log_subscribers[job_id]:
                    del self._log_subscribers[job_id]

    def _notify_log_subscribers(self, job_id: str):
        # Obtain a copy of callbacks under the lock to avoid modifying during iteration
        with self._lock:
            callbacks = list(self._log_subscribers.get(job_id, []))

        # Invoke outside of the lock
        for callback in callbacks:
            try:
                callback()
            except Exception as e:
                logger.debug("Error in log subscriber callback for %s: %s", job_id, e)

    def update_job(self, job: Job):
        with self._lock:
            self._jobs_cache[job.id] = job
            self._save_jobs()
        self._notify_log_subscribers(job.id)

    def append_log_line(self, job_id: str, line: str):
        with self._lock:
            p = self.logs_dir / f"{job_id}.log"
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8", errors="replace") as f:
                f.write(line + "\n")
        self._notify_log_subscribers(job_id)

    def read_log_lines(self, job_id: str) -> List[str]:
        with self._lock:
            p = self.logs_dir / f"{job_id}.log"
            try:
                if not p.exists():
                    return []
                return p.read_text(encoding="utf-8", errors="replace").splitlines()
            except FileNotFoundError:
                return []

    def read_log_chunk(self, job_id: str, last_line_id: int) -> List[Tuple[str, int]]:
        with self._lock:
            p = self.logs_dir / f"{job_id}.log"
            if not p.exists():
                return []

            try:
                with p.open("r", encoding="utf-8", errors="replace") as f:
                    # Defensive clamp to guarantee non-negative progression
                    skip_count = max(0, last_line_id)

                    if skip_count > 0:
                        collections.deque(
                            itertools.islice(f, skip_count),
                            maxlen=0
                        )

                    new_lines: List[Tuple[str, int]] = []
                    current_id = skip_count  # current_id is last_sent_line_id (1-based); next line gets +1

                    for line in f:
                        current_id += 1
                        new_lines.append((line.rstrip("\r\n"), current_id))

                    return new_lines

            except FileNotFoundError:
                return []
            except Exception as e:
                logger.debug(
                    "read_log_chunk failed for %s: %s",
                    job_id,
                    e,
                    exc_info=True
                )
                return []

    def remove_job(self, job_id: str):
        with self._lock:
            self._remove_job_internal(job_id)
            self._save_jobs()
            self._save_artifacts()

    def _remove_job_internal(self, job_id: str):
        job = self._jobs_cache.get(job_id)
        if not job:
            return

        def _safe_unlink(base: Path, rel: str) -> None:
            if not rel or os.path.isabs(rel):
                return
            try:
                target = (base / rel).resolve()
                target.relative_to(base.resolve())
                if target.exists():
                    target.unlink()
            except Exception as exc:
                logger.warning("Failed to delete artifact file %s relative to %s: %s", rel, base, exc)

        for art_id in job.artifact_ids:
            art = self._artifacts_cache.get(art_id)
            if art:
                try:
                    merges_dir = (
                        Path(art.params.merges_dir)
                        if art.params.merges_dir
                        else get_merges_dir(Path(art.hub))
                    )
                    if merges_dir.exists():
                        for fname in art.paths.values():
                            _safe_unlink(merges_dir, fname)
                except Exception as exc:
                    logger.warning("Failed to clean up artifact %s for job %s: %s", art_id, job_id, exc)
                del self._artifacts_cache[art_id]

        self._remove_source_snapshot_for_job(job_id)

        log_p = self.logs_dir / f"{job_id}.log"
        try:
            if log_p.exists():
                log_p.unlink()
        except Exception as exc:
            logger.warning("Failed to delete log file for job %s: %s", job_id, exc)

        # Notify any waiting SSE streams before we drop the job so they can exit gracefully.
        self._notify_log_subscribers(job_id)

        with self._lock:
            # Cleanup subscribers to prevent memory leaks if streams don't exit.
            self._log_subscribers.pop(job_id, None)
            self._jobs_cache.pop(job_id, None)

    def _remove_source_snapshot_for_job(self, job_id: str) -> None:
        try:
            with self._snapshot_cleanup_lock:
                remove_source_snapshot(get_merges_dir(self.hub_path), job_id)
        except Exception as exc:
            logger.warning("Failed to delete source snapshot for job %s: %s", job_id, exc)

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs_cache.get(job_id)

    def get_all_jobs(self) -> List[Job]:
        with self._lock:
            return sorted(
                self._jobs_cache.values(),
                key=lambda x: x.created_at,
                reverse=True,
            )

    def find_job_by_hash(self, content_hash: str) -> Optional[Job]:
        with self._lock:
            candidates = [
                j for j in self._jobs_cache.values()
                if j.content_hash == content_hash
            ]
            if not candidates:
                return None

            active = [
                j for j in candidates
                if j.status in ("queued", "running", "canceling")
            ]
            if active:
                return max(active, key=lambda x: x.created_at)

            return max(candidates, key=lambda x: x.created_at)

    def cleanup_source_snapshots(
        self,
        *,
        merges_dir: Path | None = None,
        apply: bool = True,
        keep: int = 3,
        max_age_hours: int = 24,
        max_bytes: int = 2 * 1024 * 1024 * 1024,
    ) -> dict:
        root = Path(merges_dir) if merges_dir is not None else get_merges_dir(self.hub_path)
        with self._lock:
            protected = {
                job.id
                for job in self._jobs_cache.values()
                if job.status in {"queued", "running", "canceling"}
            }
            with self._snapshot_cleanup_lock:
                return prune_source_snapshots(
                    root,
                    protected_job_ids=protected,
                    keep=keep,
                    max_age_hours=max_age_hours,
                    max_bytes=max_bytes,
                    apply=apply,
                )

    def cleanup_jobs(self, max_jobs: int = 100, max_age_hours: int = 24):
        now = datetime.now(timezone.utc)
        limit_time = now - timedelta(hours=max_age_hours)

        with self._lock:
            to_remove = set()
            all_jobs = sorted(
                self._jobs_cache.values(),
                key=lambda x: x.created_at,
                reverse=True,
            )

            for job in all_jobs:
                try:
                    s = job.created_at
                    if s.endswith("Z"):
                        s = s[:-1] + "+00:00"
                    dt = datetime.fromisoformat(s)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)

                    if dt < limit_time and job.status not in (
                        "queued", "running", "canceling"
                    ):
                        to_remove.add(job.id)
                except Exception as exc:
                    logger.warning("Skipping cleanup age check for job %s due to invalid created_at %r: %s", job.id, job.created_at, exc)

            remaining = [j for j in all_jobs if j.id not in to_remove]
            finished = [j for j in remaining if j.status not in ("queued", "running", "canceling")]
            active = [j for j in remaining if j.status in ("queued", "running", "canceling")]

            capacity = max(0, max_jobs - len(active))
            for j in finished[capacity:]:
                to_remove.add(j.id)

            for job_id in to_remove:
                self._remove_job_internal(job_id)

            if to_remove:
                self._save_jobs()
                self._save_artifacts()

    def add_artifact(self, artifact: Artifact):
        with self._lock:
            self._artifacts_cache[artifact.id] = artifact
            self._save_artifacts()

    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        with self._lock:
            return self._artifacts_cache.get(artifact_id)

    def get_all_artifacts(self) -> List[Artifact]:
        with self._lock:
            return sorted(
                self._artifacts_cache.values(),
                key=lambda x: x.created_at,
                reverse=True,
            )
