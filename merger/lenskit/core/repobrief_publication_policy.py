"""Identity-bound RepoBrief publication and retention policy.

The durable evidence store is intentionally separate from regenerable publication
payloads.  Publication reservation is serialized per repository/lane, while
retention is deterministic and preserves explicit pins, recent generations,
daily anchors, weekly anchors, and young incomplete attempts.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterator

POLICY_SCHEMA = "repobrief.publication-policy.v1"
RECORD_SCHEMA = "repobrief.publication-record.v1"
PIN_SCHEMA = "repobrief.publication-pin.v1"
PLAN_SCHEMA = "repobrief.publication-retention-plan.v1"
TRANSACTION_SCHEMA = "repobrief.publication-prune-transaction.v1"
TRANSACTION_STATES = frozenset(
    {
        "planned",
        "quarantined",
        "deleted",
        "restored",
        "aborted-safe-source",
        "skipped-retained",
    }
)
TERMINAL_TRANSACTION_STATES = frozenset(
    {"deleted", "restored", "aborted-safe-source", "skipped-retained"}
)
DEFAULT_RECENT = 3
DEFAULT_DAILY = 7
DEFAULT_WEEKLY = 8
DEFAULT_INCOMPLETE_TTL_SECONDS = 48 * 60 * 60
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_GENERATION_RE = re.compile(r"^\d{8}T\d{12}Z-[0-9a-f]{12}$")
_TRANSACTION_RE = re.compile(r"^[0-9a-f]{32}$")
UTC = dt.timezone.utc


class PublicationPolicyError(RuntimeError):
    """Fail-closed publication policy error."""


@dataclasses.dataclass(frozen=True)
class PublicationIdentity:
    repository: str
    lane: str
    repository_commit: str
    profile: str
    configuration_sha256: str
    lenskit_version: str
    bundle_schema: str
    generator_inputs_sha256: str

    def __post_init__(self) -> None:
        for label, value in (
            ("repository", self.repository),
            ("lane", self.lane),
            ("profile", self.profile),
        ):
            if not _KEY_RE.fullmatch(value):
                raise ValueError(f"{label} is not a safe publication key: {value!r}")
        if not _GIT_COMMIT_RE.fullmatch(self.repository_commit):
            raise ValueError("repository_commit must be a full hexadecimal Git id")
        for label, value in (
            ("configuration_sha256", self.configuration_sha256),
            ("generator_inputs_sha256", self.generator_inputs_sha256),
        ):
            if not _SHA256_RE.fullmatch(value):
                raise ValueError(f"{label} must be a lowercase SHA-256")
        if not self.lenskit_version.strip():
            raise ValueError("lenskit_version must not be empty")
        if not self.bundle_schema.strip():
            raise ValueError("bundle_schema must not be empty")

    def as_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.as_dict())


@dataclasses.dataclass(frozen=True)
class RetentionPolicy:
    recent: int = DEFAULT_RECENT
    daily: int = DEFAULT_DAILY
    weekly: int = DEFAULT_WEEKLY
    incomplete_ttl_seconds: int = DEFAULT_INCOMPLETE_TTL_SECONDS

    def __post_init__(self) -> None:
        for label, value in (
            ("recent", self.recent),
            ("daily", self.daily),
            ("weekly", self.weekly),
            ("incomplete_ttl_seconds", self.incomplete_ttl_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{label} must be a non-negative integer")
        if self.recent == 0:
            raise ValueError("recent must retain at least one successful generation")

    def as_dict(self) -> dict[str, int]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class TreeSnapshot:
    device: int
    inode: int
    tree_sha256: str
    bytes: int

    def as_dict(self) -> dict[str, int | str]:
        return dataclasses.asdict(self)


def canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> dt.datetime:
    return dt.datetime.now(UTC)


def format_time(value: dt.datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise ValueError("publication timestamps must be timezone-aware UTC values")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value: object) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PublicationPolicyError(f"invalid UTC timestamp: {value!r}")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PublicationPolicyError(f"invalid UTC timestamp: {value!r}") from exc
    if parsed.utcoffset() != dt.timedelta(0):
        raise PublicationPolicyError(f"timestamp is not UTC: {value!r}")
    return parsed.astimezone(UTC)


def _is_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if tmp.exists():
            tmp.unlink()


def _strict_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PublicationPolicyError(f"metadata is not a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationPolicyError(f"cannot parse metadata {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PublicationPolicyError(f"metadata is not a JSON object: {path}")
    return value


def tree_snapshot(path: Path) -> TreeSnapshot:
    if path.is_symlink() or not path.is_dir():
        raise PublicationPolicyError(f"payload is not a regular directory: {path}")
    root_stat = path.lstat()
    if not stat.S_ISDIR(root_stat.st_mode):
        raise PublicationPolicyError(f"payload is not a directory: {path}")
    rows: list[list[object]] = []
    total = 0
    for raw_root, directories, files in os.walk(path, followlinks=False):
        root = Path(raw_root)
        directories[:] = sorted(directories)
        metadata = root.lstat()
        rows.append(
            [
                "d",
                root.relative_to(path).as_posix(),
                stat.S_IMODE(metadata.st_mode),
            ]
        )
        for name in directories:
            child = root / name
            if child.is_symlink():
                raise PublicationPolicyError(f"payload contains a symlink: {child}")
        for name in sorted(files):
            child = root / name
            child_stat = child.lstat()
            if stat.S_ISLNK(child_stat.st_mode):
                raise PublicationPolicyError(f"payload contains a symlink: {child}")
            if not stat.S_ISREG(child_stat.st_mode):
                raise PublicationPolicyError(
                    f"payload contains a non-regular file: {child}"
                )
            total += child_stat.st_size
            rows.append(
                [
                    "f",
                    child.relative_to(path).as_posix(),
                    stat.S_IMODE(child_stat.st_mode),
                    child_stat.st_size,
                    sha256_file(child),
                ]
            )
    digest = canonical_sha256(rows)
    return TreeSnapshot(root_stat.st_dev, root_stat.st_ino, digest, total)


class PublicationPolicyStore:
    """Manage publication evidence and regenerable payloads with strict separation."""

    def __init__(self, *, evidence_root: Path, payload_root: Path) -> None:
        self.evidence_root = evidence_root.expanduser().resolve(strict=False)
        self.payload_root = payload_root.expanduser().resolve(strict=False)
        if self.evidence_root == self.payload_root or _is_under(
            self.evidence_root, self.payload_root
        ) or _is_under(self.payload_root, self.evidence_root):
            raise ValueError("evidence_root and payload_root must be disjoint")

    def _stream_dir(self, identity: PublicationIdentity) -> Path:
        return self.evidence_root / "records" / identity.repository / identity.lane

    def _records_dir(self, repository: str, lane: str) -> Path:
        self._validate_stream(repository, lane)
        return self.evidence_root / "records" / repository / lane

    def _pins_dir(self, repository: str, lane: str) -> Path:
        self._validate_stream(repository, lane)
        return self.evidence_root / "pins" / repository / lane

    def _lock_path(self, repository: str, lane: str) -> Path:
        self._validate_stream(repository, lane)
        return self.evidence_root / "locks" / repository / f"{lane}.lock"

    def _transactions_dir(self) -> Path:
        return self.evidence_root / "transactions"

    def _quarantine_root(self) -> Path:
        return self.payload_root / ".publication-policy-quarantine"

    @staticmethod
    def _validate_stream(repository: str, lane: str) -> None:
        for label, value in (("repository", repository), ("lane", lane)):
            if not _KEY_RE.fullmatch(value):
                raise ValueError(f"{label} is not a safe publication key: {value!r}")

    @contextlib.contextmanager
    def stream_lock(self, repository: str, lane: str) -> Iterator[None]:
        lock_path = self._lock_path(repository, lane)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _payload_path(self, raw_path: Path, *, must_exist: bool) -> Path:
        path = raw_path.expanduser().resolve(strict=False)
        if not _is_under(path, self.payload_root) or path == self.payload_root:
            raise PublicationPolicyError(
                f"payload path escapes the managed payload root: {raw_path}"
            )
        if self.payload_root.exists() and (
            self.payload_root.is_symlink() or not self.payload_root.is_dir()
        ):
            raise PublicationPolicyError(
                f"payload root is not a regular directory: {self.payload_root}"
            )
        if must_exist and (path.is_symlink() or not path.is_dir()):
            raise PublicationPolicyError(f"payload directory is unavailable: {path}")
        return path

    def _payload_relpath(self, path: Path) -> str:
        return path.relative_to(self.payload_root).as_posix()

    def _record_path(self, repository: str, lane: str, generation_id: str) -> Path:
        if not _GENERATION_RE.fullmatch(generation_id):
            raise PublicationPolicyError(f"invalid generation id: {generation_id}")
        return self._records_dir(repository, lane) / f"{generation_id}.json"

    def _record_reference(self, record_path: Path) -> tuple[str, str, str]:
        resolved = record_path.expanduser().resolve(strict=False)
        records_root = (self.evidence_root / "records").resolve(strict=False)
        if not _is_under(resolved, records_root):
            raise PublicationPolicyError(f"record path escapes evidence root: {record_path}")
        relative = resolved.relative_to(records_root)
        if len(relative.parts) != 3 or relative.suffix != ".json":
            raise PublicationPolicyError(f"invalid record path: {record_path}")
        repository, lane, filename = relative.parts
        generation_id = Path(filename).stem
        self._validate_stream(repository, lane)
        if not _GENERATION_RE.fullmatch(generation_id):
            raise PublicationPolicyError(f"invalid record filename: {record_path}")
        return repository, lane, generation_id

    def _load_record(self, path: Path) -> dict[str, Any]:
        repository, lane, generation_id = self._record_reference(path)
        record = _strict_json(path)
        if (
            record.get("schema") != RECORD_SCHEMA
            or record.get("repository") != repository
            or record.get("lane") != lane
            or record.get("generation_id") != generation_id
        ):
            raise PublicationPolicyError(f"record identity mismatch: {path}")
        identity = record.get("identity")
        if not isinstance(identity, dict):
            raise PublicationPolicyError(f"record lacks identity: {path}")
        try:
            parsed_identity = PublicationIdentity(**identity)
        except (TypeError, ValueError) as exc:
            raise PublicationPolicyError(f"invalid record identity: {path}") from exc
        if record.get("identity_sha256") != parsed_identity.sha256:
            raise PublicationPolicyError(f"record identity digest mismatch: {path}")
        if record.get("state") not in {"incomplete", "failed", "success"}:
            raise PublicationPolicyError(f"invalid record state: {path}")
        if record.get("payload_state") not in {"present", "pruned"}:
            raise PublicationPolicyError(f"invalid payload state: {path}")
        parse_time(record.get("created_at"))
        parse_time(record.get("updated_at"))
        return record

    def list_records(self, repository: str, lane: str) -> list[tuple[Path, dict[str, Any]]]:
        directory = self._records_dir(repository, lane)
        if not directory.exists():
            return []
        if directory.is_symlink() or not directory.is_dir():
            raise PublicationPolicyError(f"record root is not a directory: {directory}")
        records: list[tuple[Path, dict[str, Any]]] = []
        unexpected: list[Path] = []
        for path in directory.iterdir():
            if path.is_file() and not path.is_symlink() and path.suffix == ".json":
                records.append((path, self._load_record(path)))
            else:
                unexpected.append(path)
        if unexpected:
            rendered = ", ".join(str(path) for path in sorted(unexpected))
            raise PublicationPolicyError(f"unexpected record entries: {rendered}")
        return sorted(records, key=lambda row: row[1]["generation_id"])

    def _record_payload(self, record: dict[str, Any], *, must_exist: bool) -> Path:
        raw = record.get("payload_relpath")
        if not isinstance(raw, str) or not raw:
            raise PublicationPolicyError("record lacks payload_relpath")
        candidate = self.payload_root / raw
        return self._payload_path(candidate, must_exist=must_exist)

    def _pin_path(self, repository: str, lane: str, generation_id: str) -> Path:
        if not _GENERATION_RE.fullmatch(generation_id):
            raise PublicationPolicyError(f"invalid generation id: {generation_id}")
        return self._pins_dir(repository, lane) / f"{generation_id}.json"

    def pinned_generation_ids(self, repository: str, lane: str) -> set[str]:
        directory = self._pins_dir(repository, lane)
        if not directory.exists():
            return set()
        if directory.is_symlink() or not directory.is_dir():
            raise PublicationPolicyError(f"pin root is not a directory: {directory}")
        pinned: set[str] = set()
        unexpected: list[Path] = []
        for path in directory.iterdir():
            if not (path.is_file() and not path.is_symlink() and path.suffix == ".json"):
                unexpected.append(path)
                continue
            payload = _strict_json(path)
            generation_id = path.stem
            if (
                payload.get("schema") != PIN_SCHEMA
                or payload.get("repository") != repository
                or payload.get("lane") != lane
                or payload.get("generation_id") != generation_id
                or not _GENERATION_RE.fullmatch(generation_id)
                or not isinstance(payload.get("reason"), str)
                or not payload["reason"].strip()
            ):
                raise PublicationPolicyError(f"invalid pin metadata: {path}")
            parse_time(payload.get("pinned_at"))
            pinned.add(generation_id)
        if unexpected:
            rendered = ", ".join(str(path) for path in sorted(unexpected))
            raise PublicationPolicyError(f"unexpected pin entries: {rendered}")
        return pinned

    def begin(
        self,
        identity: PublicationIdentity,
        *,
        payload_path: Path,
        now: dt.datetime | None = None,
        incomplete_ttl_seconds: int = DEFAULT_INCOMPLETE_TTL_SECONDS,
    ) -> dict[str, object]:
        if incomplete_ttl_seconds < 0:
            raise ValueError("incomplete_ttl_seconds must be non-negative")
        observed_at = now or utc_now()
        payload = self._payload_path(payload_path, must_exist=False)
        with self.stream_lock(identity.repository, identity.lane):
            records = self.list_records(identity.repository, identity.lane)
            for path, record in reversed(records):
                if record["identity_sha256"] != identity.sha256:
                    continue
                state = record["state"]
                payload_state = record["payload_state"]
                existing_payload = self._record_payload(record, must_exist=False)
                if state == "success" and payload_state == "present":
                    if existing_payload.is_symlink() or not existing_payload.is_dir():
                        raise PublicationPolicyError(
                            f"successful publication payload is missing: {existing_payload}"
                        )
                    return {
                        "status": "noop",
                        "identity_sha256": identity.sha256,
                        "record_path": str(path),
                        "payload_path": str(existing_payload),
                    }
                if state == "incomplete":
                    age = (observed_at - parse_time(record["created_at"])).total_seconds()
                    if age < incomplete_ttl_seconds:
                        return {
                            "status": "in_progress",
                            "identity_sha256": identity.sha256,
                            "record_path": str(path),
                            "payload_path": str(existing_payload),
                        }
            if payload.exists() or payload.is_symlink():
                raise PublicationPolicyError(
                    f"new publication payload path already exists: {payload}"
                )
            generation_id = (
                observed_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                + f"-{identity.sha256[:12]}"
            )
            record_path = self._record_path(
                identity.repository, identity.lane, generation_id
            )
            record = {
                "schema": RECORD_SCHEMA,
                "policy_schema": POLICY_SCHEMA,
                "generation_id": generation_id,
                "repository": identity.repository,
                "lane": identity.lane,
                "identity": identity.as_dict(),
                "identity_sha256": identity.sha256,
                "state": "incomplete",
                "payload_state": "present",
                "payload_relpath": self._payload_relpath(payload),
                "created_at": format_time(observed_at),
                "updated_at": format_time(observed_at),
                "completed_at": None,
                "failed_at": None,
                "failure_reason": None,
                "manifest_relpath": None,
                "manifest_sha256": None,
                "payload_tree_sha256": None,
                "payload_bytes": None,
                "pruned_at": None,
                "prune_reason": None,
            }
            if record_path.exists() or record_path.is_symlink():
                raise PublicationPolicyError(
                    f"publication generation already exists: {record_path}"
                )
            _atomic_write_json(record_path, record)
            return {
                "status": "created",
                "identity_sha256": identity.sha256,
                "generation_id": generation_id,
                "record_path": str(record_path),
                "payload_path": str(payload),
            }

    def complete(
        self,
        record_path: Path,
        *,
        manifest_path: Path,
        now: dt.datetime | None = None,
    ) -> dict[str, object]:
        repository, lane, _ = self._record_reference(record_path)
        observed_at = now or utc_now()
        with self.stream_lock(repository, lane):
            record = self._load_record(record_path)
            if record["state"] == "success":
                return {"status": "already_complete", "record_path": str(record_path)}
            if record["state"] != "incomplete":
                raise PublicationPolicyError("only incomplete publications can complete")
            payload = self._record_payload(record, must_exist=True)
            manifest = manifest_path.expanduser().resolve(strict=True)
            if manifest.is_symlink() or not manifest.is_file() or not _is_under(
                manifest, payload
            ):
                raise PublicationPolicyError(
                    "manifest must be a regular file inside the publication payload"
                )
            snapshot = tree_snapshot(payload)
            record.update(
                {
                    "state": "success",
                    "updated_at": format_time(observed_at),
                    "completed_at": format_time(observed_at),
                    "manifest_relpath": manifest.relative_to(payload).as_posix(),
                    "manifest_sha256": sha256_file(manifest),
                    "payload_tree_sha256": snapshot.tree_sha256,
                    "payload_bytes": snapshot.bytes,
                }
            )
            _atomic_write_json(record_path, record)
            return {
                "status": "completed",
                "record_path": str(record_path),
                "identity_sha256": record["identity_sha256"],
                "payload_tree_sha256": snapshot.tree_sha256,
                "payload_bytes": snapshot.bytes,
                "manifest_sha256": record["manifest_sha256"],
            }

    def fail(
        self,
        record_path: Path,
        *,
        reason: str,
        now: dt.datetime | None = None,
    ) -> dict[str, object]:
        if not reason.strip():
            raise ValueError("failure reason must not be empty")
        repository, lane, _ = self._record_reference(record_path)
        observed_at = now or utc_now()
        with self.stream_lock(repository, lane):
            record = self._load_record(record_path)
            if record["state"] == "success":
                raise PublicationPolicyError("successful publications cannot be failed")
            if record["state"] == "failed":
                return {
                    "status": "already_failed",
                    "record_path": str(record_path),
                }
            if record["state"] != "incomplete":
                raise PublicationPolicyError("only incomplete publications can fail")
            record.update(
                {
                    "state": "failed",
                    "updated_at": format_time(observed_at),
                    "failed_at": format_time(observed_at),
                    "failure_reason": reason.strip(),
                }
            )
            _atomic_write_json(record_path, record)
            return {"status": "failed", "record_path": str(record_path)}

    def _assert_payload_available_for_pin(
        self,
        *,
        repository: str,
        lane: str,
        generation_id: str,
        record: dict[str, Any],
    ) -> None:
        payload = self._record_payload(record, must_exist=False)
        if not payload.is_symlink() and payload.is_dir():
            return
        for transaction_path in self._open_transactions(repository, lane):
            transaction = _strict_json(transaction_path)
            if self._transaction_generation_id(
                transaction_path, transaction
            ) != generation_id:
                continue
            (
                _,
                _,
                _,
                _,
                _,
                quarantine,
                expected_snapshot,
            ) = self._reconcile_context(transaction_path, repository, lane)
            if (
                not quarantine.is_symlink()
                and quarantine.is_dir()
                and tree_snapshot(quarantine) == expected_snapshot
            ):
                return
        raise PublicationPolicyError(
            "only publications with a present or recoverable payload can be pinned"
        )

    def pin(
        self,
        record_path: Path,
        *,
        reason: str,
        now: dt.datetime | None = None,
    ) -> dict[str, object]:
        if not reason.strip():
            raise ValueError("pin reason must not be empty")
        repository, lane, generation_id = self._record_reference(record_path)
        observed_at = now or utc_now()
        with self.stream_lock(repository, lane):
            record = self._load_record(record_path)
            if record["payload_state"] != "present":
                raise PublicationPolicyError(
                    "only publications with a present payload can be pinned"
                )
            self._assert_payload_available_for_pin(
                repository=repository,
                lane=lane,
                generation_id=generation_id,
                record=record,
            )
            pin_path = self._pin_path(repository, lane, generation_id)
            payload = {
                "schema": PIN_SCHEMA,
                "repository": repository,
                "lane": lane,
                "generation_id": generation_id,
                "reason": reason.strip(),
                "pinned_at": format_time(observed_at),
            }
            _atomic_write_json(pin_path, payload)
            return {"status": "pinned", "pin_path": str(pin_path)}

    def unpin(self, record_path: Path) -> dict[str, object]:
        repository, lane, generation_id = self._record_reference(record_path)
        with self.stream_lock(repository, lane):
            self._load_record(record_path)
            pin_path = self._pin_path(repository, lane, generation_id)
            pin_path.unlink(missing_ok=True)
            return {"status": "unpinned", "pin_path": str(pin_path)}

    @staticmethod
    def _add_retention_reason(
        retained: set[str],
        reasons: dict[str, set[str]],
        generation_id: str,
        reason: str,
    ) -> None:
        retained.add(generation_id)
        reasons.setdefault(generation_id, set()).add(reason)

    @staticmethod
    def _assert_pins_reference_records(
        records: list[tuple[Path, dict[str, Any]]], pinned: set[str]
    ) -> None:
        record_generation_ids = {record["generation_id"] for _, record in records}
        orphan_pins = pinned - record_generation_ids
        if orphan_pins:
            raise PublicationPolicyError(
                "pins reference missing publication records: "
                + ", ".join(sorted(orphan_pins))
            )

    def _classify_retention_records(
        self,
        records: list[tuple[Path, dict[str, Any]]],
        *,
        pinned: set[str],
        policy: RetentionPolicy,
        now: dt.datetime,
    ) -> tuple[
        list[tuple[Path, dict[str, Any], dt.datetime]],
        set[str],
        dict[str, set[str]],
    ]:
        successful: list[tuple[Path, dict[str, Any], dt.datetime]] = []
        retained = set(pinned)
        reasons = {generation_id: {"pin"} for generation_id in pinned}
        for path, record in records:
            generation_id = record["generation_id"]
            payload_present = record["payload_state"] == "present"
            if record["state"] == "success" and payload_present:
                successful.append((path, record, parse_time(record.get("completed_at"))))
                continue
            if not payload_present:
                continue
            age_source = (
                record.get("failed_at")
                if record["state"] == "failed" and record.get("failed_at")
                else record["created_at"]
            )
            age = (now - parse_time(age_source)).total_seconds()
            if age < policy.incomplete_ttl_seconds:
                self._add_retention_reason(
                    retained, reasons, generation_id, "incomplete-ttl"
                )
        successful.sort(
            key=lambda row: (row[2], row[1]["generation_id"]), reverse=True
        )
        return successful, retained, reasons

    def _retain_recent_generations(
        self,
        successful: list[tuple[Path, dict[str, Any], dt.datetime]],
        *,
        limit: int,
        retained: set[str],
        reasons: dict[str, set[str]],
    ) -> None:
        for _, record, _ in successful[:limit]:
            self._add_retention_reason(
                retained, reasons, record["generation_id"], "recent"
            )

    def _retain_period_anchors(
        self,
        successful: list[tuple[Path, dict[str, Any], dt.datetime]],
        *,
        limit: int,
        period_key: str,
        retained: set[str],
        reasons: dict[str, set[str]],
    ) -> None:
        if not limit:
            return
        seen: set[object] = set()
        for _, record, completed_at in successful:
            if period_key == "daily":
                period: object = completed_at.date()
            else:
                calendar = completed_at.isocalendar()
                period = (calendar.year, calendar.week)
            if period in seen:
                continue
            seen.add(period)
            self._add_retention_reason(
                retained, reasons, record["generation_id"], period_key
            )
            if len(seen) >= limit:
                return

    def _retention_candidates(
        self,
        records: list[tuple[Path, dict[str, Any]]],
        *,
        retained: set[str],
        allowed_missing: set[str],
    ) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        missing_retained: list[str] = []
        for path, record in records:
            generation_id = record["generation_id"]
            if record["payload_state"] == "pruned":
                continue
            payload = self._record_payload(record, must_exist=False)
            payload_missing = payload.is_symlink() or not payload.is_dir()
            if generation_id in retained:
                if payload_missing and generation_id not in allowed_missing:
                    missing_retained.append(generation_id)
                continue
            if payload_missing and generation_id not in allowed_missing:
                raise PublicationPolicyError(
                    f"unretained payload is missing or invalid: {payload}"
                )
            reason = (
                "history-policy"
                if record["state"] == "success"
                else "incomplete-ttl-expired"
            )
            candidates.append(
                {
                    "generation_id": generation_id,
                    "record_path": str(path),
                    "payload_path": str(payload),
                    "reason": reason,
                }
            )
        if missing_retained:
            raise PublicationPolicyError(
                "retained publication payloads are missing: "
                + ", ".join(sorted(missing_retained))
            )
        return sorted(candidates, key=lambda row: str(row["generation_id"]))

    def _selection(
        self,
        repository: str,
        lane: str,
        *,
        policy: RetentionPolicy,
        now: dt.datetime,
        missing_allowed: set[str] | None = None,
    ) -> dict[str, object]:
        records = self.list_records(repository, lane)
        pinned = self.pinned_generation_ids(repository, lane)
        self._assert_pins_reference_records(records, pinned)
        successful, retained, reasons = self._classify_retention_records(
            records, pinned=pinned, policy=policy, now=now
        )
        self._retain_recent_generations(
            successful, limit=policy.recent, retained=retained, reasons=reasons
        )
        self._retain_period_anchors(
            successful,
            limit=policy.daily,
            period_key="daily",
            retained=retained,
            reasons=reasons,
        )
        self._retain_period_anchors(
            successful,
            limit=policy.weekly,
            period_key="weekly",
            retained=retained,
            reasons=reasons,
        )
        candidates = self._retention_candidates(
            records,
            retained=retained,
            allowed_missing=missing_allowed or set(),
        )
        return {
            "retained": sorted(retained),
            "retention_reasons": {
                key: sorted(value) for key, value in sorted(reasons.items())
            },
            "candidates": candidates,
            "record_count": len(records),
        }

    def plan_retention(
        self,
        repository: str,
        lane: str,
        *,
        policy: RetentionPolicy | None = None,
        now: dt.datetime | None = None,
    ) -> dict[str, object]:
        selected_policy = policy or RetentionPolicy()
        observed_at = now or utc_now()
        with self.stream_lock(repository, lane):
            open_transactions = self._open_transactions(repository, lane)
            if open_transactions:
                raise PublicationPolicyError(
                    "retention transactions require reconciliation before planning"
                )
            selection = self._selection(
                repository, lane, policy=selected_policy, now=observed_at
            )
            entries: list[dict[str, object]] = []
            for candidate in selection["candidates"]:
                record_path = Path(str(candidate["record_path"]))
                payload_path = Path(str(candidate["payload_path"]))
                snapshot = tree_snapshot(payload_path)
                entries.append(
                    {
                        "generation_id": candidate["generation_id"],
                        "record_relpath": record_path.relative_to(
                            self.evidence_root
                        ).as_posix(),
                        "record_sha256": sha256_file(record_path),
                        "payload_relpath": payload_path.relative_to(
                            self.payload_root
                        ).as_posix(),
                        "payload_snapshot": snapshot.as_dict(),
                        "reason": candidate["reason"],
                    }
                )
            plan: dict[str, object] = {
                "schema": PLAN_SCHEMA,
                "policy_schema": POLICY_SCHEMA,
                "plan_id": uuid.uuid4().hex,
                "repository": repository,
                "lane": lane,
                "generated_at": format_time(observed_at),
                "policy": selected_policy.as_dict(),
                "retained": selection["retained"],
                "retention_reasons": selection["retention_reasons"],
                "entries": entries,
            }
            plan["plan_sha256"] = canonical_sha256(plan)
            return plan

    def write_plan(self, path: Path, plan: dict[str, object]) -> None:
        self._validate_plan(plan)
        _atomic_write_json(path.expanduser().resolve(strict=False), plan)

    @staticmethod
    def _assert_unique_plan_entries(entries: list[object]) -> None:
        generation_ids: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise PublicationPolicyError("retention plan entry must be an object")
            generation_id = entry.get("generation_id")
            if not isinstance(generation_id, str) or not _GENERATION_RE.fullmatch(
                generation_id
            ):
                raise PublicationPolicyError("malformed retention plan entry")
            if generation_id in generation_ids:
                raise PublicationPolicyError(
                    f"duplicate retention plan generation: {generation_id}"
                )
            generation_ids.add(generation_id)

    def _validate_plan(self, plan: dict[str, object]) -> RetentionPolicy:
        if plan.get("schema") != PLAN_SCHEMA or plan.get("policy_schema") != POLICY_SCHEMA:
            raise PublicationPolicyError("unsupported retention plan schema")
        plan_sha = plan.get("plan_sha256")
        if not isinstance(plan_sha, str) or not _SHA256_RE.fullmatch(plan_sha):
            raise PublicationPolicyError("retention plan lacks a valid hash")
        unhashed = dict(plan)
        unhashed.pop("plan_sha256", None)
        if canonical_sha256(unhashed) != plan_sha:
            raise PublicationPolicyError("retention plan hash mismatch")
        plan_id = plan.get("plan_id")
        if not isinstance(plan_id, str) or not _TRANSACTION_RE.fullmatch(plan_id):
            raise PublicationPolicyError("invalid retention plan id")
        repository = plan.get("repository")
        lane = plan.get("lane")
        if not isinstance(repository, str) or not isinstance(lane, str):
            raise PublicationPolicyError("retention plan lacks stream identity")
        self._validate_stream(repository, lane)
        raw_policy = plan.get("policy")
        if not isinstance(raw_policy, dict):
            raise PublicationPolicyError("retention plan lacks policy")
        try:
            policy = RetentionPolicy(**raw_policy)
        except (TypeError, ValueError) as exc:
            raise PublicationPolicyError("invalid retention policy") from exc
        entries = plan.get("entries")
        if not isinstance(entries, list):
            raise PublicationPolicyError("retention plan entries must be a list")
        self._assert_unique_plan_entries(entries)
        parse_time(plan.get("generated_at"))
        return policy

    def _transaction_path(self, transaction_id: str) -> Path:
        if not _TRANSACTION_RE.fullmatch(transaction_id):
            raise PublicationPolicyError("invalid transaction id")
        return self._transactions_dir() / f"{transaction_id}.json"

    def _write_transaction(self, payload: dict[str, object]) -> Path:
        transaction_id = payload.get("transaction_id")
        if not isinstance(transaction_id, str):
            raise PublicationPolicyError("transaction lacks id")
        path = self._transaction_path(transaction_id)
        _atomic_write_json(path, payload)
        return path

    def _set_transaction_state(
        self, payload: dict[str, object], state_value: str, now: dt.datetime
    ) -> None:
        payload["state"] = state_value
        payload["updated_at"] = format_time(now)
        self._write_transaction(payload)

    def _mark_pruned(
        self,
        record_path: Path,
        *,
        reason: str,
        transaction_id: str,
        now: dt.datetime,
    ) -> None:
        record = self._load_record(record_path)
        record.update(
            {
                "payload_state": "pruned",
                "updated_at": format_time(now),
                "pruned_at": format_time(now),
                "prune_reason": reason,
                "prune_transaction_id": transaction_id,
            }
        )
        _atomic_write_json(record_path, record)

    def _open_transactions(self, repository: str, lane: str) -> list[Path]:
        directory = self._transactions_dir()
        if not directory.exists():
            return []
        open_paths: list[Path] = []
        for path in sorted(directory.iterdir()):
            if not (
                path.is_file()
                and not path.is_symlink()
                and path.suffix == ".json"
                and _TRANSACTION_RE.fullmatch(path.stem)
            ):
                raise PublicationPolicyError(f"unexpected transaction entry: {path}")
            payload = _strict_json(path)
            if payload.get("schema") != TRANSACTION_SCHEMA:
                raise PublicationPolicyError(f"unsupported transaction schema: {path}")
            state_value = payload.get("state")
            if state_value not in TRANSACTION_STATES:
                raise PublicationPolicyError(f"invalid transaction state: {path}")
            if (
                payload.get("repository") == repository
                and payload.get("lane") == lane
                and state_value not in TERMINAL_TRANSACTION_STATES
            ):
                open_paths.append(path)
        return open_paths

    def _validate_plan_entry(
        self, entry: object, repository: str, lane: str
    ) -> tuple[str, Path, Path, TreeSnapshot, str]:
        if not isinstance(entry, dict):
            raise PublicationPolicyError("retention plan entry must be an object")
        generation_id = entry.get("generation_id")
        record_relpath = entry.get("record_relpath")
        payload_relpath = entry.get("payload_relpath")
        snapshot_raw = entry.get("payload_snapshot")
        reason = entry.get("reason")
        if (
            not isinstance(generation_id, str)
            or not _GENERATION_RE.fullmatch(generation_id)
            or not isinstance(record_relpath, str)
            or not isinstance(payload_relpath, str)
            or not isinstance(snapshot_raw, dict)
            or not isinstance(reason, str)
        ):
            raise PublicationPolicyError("malformed retention plan entry")
        record_path = (self.evidence_root / record_relpath).resolve(strict=False)
        expected_record = self._record_path(repository, lane, generation_id).resolve(
            strict=False
        )
        if record_path != expected_record:
            raise PublicationPolicyError("retention plan record path mismatch")
        payload_path = self._payload_path(
            self.payload_root / payload_relpath, must_exist=True
        )
        try:
            snapshot = TreeSnapshot(
                device=int(snapshot_raw["device"]),
                inode=int(snapshot_raw["inode"]),
                tree_sha256=str(snapshot_raw["tree_sha256"]),
                bytes=int(snapshot_raw["bytes"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PublicationPolicyError("invalid payload snapshot") from exc
        if not _SHA256_RE.fullmatch(snapshot.tree_sha256) or snapshot.bytes < 0:
            raise PublicationPolicyError("invalid payload snapshot values")
        return generation_id, record_path, payload_path, snapshot, reason

    def apply_plan(
        self,
        plan: dict[str, object],
        *,
        now: dt.datetime | None = None,
    ) -> dict[str, object]:
        policy = self._validate_plan(plan)
        repository = str(plan["repository"])
        lane = str(plan["lane"])
        observed_at = now or utc_now()
        results: list[dict[str, object]] = []
        with self.stream_lock(repository, lane):
            if self._open_transactions(repository, lane):
                raise PublicationPolicyError(
                    "retention transactions require reconciliation before apply"
                )
            current = self._selection(
                repository, lane, policy=policy, now=observed_at
            )
            current_candidates = {
                str(row["generation_id"]) for row in current["candidates"]
            }
            for raw_entry in plan["entries"]:
                (
                    generation_id,
                    record_path,
                    payload_path,
                    expected_snapshot,
                    reason,
                ) = self._validate_plan_entry(raw_entry, repository, lane)
                if generation_id not in current_candidates:
                    results.append(
                        {"generation_id": generation_id, "status": "retained-now"}
                    )
                    continue
                entry = raw_entry
                assert isinstance(entry, dict)
                if sha256_file(record_path) != entry.get("record_sha256"):
                    raise PublicationPolicyError(
                        f"record changed after retention planning: {record_path}"
                    )
                if tree_snapshot(payload_path) != expected_snapshot:
                    raise PublicationPolicyError(
                        f"payload changed after retention planning: {payload_path}"
                    )
                transaction_id = uuid.uuid4().hex
                quarantine = (
                    self._quarantine_root() / transaction_id / generation_id
                ).resolve(strict=False)
                transaction: dict[str, object] = {
                    "schema": TRANSACTION_SCHEMA,
                    "transaction_id": transaction_id,
                    "plan_id": plan["plan_id"],
                    "repository": repository,
                    "lane": lane,
                    "generation_id": generation_id,
                    "record_relpath": record_path.relative_to(
                        self.evidence_root
                    ).as_posix(),
                    "source_relpath": payload_path.relative_to(
                        self.payload_root
                    ).as_posix(),
                    "quarantine_relpath": quarantine.relative_to(
                        self.payload_root
                    ).as_posix(),
                    "snapshot": expected_snapshot.as_dict(),
                    "reason": reason,
                    "state": "planned",
                    "updated_at": format_time(observed_at),
                }
                self._write_transaction(transaction)
                quarantine.parent.mkdir(parents=True, exist_ok=False)
                if tree_snapshot(payload_path) != expected_snapshot:
                    self._set_transaction_state(
                        transaction, "aborted-safe-source", observed_at
                    )
                    quarantine.parent.rmdir()
                    raise PublicationPolicyError(
                        f"payload changed before quarantine: {payload_path}"
                    )
                os.replace(payload_path, quarantine)
                if tree_snapshot(quarantine) != expected_snapshot:
                    os.replace(quarantine, payload_path)
                    self._set_transaction_state(
                        transaction, "restored", observed_at
                    )
                    raise PublicationPolicyError(
                        f"quarantined payload identity mismatch: {payload_path}"
                    )
                self._set_transaction_state(transaction, "quarantined", observed_at)
                if tree_snapshot(quarantine) != expected_snapshot:
                    os.replace(quarantine, payload_path)
                    self._set_transaction_state(
                        transaction, "restored", observed_at
                    )
                    raise PublicationPolicyError(
                        f"quarantined payload changed before deletion: {payload_path}"
                    )
                shutil.rmtree(quarantine)
                self._mark_pruned(
                    record_path,
                    reason=reason,
                    transaction_id=transaction_id,
                    now=observed_at,
                )
                self._set_transaction_state(transaction, "deleted", observed_at)
                with contextlib.suppress(OSError):
                    quarantine.parent.rmdir()
                with contextlib.suppress(OSError):
                    self._quarantine_root().rmdir()
                results.append(
                    {
                        "generation_id": generation_id,
                        "status": "deleted",
                        "transaction_id": transaction_id,
                        "payload_bytes": expected_snapshot.bytes,
                    }
                )
        return {
            "status": "applied",
            "plan_id": plan["plan_id"],
            "plan_sha256": plan["plan_sha256"],
            "results": results,
        }

    @staticmethod
    def _transaction_generation_id(
        transaction_path: Path, transaction: dict[str, Any]
    ) -> str:
        generation_id = transaction.get("generation_id")
        if not isinstance(generation_id, str) or not _GENERATION_RE.fullmatch(
            generation_id
        ):
            raise PublicationPolicyError(
                f"malformed transaction generation: {transaction_path}"
            )
        return generation_id

    def _transaction_generation_ids(self, paths: list[Path]) -> set[str]:
        return {
            self._transaction_generation_id(path, _strict_json(path)) for path in paths
        }

    @staticmethod
    def _snapshot_from_transaction(
        transaction_path: Path, snapshot_raw: object
    ) -> TreeSnapshot:
        if not isinstance(snapshot_raw, dict):
            raise PublicationPolicyError(
                f"malformed transaction snapshot: {transaction_path}"
            )
        try:
            snapshot = TreeSnapshot(
                device=int(snapshot_raw["device"]),
                inode=int(snapshot_raw["inode"]),
                tree_sha256=str(snapshot_raw["tree_sha256"]),
                bytes=int(snapshot_raw["bytes"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PublicationPolicyError(
                f"malformed transaction snapshot: {transaction_path}"
            ) from exc
        if not _SHA256_RE.fullmatch(snapshot.tree_sha256) or snapshot.bytes < 0:
            raise PublicationPolicyError(
                f"malformed transaction snapshot: {transaction_path}"
            )
        return snapshot

    def _reconcile_context(
        self, transaction_path: Path, repository: str, lane: str
    ) -> tuple[
        dict[str, Any], str, str, Path, Path, Path, TreeSnapshot
    ]:
        transaction = _strict_json(transaction_path)
        transaction_id = transaction_path.stem
        generation_id = self._transaction_generation_id(
            transaction_path, transaction
        )
        record_relpath = transaction.get("record_relpath")
        source_relpath = transaction.get("source_relpath")
        quarantine_relpath = transaction.get("quarantine_relpath")
        raw_paths = (record_relpath, source_relpath, quarantine_relpath)
        if not all(isinstance(value, str) for value in raw_paths):
            raise PublicationPolicyError(
                f"malformed transaction paths: {transaction_path}"
            )
        record_path = (self.evidence_root / str(record_relpath)).resolve(strict=False)
        expected_record = self._record_path(repository, lane, generation_id).resolve(
            strict=False
        )
        if record_path != expected_record:
            raise PublicationPolicyError(
                f"transaction record path mismatch: {transaction_path}"
            )
        source = self._payload_path(
            self.payload_root / str(source_relpath), must_exist=False
        )
        quarantine = self._payload_path(
            self.payload_root / str(quarantine_relpath), must_exist=False
        )
        expected_quarantine = (
            self._quarantine_root() / transaction_id / generation_id
        ).resolve(strict=False)
        if quarantine != expected_quarantine:
            raise PublicationPolicyError(
                f"transaction quarantine path mismatch: {transaction_path}"
            )
        snapshot = self._snapshot_from_transaction(
            transaction_path, transaction.get("snapshot")
        )
        return (
            transaction,
            transaction_id,
            generation_id,
            record_path,
            source,
            quarantine,
            snapshot,
        )

    def _cleanup_reconcile_quarantine(self, quarantine: Path) -> None:
        with contextlib.suppress(OSError):
            quarantine.parent.rmdir()
        with contextlib.suppress(OSError):
            self._quarantine_root().rmdir()

    def _reconcile_source_copy(
        self,
        *,
        transaction_path: Path,
        transaction: dict[str, Any],
        transaction_id: str,
        source: Path,
        quarantine: Path,
        expected_snapshot: TreeSnapshot,
        observed_at: dt.datetime,
    ) -> dict[str, object]:
        if tree_snapshot(source) != expected_snapshot:
            raise PublicationPolicyError(
                f"transaction source identity mismatch: {transaction_path}"
            )
        self._set_transaction_state(transaction, "aborted-safe-source", observed_at)
        self._cleanup_reconcile_quarantine(quarantine)
        return {"transaction_id": transaction_id, "status": "source-retained"}

    def _reconcile_quarantine_copy(
        self,
        *,
        transaction_path: Path,
        transaction: dict[str, Any],
        transaction_id: str,
        generation_id: str,
        record_path: Path,
        source: Path,
        quarantine: Path,
        expected_snapshot: TreeSnapshot,
        retained: set[str],
        observed_at: dt.datetime,
    ) -> dict[str, object]:
        if tree_snapshot(quarantine) != expected_snapshot:
            raise PublicationPolicyError(
                f"transaction quarantine identity mismatch: {transaction_path}"
            )
        if generation_id in retained:
            source.parent.mkdir(parents=True, exist_ok=True)
            os.replace(quarantine, source)
            self._set_transaction_state(transaction, "restored", observed_at)
            status = "restored"
        else:
            shutil.rmtree(quarantine)
            self._mark_pruned(
                record_path,
                reason=str(transaction.get("reason") or "reconciled"),
                transaction_id=transaction_id,
                now=observed_at,
            )
            self._set_transaction_state(transaction, "deleted", observed_at)
            status = "deleted"
        self._cleanup_reconcile_quarantine(quarantine)
        return {"transaction_id": transaction_id, "status": status}

    def _record_completed_transaction_delete(
        self,
        *,
        transaction: dict[str, Any],
        transaction_id: str,
        record_path: Path,
        observed_at: dt.datetime,
    ) -> dict[str, object]:
        self._mark_pruned(
            record_path,
            reason=str(transaction.get("reason") or "reconciled"),
            transaction_id=transaction_id,
            now=observed_at,
        )
        self._set_transaction_state(transaction, "deleted", observed_at)
        return {"transaction_id": transaction_id, "status": "recorded-deleted"}

    def _reconcile_one_transaction(
        self,
        transaction_path: Path,
        *,
        repository: str,
        lane: str,
        retained: set[str],
        observed_at: dt.datetime,
    ) -> dict[str, object]:
        (
            transaction,
            transaction_id,
            generation_id,
            record_path,
            source,
            quarantine,
            expected_snapshot,
        ) = self._reconcile_context(transaction_path, repository, lane)
        source_exists = source.exists() or source.is_symlink()
        quarantine_exists = quarantine.exists() or quarantine.is_symlink()
        if source_exists and quarantine_exists:
            raise PublicationPolicyError(
                f"transaction has two payload copies: {transaction_path}"
            )
        if source_exists:
            return self._reconcile_source_copy(
                transaction_path=transaction_path,
                transaction=transaction,
                transaction_id=transaction_id,
                source=source,
                quarantine=quarantine,
                expected_snapshot=expected_snapshot,
                observed_at=observed_at,
            )
        if quarantine_exists:
            return self._reconcile_quarantine_copy(
                transaction_path=transaction_path,
                transaction=transaction,
                transaction_id=transaction_id,
                generation_id=generation_id,
                record_path=record_path,
                source=source,
                quarantine=quarantine,
                expected_snapshot=expected_snapshot,
                retained=retained,
                observed_at=observed_at,
            )
        if transaction.get("state") == "quarantined":
            return self._record_completed_transaction_delete(
                transaction=transaction,
                transaction_id=transaction_id,
                record_path=record_path,
                observed_at=observed_at,
            )
        raise PublicationPolicyError(
            f"planned transaction lost both payload copies: {transaction_path}"
        )

    def reconcile_transactions(
        self,
        repository: str,
        lane: str,
        *,
        policy: RetentionPolicy | None = None,
        now: dt.datetime | None = None,
    ) -> dict[str, object]:
        selected_policy = policy or RetentionPolicy()
        observed_at = now or utc_now()
        with self.stream_lock(repository, lane):
            transaction_paths = self._open_transactions(repository, lane)
            generation_ids = self._transaction_generation_ids(transaction_paths)
            selection = self._selection(
                repository,
                lane,
                policy=selected_policy,
                now=observed_at,
                missing_allowed=generation_ids,
            )
            retained = set(selection["retained"])
            results = [
                self._reconcile_one_transaction(
                    transaction_path,
                    repository=repository,
                    lane=lane,
                    retained=retained,
                    observed_at=observed_at,
                )
                for transaction_path in transaction_paths
            ]
        return {"status": "reconciled", "results": results}
