"""Stable, request-scoped bindings for one RepoGround bundle manifest."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from merger.repoground.core.bundle_identity import is_bundle_manifest

MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class ManifestBindingError(ValueError):
    """Raised when a manifest cannot satisfy its selected byte identity."""


@dataclass(frozen=True, slots=True)
class ManifestBinding:
    # This deliberately retains a final symlink instead of collapsing it into
    # the separately stored file target.
    selected_path: Path
    resolved_path: Path
    sha256: str
    run_id: str

    @property
    def path(self) -> Path:
        """Compatibility alias for the selected absolute path identity."""
        return self.selected_path


@dataclass(frozen=True, slots=True)
class ManifestSnapshot:
    binding: ManifestBinding
    raw: bytes
    file_identity: tuple[int, int, int, int, int, int]

    @property
    def path(self) -> Path:
        return self.binding.selected_path

    @property
    def selected_path(self) -> Path:
        return self.binding.selected_path

    @property
    def resolved_path(self) -> Path:
        return self.binding.resolved_path

    def json_object(self) -> dict[str, Any]:
        value = json.loads(self.raw.decode("utf-8"))
        if not isinstance(value, dict):  # pragma: no cover - capture validates this
            raise ManifestBindingError("bundle manifest must be a JSON object")
        return value


_ACTIVE_MANIFEST_SNAPSHOT: ContextVar[ManifestSnapshot | None] = ContextVar(
    "repoground_active_manifest_snapshot",
    default=None,
)


def _file_identity(value: Any) -> tuple[int, int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _decode_manifest(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestBindingError("bundle manifest is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ManifestBindingError("bundle manifest must be a JSON object")
    if (
        not is_bundle_manifest(value)
        or not isinstance(value.get("run_id"), str)
        or not value["run_id"]
        or not isinstance(value.get("artifacts"), list)
    ):
        raise ManifestBindingError(
            "bundle manifest does not have RepoGround manifest shape"
        )
    return value


def manifest_path_identity(path: str | Path) -> Path:
    """Return an absolute lexical path identity without following symlinks."""
    return Path(os.path.abspath(Path(path).expanduser()))


def _validate_expected_binding(
    expected: ManifestBinding | None,
    selected_path: Path,
    resolved_path: Path,
) -> None:
    if expected is None:
        return
    if expected.selected_path != selected_path:
        raise ManifestBindingError("selected bundle manifest path changed")
    if expected.resolved_path != resolved_path:
        raise ManifestBindingError("selected bundle manifest file target changed")
    if not _SHA256_RE.fullmatch(expected.sha256):
        raise ManifestBindingError("selected bundle manifest digest is invalid")
    if not expected.run_id:
        raise ManifestBindingError("selected bundle manifest run_id is invalid")


def _read_stable_manifest(
    path: Path,
    max_bytes: int,
) -> tuple[bytes, tuple[int, int, int, int, int, int]]:
    try:
        with path.open("rb") as handle:
            descriptor = handle.fileno()
            stat_before = os.fstat(descriptor)
            if not stat.S_ISREG(stat_before.st_mode):
                raise ManifestBindingError(
                    "selected bundle manifest is not a regular file"
                )
            raw = handle.read(max_bytes + 1)
            stat_after = os.fstat(descriptor)
    except ManifestBindingError:
        raise
    except OSError as exc:
        raise ManifestBindingError("selected bundle manifest is unavailable") from exc
    if len(raw) > max_bytes:
        raise ManifestBindingError(
            "selected bundle manifest exceeds the bounded read limit"
        )
    identity = _file_identity(stat_before)
    if identity != _file_identity(stat_after):
        raise ManifestBindingError(
            "selected bundle manifest changed while it was being read"
        )
    try:
        current = path.stat()
    except OSError as exc:
        raise ManifestBindingError(
            "selected bundle manifest changed while it was being read"
        ) from exc
    if identity != _file_identity(current):
        raise ManifestBindingError(
            "selected bundle manifest changed while it was being read"
        )
    return raw, identity


def _build_manifest_binding(
    expected: ManifestBinding | None,
    *,
    selected_path: Path,
    resolved_path: Path,
    raw: bytes,
    document: dict[str, Any],
) -> ManifestBinding:
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    actual_run_id = document["run_id"]
    if expected is None:
        return ManifestBinding(
            selected_path=selected_path,
            resolved_path=resolved_path,
            sha256=actual_sha256,
            run_id=actual_run_id,
        )
    if actual_sha256 != expected.sha256:
        raise ManifestBindingError(
            "selected bundle manifest bytes do not match the selected digest"
        )
    if actual_run_id != expected.run_id:
        raise ManifestBindingError(
            "selected bundle manifest run_id does not match the selection"
        )
    return expected


def capture_manifest_snapshot(
    source: str | Path | ManifestBinding,
    *,
    selected_path: str | Path | None = None,
    max_bytes: int = MAX_MANIFEST_BYTES,
) -> ManifestSnapshot:
    """Read one stable descriptor and validate its path, digest and run identity."""
    expected = source if isinstance(source, ManifestBinding) else None
    if expected is None:
        source_path = manifest_path_identity(source)
        selected = manifest_path_identity(
            source if selected_path is None else selected_path
        )
        resolved = source_path.resolve()
    else:
        if selected_path is not None:
            raise ManifestBindingError(
                "selected_path cannot override an existing manifest binding"
            )
        selected = manifest_path_identity(expected.selected_path)
        # Never resolve the selected path again. A request binding owns the
        # originally resolved file target even if its selected symlink moves.
        resolved = manifest_path_identity(expected.resolved_path)
    _validate_expected_binding(expected, selected, resolved)
    raw, identity = _read_stable_manifest(resolved, max_bytes)
    document = _decode_manifest(raw)
    binding = _build_manifest_binding(
        expected,
        selected_path=selected,
        resolved_path=resolved,
        raw=raw,
        document=document,
    )
    return ManifestSnapshot(binding=binding, raw=raw, file_identity=identity)


def active_manifest_snapshot(
    path: str | Path,
) -> ManifestSnapshot | None:
    snapshot = _ACTIVE_MANIFEST_SNAPSHOT.get()
    if snapshot is None:
        return None
    selected = manifest_path_identity(path)
    if selected in (snapshot.selected_path, snapshot.resolved_path):
        return snapshot
    return None


def resolve_manifest_path(path: str | Path) -> Path:
    """Resolve a path without re-following an active selected symlink."""
    snapshot = active_manifest_snapshot(path)
    if snapshot is not None:
        return snapshot.resolved_path
    return manifest_path_identity(path).resolve()


def manifest_snapshot(path: str | Path) -> ManifestSnapshot:
    return active_manifest_snapshot(path) or capture_manifest_snapshot(path)


def manifest_document(path: str | Path) -> dict[str, Any]:
    return manifest_snapshot(path).json_object()


@contextmanager
def use_manifest_binding(binding: ManifestBinding) -> Iterator[ManifestSnapshot]:
    """Pin one selected manifest snapshot for every consumer in this context."""
    snapshot = capture_manifest_snapshot(binding)
    token = _ACTIVE_MANIFEST_SNAPSHOT.set(snapshot)
    try:
        yield snapshot
        capture_manifest_snapshot(binding)
    finally:
        _ACTIVE_MANIFEST_SNAPSHOT.reset(token)
