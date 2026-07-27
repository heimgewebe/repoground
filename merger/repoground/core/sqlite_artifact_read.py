"""Integrity primitives for a bounded, read-only SQLite bundle artifact."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any, BinaryIO

from merger.repoground.core.bounded_artifact_read import (
    MAX_REGISTERED_ARTIFACT_BYTES,
)

MAX_SQLITE_ARTIFACT_BYTES = MAX_REGISTERED_ARTIFACT_BYTES
SQLITE_HASH_CHUNK_BYTES = 1024 * 1024


class SqliteArtifactValidationError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def sqlite_file_identity(
    value: os.stat_result,
) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _portable_copy_flags(*, write: bool) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL if write else os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def write_portable_sqlite_copy(
    handle: BinaryIO,
    destination: Path,
    *,
    expected_bytes: int,
    expected_sha256: str,
    expected_identity: tuple[int, int, int, int, int],
) -> None:
    digest = hashlib.sha256()
    observed_bytes = 0
    try:
        handle.seek(0)
        descriptor = os.open(destination, _portable_copy_flags(write=True), 0o600)
        with os.fdopen(descriptor, "wb") as target:
            for chunk in iter(
                lambda: handle.read(SQLITE_HASH_CHUNK_BYTES),
                b"",
            ):
                observed_bytes += len(chunk)
                digest.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
    except OSError as exc:
        raise SqliteArtifactValidationError(
            "sqlite_index_portable_copy_failed",
            f"sqlite_index verified copy could not be created: {exc}",
        ) from exc

    if (
        observed_bytes != expected_bytes
        or digest.hexdigest() != expected_sha256
        or sqlite_file_identity(os.fstat(handle.fileno())) != expected_identity
    ):
        raise SqliteArtifactValidationError(
            "sqlite_index_integrity_mismatch",
            "sqlite_index bytes changed while creating the verified copy",
        )
    try:
        os.chmod(destination, stat.S_IRUSR)
    except OSError as exc:
        raise SqliteArtifactValidationError(
            "sqlite_index_portable_copy_failed",
            f"sqlite_index verified copy could not be made read-only: {exc}",
        ) from exc


def verify_sqlite_handle(
    handle: BinaryIO,
    *,
    expected_bytes: int,
    expected_sha256: str,
) -> tuple[int, int, int, int, int]:
    before = os.fstat(handle.fileno())
    if not stat.S_ISREG(before.st_mode):
        raise SqliteArtifactValidationError(
            "sqlite_index_path_invalid",
            "sqlite_index artifact is not a regular file",
        )
    if before.st_size != expected_bytes:
        raise SqliteArtifactValidationError(
            "sqlite_index_integrity_mismatch",
            "sqlite_index byte size does not match active manifest",
        )

    digest = hashlib.sha256()
    observed_bytes = 0
    for chunk in iter(lambda: handle.read(SQLITE_HASH_CHUNK_BYTES), b""):
        observed_bytes += len(chunk)
        digest.update(chunk)
    identity = sqlite_file_identity(before)
    stable_identity = sqlite_file_identity(os.fstat(handle.fileno()))
    if (
        observed_bytes != expected_bytes
        or digest.hexdigest() != expected_sha256
        or stable_identity != identity
    ):
        raise SqliteArtifactValidationError(
            "sqlite_index_integrity_mismatch",
            "sqlite_index bytes do not match active manifest",
        )
    return identity


def verify_portable_sqlite_copy(
    path: Path,
    *,
    expected_bytes: int,
    expected_sha256: str,
) -> None:
    try:
        descriptor = os.open(path, _portable_copy_flags(write=False))
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if stat.S_IMODE(before.st_mode) & 0o222:
                raise SqliteArtifactValidationError(
                    "sqlite_index_integrity_mismatch",
                    "sqlite_index verified copy is not read-only",
                )
            identity = verify_sqlite_handle(
                handle,
                expected_bytes=expected_bytes,
                expected_sha256=expected_sha256,
            )
        current = os.stat(path, follow_symlinks=False)
    except SqliteArtifactValidationError:
        raise
    except OSError as exc:
        raise SqliteArtifactValidationError(
            "sqlite_index_integrity_mismatch",
            f"sqlite_index verified copy is unavailable: {exc}",
        ) from exc
    if (
        not stat.S_ISREG(current.st_mode)
        or sqlite_file_identity(current) != identity
    ):
        raise SqliteArtifactValidationError(
            "sqlite_index_integrity_mismatch",
            "sqlite_index verified copy changed while it was checked",
        )


def sqlite_integrity_contract(
    artifact: dict[str, Any],
) -> tuple[int, str]:
    expected_bytes = artifact.get("bytes")
    expected_sha256 = artifact.get("sha256")
    valid_sha256 = (
        isinstance(expected_sha256, str)
        and len(expected_sha256) == 64
        and all(character in "0123456789abcdef" for character in expected_sha256)
    )
    if (
        not isinstance(expected_bytes, int)
        or isinstance(expected_bytes, bool)
        or expected_bytes < 0
        or not valid_sha256
    ):
        raise SqliteArtifactValidationError(
            "sqlite_index_integrity_unavailable",
            "sqlite_index bytes/sha256 contract is missing or invalid in manifest",
        )
    if expected_bytes > MAX_SQLITE_ARTIFACT_BYTES:
        raise SqliteArtifactValidationError(
            "sqlite_index_too_large",
            "sqlite_index exceeds the bounded read limit",
        )
    return expected_bytes, expected_sha256


def open_sqlite_artifact(index_path: Path) -> BinaryIO:
    try:
        return index_path.open("rb")
    except FileNotFoundError as exc:
        raise SqliteArtifactValidationError(
            "sqlite_index_file_missing",
            "sqlite_index artifact file does not exist",
        ) from exc
    except OSError as exc:
        raise SqliteArtifactValidationError(
            "sqlite_index_unreadable",
            f"sqlite_index artifact cannot be opened: {exc}",
        ) from exc


def require_current_sqlite_path(
    index_path: Path,
    expected_identity: tuple[int, int, int, int, int],
) -> None:
    try:
        current_identity = sqlite_file_identity(index_path.stat())
    except OSError as exc:
        raise SqliteArtifactValidationError(
            "sqlite_index_integrity_mismatch",
            "sqlite_index path changed during manifest verification",
        ) from exc
    if current_identity != expected_identity:
        raise SqliteArtifactValidationError(
            "sqlite_index_integrity_mismatch",
            "sqlite_index path changed during manifest verification",
        )
