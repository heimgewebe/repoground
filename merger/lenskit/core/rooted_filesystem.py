"""Trusted-directory-descriptor filesystem primitives for local publication.

The module intentionally supports only POSIX platforms that expose the dir_fd,
O_DIRECTORY and O_NOFOLLOW primitives required by the declared threat model.
Unsupported platforms fail closed instead of silently falling back to pathname
operations.
"""

from __future__ import annotations

import contextlib
import contextvars
import ctypes
import errno
import fcntl
import hashlib
import os
import secrets
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


class RootedFilesystemError(OSError):
    """Raised when a rooted filesystem operation cannot preserve its contract."""


_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_FILE_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_SYMLINK_DIR_FD_SUPPORTED = os.symlink in os.supports_dir_fd
_READLINK_DIR_FD_SUPPORTED = os.readlink in os.supports_dir_fd
_SYMLINK_UNSUPPORTED_ERRNOS = frozenset(
    {errno.EOPNOTSUPP, errno.ENOSYS, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP)}
)
_IO_CHUNK_BYTES = 1024 * 1024
_SELECTION = contextvars.ContextVar[tuple["DirectoryBinding", ...]](
    "lenskit_rooted_filesystem_bindings",
    default=(),
)


_REQUIRED_PRIMITIVES_SUPPORTED = (
    os.name == "posix"
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    and all(
        function in os.supports_dir_fd
        for function in (os.open, os.mkdir, os.rename, os.stat, os.unlink, os.rmdir)
    )
)


def _required_primitives_supported() -> bool:
    return _REQUIRED_PRIMITIVES_SUPPORTED


def require_rooted_filesystem_support() -> None:
    """Fail closed when the host cannot provide the required path semantics."""
    if not _required_primitives_supported():
        raise RootedFilesystemError(
            "trusted dirfd filesystem operations are unsupported on this platform"
        )


def secure_absolute(path: str | Path) -> Path:
    """Return an absolute lexical path without following any symlink."""
    expanded = os.path.expanduser(os.fspath(path))
    if not os.path.isabs(expanded):
        expanded = os.path.join(os.getcwd(), expanded)
    normalized = os.path.normpath(expanded)
    if not os.path.isabs(normalized):
        raise RootedFilesystemError(
            f"path did not normalize to an absolute path: {path}"
        )
    return Path(normalized)


def _relative_parts(path: str | Path, *, allow_root: bool = True) -> tuple[str, ...]:
    raw = os.fspath(path)
    if not raw or os.path.isabs(raw) or "\\" in raw:
        raise RootedFilesystemError(
            f"path must be a non-empty relative POSIX path: {path}"
        )
    parts = tuple(part for part in Path(raw).parts if part != ".")
    if any(part in {"", ".", ".."} for part in parts):
        raise RootedFilesystemError(f"path contains a traversal component: {path}")
    if not parts and not allow_root:
        raise RootedFilesystemError(f"path must name an entry: {path}")
    return parts


def _absolute_parts(path: Path) -> tuple[str, ...]:
    absolute = secure_absolute(path)
    return tuple(
        part for part in absolute.parts if part not in {absolute.anchor, "/", ""}
    )


def _open_child_directory(
    parent_fd: int,
    name: str,
    *,
    create: bool,
    mode: int,
    label: str,
) -> int:
    try:
        return os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            raise
        try:
            os.mkdir(name, mode=mode, dir_fd=parent_fd)
        except FileExistsError:
            pass
        try:
            return os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        except OSError as exc:
            raise RootedFilesystemError(
                f"directory component is not a trusted real directory: {label}: {name}"
            ) from exc
    except OSError as exc:
        raise RootedFilesystemError(
            f"directory component is not a trusted real directory: {label}: {name}"
        ) from exc


def _open_absolute_directory(path: Path, *, create: bool, mode: int = 0o755) -> int:
    require_rooted_filesystem_support()
    absolute = secure_absolute(path)
    current_fd = os.open("/", _DIRECTORY_FLAGS)
    try:
        for part in _absolute_parts(absolute):
            next_fd = _open_child_directory(
                current_fd,
                part,
                create=create,
                mode=mode,
                label=str(absolute),
            )
            os.close(current_fd)
            current_fd = next_fd
        metadata = os.fstat(current_fd)
        if not stat.S_ISDIR(metadata.st_mode):
            raise RootedFilesystemError(f"path is not a directory: {absolute}")
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


@dataclass(frozen=True)
class DirectoryBinding:
    """One open directory identity used as an anchor for descendant operations."""

    path: Path
    fd: int
    device: int
    inode: int

    @classmethod
    def open(cls, path: str | Path, *, create: bool = False) -> "DirectoryBinding":
        absolute = secure_absolute(path)
        try:
            fd = _open_absolute_directory(absolute, create=create)
        except OSError as exc:
            if isinstance(exc, RootedFilesystemError):
                raise
            raise RootedFilesystemError(
                f"trusted directory cannot be opened: {absolute}"
            ) from exc
        metadata = os.fstat(fd)
        return cls(
            path=absolute,
            fd=fd,
            device=metadata.st_dev,
            inode=metadata.st_ino,
        )

    def close(self) -> None:
        os.close(self.fd)

    def assert_current_path_identity(self) -> None:
        """Verify that the user-visible path still names the anchored directory."""
        try:
            current_fd = _open_absolute_directory(self.path, create=False)
        except OSError as exc:
            raise RootedFilesystemError(
                f"bound directory path no longer resolves to its trusted identity: {self.path}"
            ) from exc
        try:
            metadata = os.fstat(current_fd)
            if (metadata.st_dev, metadata.st_ino) != (self.device, self.inode):
                raise RootedFilesystemError(
                    f"bound directory path identity changed during operation: {self.path}"
                )
        finally:
            os.close(current_fd)


@contextlib.contextmanager
def bind_directory(
    path: str | Path,
    *,
    create: bool = False,
) -> Iterator[DirectoryBinding]:
    """Bind a path to one directory identity for all nested secure operations."""
    absolute = secure_absolute(path)
    for existing in reversed(_SELECTION.get()):
        if existing.path == absolute:
            yield existing
            return
    binding = DirectoryBinding.open(absolute, create=create)
    token = _SELECTION.set((*_SELECTION.get(), binding))
    try:
        yield binding
    finally:
        _SELECTION.reset(token)
        binding.close()


def _matching_binding(path: Path) -> tuple[DirectoryBinding, Path] | None:
    absolute = secure_absolute(path)
    matches: list[tuple[int, DirectoryBinding, Path]] = []
    for binding in _SELECTION.get():
        try:
            relative = absolute.relative_to(binding.path)
        except ValueError:
            continue
        matches.append((len(binding.path.parts), binding, relative))
    if not matches:
        return None
    _, binding, relative = max(matches, key=lambda row: row[0])
    return binding, relative


def _open_descendant_directory(
    binding: DirectoryBinding,
    relative: Path,
    *,
    create: bool,
    mode: int = 0o755,
) -> int:
    current_fd = os.dup(binding.fd)
    try:
        if relative == Path("."):
            return current_fd
        for part in _relative_parts(relative):
            next_fd = _open_child_directory(
                current_fd,
                part,
                create=create,
                mode=mode,
                label=str(binding.path / relative),
            )
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _open_directory(path: str | Path, *, create: bool = False) -> int:
    absolute = secure_absolute(path)
    matched = _matching_binding(absolute)
    if matched is None:
        return _open_absolute_directory(absolute, create=create)
    binding, relative = matched
    return _open_descendant_directory(binding, relative, create=create)


def _open_parent(
    path: str | Path,
    *,
    create: bool,
) -> tuple[int, str, Path]:
    absolute = secure_absolute(path)
    if absolute == Path("/"):
        raise RootedFilesystemError("filesystem root cannot be used as a file entry")
    parent_fd = _open_directory(absolute.parent, create=create)
    return parent_fd, absolute.name, absolute


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _content_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _assert_directory_fd_matches_path(fd: int, path: str | Path) -> None:
    absolute = secure_absolute(path)
    expected = _identity(os.fstat(fd))
    try:
        current_fd = _open_absolute_directory(absolute, create=False)
    except OSError as exc:
        raise RootedFilesystemError(
            f"directory path no longer resolves during rooted operation: {absolute}"
        ) from exc
    try:
        if _identity(os.fstat(current_fd)) != expected:
            raise RootedFilesystemError(
                f"directory path identity changed during rooted operation: {absolute}"
            )
    finally:
        os.close(current_fd)


def _open_absolute_regular_file(path: str | Path) -> tuple[int, int]:
    absolute = secure_absolute(path)
    parent_fd = _open_absolute_directory(absolute.parent, create=False)
    try:
        fd = os.open(
            absolute.name,
            os.O_RDONLY | _FILE_NOFOLLOW,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        raise RootedFilesystemError(
            f"entry must be an existing regular file: {absolute}"
        ) from exc
    finally:
        os.close(parent_fd)
    metadata = os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode):
        os.close(fd)
        raise RootedFilesystemError(f"entry must be a regular file: {absolute}")
    return fd, metadata.st_size


def _assert_regular_fd_matches_path(fd: int, path: str | Path) -> None:
    expected = _identity(os.fstat(fd))
    current_fd, _ = _open_absolute_regular_file(path)
    try:
        if _identity(os.fstat(current_fd)) != expected:
            raise RootedFilesystemError(
                f"regular file path identity changed during rooted operation: {secure_absolute(path)}"
            )
    finally:
        os.close(current_fd)


def open_regular_file(path: str | Path, *, flags: int = os.O_RDONLY) -> tuple[int, int]:
    """Open a regular file without following the file or any bound ancestor."""
    parent_fd, name, absolute = _open_parent(path, create=False)
    fd: int | None = None
    try:
        fd = os.open(name, flags | _FILE_NOFOLLOW, dir_fd=parent_fd)
        _assert_directory_fd_matches_path(parent_fd, absolute.parent)
    except OSError as exc:
        if fd is not None:
            os.close(fd)
        raise RootedFilesystemError(
            f"entry must be an existing regular file: {absolute}"
        ) from exc
    finally:
        os.close(parent_fd)
    assert fd is not None
    metadata = os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode):
        os.close(fd)
        raise RootedFilesystemError(f"entry must be a regular file: {absolute}")
    return fd, metadata.st_size


def read_regular_bytes(
    path: str | Path, *, max_bytes: int | None = None
) -> bytes:
    """Read one stable descriptor-bound regular file with an optional size ceiling."""
    if max_bytes is not None and max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    fd, _ = open_regular_file(path)
    chunks: list[bytes] = []
    observed = 0
    try:
        before = os.fstat(fd)
        if max_bytes is not None and before.st_size > max_bytes:
            raise RootedFilesystemError(
                f"regular file exceeds maximum size {max_bytes}: {secure_absolute(path)}"
            )
        while True:
            chunk = os.read(fd, _IO_CHUNK_BYTES)
            if not chunk:
                break
            observed += len(chunk)
            if max_bytes is not None and observed > max_bytes:
                raise RootedFilesystemError(
                    f"regular file exceeds maximum size {max_bytes}: {secure_absolute(path)}"
                )
            chunks.append(chunk)
        after = os.fstat(fd)
        if _content_identity(before) != _content_identity(after):
            raise RootedFilesystemError(
                f"regular file changed while reading: {secure_absolute(path)}"
            )
        if observed != after.st_size:
            raise RootedFilesystemError(
                f"regular file size changed while reading: {secure_absolute(path)}"
            )
        _assert_regular_fd_matches_path(fd, path)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _digest_fd(fd: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    observed = 0
    while True:
        chunk = os.read(fd, _IO_CHUNK_BYTES)
        if not chunk:
            return observed, digest.hexdigest()
        observed += len(chunk)
        digest.update(chunk)


def digest_regular_file(path: str | Path) -> tuple[int, str]:
    """Hash one descriptor-bound regular file without buffering its payload."""
    fd, _ = open_regular_file(path)
    try:
        before = os.fstat(fd)
        observed, digest = _digest_fd(fd)
        after = os.fstat(fd)
        if _content_identity(before) != _content_identity(after):
            raise RootedFilesystemError(
                f"regular file changed while hashing: {secure_absolute(path)}"
            )
        if observed != after.st_size:
            raise RootedFilesystemError(
                f"regular file size changed while hashing: {secure_absolute(path)}"
            )
        _assert_regular_fd_matches_path(fd, path)
        return observed, digest
    finally:
        os.close(fd)


def make_directories(path: str | Path, *, mode: int = 0o755) -> None:
    fd = _open_directory(path, create=True)
    try:
        os.fsync(fd)
        _assert_directory_fd_matches_path(fd, path)
    finally:
        os.close(fd)


def make_directory_exclusive(path: str | Path, *, mode: int = 0o700) -> None:
    """Create exactly one directory without accepting a pre-existing entry."""
    parent_fd, name, absolute = _open_parent(path, create=True)
    try:
        os.mkdir(name, mode=mode, dir_fd=parent_fd)
        child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        try:
            metadata = os.fstat(child_fd)
            if not stat.S_ISDIR(metadata.st_mode):
                raise RootedFilesystemError(
                    f"created entry is not a directory: {absolute}"
                )
            os.fsync(child_fd)
        finally:
            os.close(child_fd)
        os.fsync(parent_fd)
        _assert_directory_fd_matches_path(parent_fd, absolute.parent)
    except RootedFilesystemError:
        raise
    except OSError as exc:
        raise RootedFilesystemError(
            f"rooted exclusive directory creation failed: {absolute}: {exc}"
        ) from exc
    finally:
        os.close(parent_fd)


def fsync_directory(path: str | Path) -> None:
    fd = _open_directory(path, create=False)
    try:
        os.fsync(fd)
        _assert_directory_fd_matches_path(fd, path)
    finally:
        os.close(fd)


def lstat_path(path: str | Path) -> os.stat_result:
    parent_fd, name, absolute = _open_parent(path, create=False)
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        _assert_directory_fd_matches_path(parent_fd, absolute.parent)
        return metadata
    except OSError as exc:
        raise RootedFilesystemError(f"entry cannot be inspected: {absolute}") from exc
    finally:
        os.close(parent_fd)


def path_exists(path: str | Path) -> bool:
    try:
        lstat_path(path)
    except FileNotFoundError:
        return False
    except RootedFilesystemError as exc:
        if (
            exc.__cause__ is not None
            and getattr(exc.__cause__, "errno", None) == errno.ENOENT
        ):
            return False
        raise
    return True


def path_is_real_directory(path: str | Path) -> bool:
    try:
        metadata = lstat_path(path)
    except (FileNotFoundError, RootedFilesystemError):
        return False
    return stat.S_ISDIR(metadata.st_mode)


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise RootedFilesystemError("short write while writing rooted file")
        view = view[written:]


def _new_temp_name(prefix: str) -> str:
    return f".{prefix}.{secrets.token_hex(12)}.tmp"


def atomic_write_bytes(
    path: str | Path,
    payload: bytes,
    *,
    mode: int = 0o600,
) -> dict[str, object]:
    """Atomically replace one file through its already-open parent directory."""
    parent_fd, name, absolute = _open_parent(path, create=True)
    temp_name = _new_temp_name(name)
    temp_created = False
    replaced = False
    try:
        fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _FILE_NOFOLLOW,
            mode,
            dir_fd=parent_fd,
        )
        temp_created = True
        try:
            _write_all(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.rename(
            temp_name,
            name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        replaced = True
        temp_created = False
        try:
            os.fsync(parent_fd)
            _assert_directory_fd_matches_path(parent_fd, absolute.parent)
        except RootedFilesystemError:
            raise
        except OSError as exc:
            visible_fd = os.open(name, os.O_RDONLY | _FILE_NOFOLLOW, dir_fd=parent_fd)
            try:
                visible_chunks: list[bytes] = []
                while True:
                    chunk = os.read(visible_fd, 1024 * 1024)
                    if not chunk:
                        break
                    visible_chunks.append(chunk)
            finally:
                os.close(visible_fd)
            if b"".join(visible_chunks) == payload:
                _assert_directory_fd_matches_path(parent_fd, absolute.parent)
                return {
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "durability": "uncertain_after_directory_fsync",
                    "error": str(exc),
                }
            raise
    except OSError as exc:
        phase = "after replace" if replaced else "before replace"
        raise RootedFilesystemError(
            f"rooted atomic write failed {phase}: {absolute}: {exc}"
        ) from exc
    finally:
        if temp_created:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except OSError:
                pass
        os.close(parent_fd)
    return {
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "durability": "durable",
    }


def exclusive_write_bytes(
    path: str | Path,
    payload: bytes,
    *,
    mode: int = 0o600,
) -> None:
    parent_fd, name, absolute = _open_parent(path, create=True)
    try:
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _FILE_NOFOLLOW,
            mode,
            dir_fd=parent_fd,
        )
        try:
            _write_all(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(parent_fd)
        _assert_directory_fd_matches_path(parent_fd, absolute.parent)
    except OSError as exc:
        raise RootedFilesystemError(
            f"rooted exclusive write failed: {absolute}: {exc}"
        ) from exc
    finally:
        os.close(parent_fd)


def _read_stable_symlink_entry(
    parent_fd: int,
    name: str,
    absolute: Path,
) -> tuple[str, tuple[int, int, int, int, int]]:
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISLNK(before.st_mode):
        raise RootedFilesystemError(f"entry is not a symlink: {absolute}")
    target = os.readlink(name, dir_fd=parent_fd)
    after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if _content_identity(before) != _content_identity(after):
        raise RootedFilesystemError(f"symlink changed while reading: {absolute}")
    return target, _content_identity(after)


def read_symlink_target(path: str | Path) -> str:
    """Read one stable symlink target through its already-open parent directory."""
    if not _READLINK_DIR_FD_SUPPORTED:
        raise RootedFilesystemError(
            "trusted dirfd symlink reads are unsupported on this platform"
        )
    parent_fd, name, absolute = _open_parent(path, create=False)
    try:
        target, _entry_identity = _read_stable_symlink_entry(
            parent_fd, name, absolute
        )
        _assert_directory_fd_matches_path(parent_fd, absolute.parent)
        return target
    except RootedFilesystemError:
        raise
    except OSError as exc:
        raise RootedFilesystemError(f"symlink cannot be read: {absolute}") from exc
    finally:
        os.close(parent_fd)


def _create_verified_temp_symlink(
    parent_fd: int,
    temp_name: str,
    target: str,
    absolute: Path,
) -> tuple[int, int, int, int, int]:
    try:
        os.symlink(target, temp_name, dir_fd=parent_fd)
    except OSError as exc:
        if exc.errno in _SYMLINK_UNSUPPORTED_ERRNOS:
            raise NotImplementedError(str(exc)) from exc
        raise
    observed_target, identity = _read_stable_symlink_entry(
        parent_fd, temp_name, absolute.parent / temp_name
    )
    if observed_target != target:
        raise RootedFilesystemError(
            f"temporary symlink readback mismatch: {absolute.parent / temp_name}"
        )
    return identity


def _verify_published_symlink(
    parent_fd: int,
    name: str,
    target: str,
    absolute: Path,
) -> None:
    observed_target, _identity_after = _read_stable_symlink_entry(
        parent_fd, name, absolute
    )
    if observed_target != target:
        raise RootedFilesystemError(
            f"published symlink selected the wrong target: {absolute}"
        )
    _assert_directory_fd_matches_path(parent_fd, absolute.parent)


def _cleanup_owned_temp_symlink(
    parent_fd: int,
    temp_name: str,
    expected_identity: tuple[int, int, int, int, int] | None,
) -> None:
    if expected_identity is None:
        return
    try:
        current = os.stat(temp_name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        return
    if not stat.S_ISLNK(current.st_mode):
        return
    if _content_identity(current) != expected_identity:
        return
    try:
        os.unlink(temp_name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except OSError:
        pass


def atomic_replace_symlink(path: str | Path, target: str) -> None:
    """Atomically replace one symlink through a stable parent descriptor."""
    if not _SYMLINK_DIR_FD_SUPPORTED or not _READLINK_DIR_FD_SUPPORTED:
        raise NotImplementedError(
            "trusted dirfd symlink publication is unsupported on this platform"
        )
    parent_fd, name, absolute = _open_parent(path, create=True)
    temp_name = _new_temp_name(name)
    temp_identity: tuple[int, int, int, int, int] | None = None
    replaced = False
    try:
        _assert_directory_fd_matches_path(parent_fd, absolute.parent)
        temp_identity = _create_verified_temp_symlink(
            parent_fd, temp_name, target, absolute
        )
        _assert_directory_fd_matches_path(parent_fd, absolute.parent)
        os.rename(
            temp_name,
            name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        replaced = True
        temp_identity = None
        os.fsync(parent_fd)
        _verify_published_symlink(parent_fd, name, target, absolute)
    except NotImplementedError:
        raise
    except RootedFilesystemError:
        raise
    except OSError as exc:
        phase = "after replace" if replaced else "before replace"
        raise RootedFilesystemError(
            f"rooted symlink publication failed {phase}: {absolute}: {exc}"
        ) from exc
    finally:
        _cleanup_owned_temp_symlink(parent_fd, temp_name, temp_identity)
        os.close(parent_fd)


def remove_symlink(path: str | Path, *, missing_ok: bool = False) -> bool:
    """Remove exactly one symlink without following it or any bound ancestor."""
    parent_fd, name, absolute = _open_parent(path, create=False)
    try:
        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            if missing_ok:
                return False
            raise
        if not stat.S_ISLNK(metadata.st_mode):
            raise RootedFilesystemError(f"entry is not a symlink: {absolute}")
        os.unlink(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        _assert_directory_fd_matches_path(parent_fd, absolute.parent)
        return True
    except RootedFilesystemError:
        raise
    except OSError as exc:
        raise RootedFilesystemError(f"symlink cannot be removed: {absolute}") from exc
    finally:
        os.close(parent_fd)


def remove_regular_file(path: str | Path, *, missing_ok: bool = False) -> bool:
    """Remove one regular file through its already-open parent directory."""
    try:
        parent_fd, name, absolute = _open_parent(path, create=False)
    except FileNotFoundError:
        if missing_ok:
            return False
        raise
    try:
        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            if missing_ok:
                return False
            raise
        if not stat.S_ISREG(metadata.st_mode):
            raise RootedFilesystemError(
                f"refusing to remove a non-regular file: {absolute}"
            )
        os.unlink(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        _assert_directory_fd_matches_path(parent_fd, absolute.parent)
        return True
    except RootedFilesystemError:
        raise
    except OSError as exc:
        raise RootedFilesystemError(
            f"rooted regular-file removal failed: {absolute}: {exc}"
        ) from exc
    finally:
        os.close(parent_fd)


def _copy_stream(source_fd: int, destination_fd: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    observed = 0
    while True:
        chunk = os.read(source_fd, _IO_CHUNK_BYTES)
        if not chunk:
            break
        observed += len(chunk)
        digest.update(chunk)
        _write_all(destination_fd, chunk)
    os.fsync(destination_fd)
    return observed, digest.hexdigest()


def _verify_copy_integrity(
    *,
    observed_bytes: int,
    observed_sha256: str,
    expected_bytes: int,
    expected_sha256: str,
) -> None:
    if observed_bytes != expected_bytes:
        raise RootedFilesystemError(
            f"source byte count mismatch: expected {expected_bytes}, observed {observed_bytes}"
        )
    if observed_sha256 != expected_sha256:
        raise RootedFilesystemError(
            f"source sha256 mismatch: expected {expected_sha256}, observed {observed_sha256}"
        )


def _commit_temporary_file(parent_fd: int, temp_name: str, name: str) -> None:
    os.rename(
        temp_name,
        name,
        src_dir_fd=parent_fd,
        dst_dir_fd=parent_fd,
    )
    os.fsync(parent_fd)


def copy_verified_file(
    source: str | Path,
    destination: str | Path,
    *,
    expected_sha256: str,
    expected_bytes: int,
) -> None:
    """Copy one verified regular file and commit it through the destination dirfd."""
    source_fd, source_size = open_regular_file(source)
    if source_size != expected_bytes:
        os.close(source_fd)
        raise RootedFilesystemError(
            f"source byte count mismatch: expected {expected_bytes}, observed {source_size}"
        )
    try:
        parent_fd, name, absolute = _open_parent(destination, create=True)
    except OSError:
        os.close(source_fd)
        raise
    temp_name = _new_temp_name(name)
    temp_created = False
    try:
        destination_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _FILE_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        temp_created = True
        try:
            observed, observed_sha = _copy_stream(source_fd, destination_fd)
        finally:
            os.close(destination_fd)
        _verify_copy_integrity(
            observed_bytes=observed,
            observed_sha256=observed_sha,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
        )
        _assert_regular_fd_matches_path(source_fd, source)
        _commit_temporary_file(parent_fd, temp_name, name)
        temp_created = False
        _assert_directory_fd_matches_path(parent_fd, absolute.parent)
    except RootedFilesystemError:
        raise
    except OSError as exc:
        raise RootedFilesystemError(
            f"rooted verified copy failed: {absolute}: {exc}"
        ) from exc
    finally:
        os.close(source_fd)
        if temp_created:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except OSError:
                pass
        os.close(parent_fd)


def make_temporary_directory(parent: str | Path, *, prefix: str) -> Path:
    parent_absolute = secure_absolute(parent)
    parent_fd = _open_directory(parent_absolute, create=True)
    try:
        for _ in range(128):
            name = f".{prefix}.{secrets.token_hex(12)}.tmp"
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            except FileExistsError:
                continue
            os.fsync(parent_fd)
            try:
                _assert_directory_fd_matches_path(parent_fd, parent_absolute)
            except RootedFilesystemError:
                os.rmdir(name, dir_fd=parent_fd)
                raise
            return parent_absolute / name
    finally:
        os.close(parent_fd)
    raise RootedFilesystemError(f"could not create temporary directory below {parent}")


def rename_path(source: str | Path, destination: str | Path) -> None:
    source_parent, source_name, source_absolute = _open_parent(source, create=False)
    try:
        destination_parent, destination_name, destination_absolute = _open_parent(
            destination,
            create=True,
        )
    except OSError:
        os.close(source_parent)
        raise
    try:
        os.rename(
            source_name,
            destination_name,
            src_dir_fd=source_parent,
            dst_dir_fd=destination_parent,
        )
        os.fsync(destination_parent)
        _assert_directory_fd_matches_path(source_parent, source_absolute.parent)
        _assert_directory_fd_matches_path(
            destination_parent, destination_absolute.parent
        )
    except OSError as exc:
        raise RootedFilesystemError(
            f"rooted rename failed: {source_absolute} -> {destination_absolute}: {exc}"
        ) from exc
    finally:
        os.close(source_parent)
        os.close(destination_parent)


_RENAME_NOREPLACE = 0x00000001
_RENAME_EXCL = 0x00000004
_RENAME_FUNCTION_ARGTYPES = (
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_uint,
)


def _rename_platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform in {"darwin", "ios"}:
        return "darwin"
    try:
        if os.uname().sysname == "Darwin":
            return "darwin"
    except (AttributeError, OSError):
        pass
    return sys.platform


def _load_libc_rename_function(name: str):
    try:
        function = getattr(ctypes.CDLL(None, use_errno=True), name)
    except AttributeError as exc:
        raise RootedFilesystemError(
            f"create-only rooted rename primitive {name} is unavailable"
        ) from exc
    function.argtypes = _RENAME_FUNCTION_ARGTYPES
    function.restype = ctypes.c_int
    return function


def _call_rename_no_replace(
    function,
    source_parent: int,
    source_name: str,
    destination_parent: int,
    destination_name: str,
    flags: int,
) -> None:
    ctypes.set_errno(0)
    result = function(
        source_parent,
        os.fsencode(source_name),
        destination_parent,
        os.fsencode(destination_name),
        flags,
    )
    captured_errno = ctypes.get_errno()
    if result == 0:
        return
    err = captured_errno or errno.EIO
    if err == errno.EEXIST:
        raise FileExistsError(err, os.strerror(err), destination_name)
    raise OSError(err, os.strerror(err), destination_name)


def _rename_no_replace(
    source_parent: int,
    source_name: str,
    destination_parent: int,
    destination_name: str,
) -> None:
    platform = _rename_platform()
    if platform == "linux":
        function = _load_libc_rename_function("renameat2")
        flags = _RENAME_NOREPLACE
    elif platform == "darwin":
        function = _load_libc_rename_function("renameatx_np")
        flags = _RENAME_EXCL
    else:
        raise RootedFilesystemError(
            f"create-only rooted rename is unsupported on platform {platform!r}"
        )
    _call_rename_no_replace(
        function,
        source_parent,
        source_name,
        destination_parent,
        destination_name,
        flags,
    )


def rename_path_no_replace(source: str | Path, destination: str | Path) -> None:
    source_parent, source_name, source_absolute = _open_parent(source, create=False)
    try:
        destination_parent, destination_name, destination_absolute = _open_parent(
            destination,
            create=True,
        )
    except OSError:
        os.close(source_parent)
        raise
    try:
        _rename_no_replace(
            source_parent,
            source_name,
            destination_parent,
            destination_name,
        )
        os.fsync(destination_parent)
        _assert_directory_fd_matches_path(source_parent, source_absolute.parent)
        _assert_directory_fd_matches_path(
            destination_parent, destination_absolute.parent
        )
    except RootedFilesystemError:
        raise
    except OSError as exc:
        raise RootedFilesystemError(
            f"rooted create-only rename failed: {source_absolute} -> {destination_absolute}: {exc}"
        ) from exc
    finally:
        os.close(source_parent)
        os.close(destination_parent)


@dataclass(slots=True)
class _DigestTreeFrame:
    fd: int
    prefix: Path
    directory_before: os.stat_result
    scanner: Any
    owns_fd: bool
    parent_fd: int | None = None
    parent_name: str | None = None
    opened_identity: tuple[int, int] | None = None
    closed: bool = False


def _new_digest_tree_frame(
    fd: int,
    prefix: Path,
    *,
    owns_fd: bool,
    parent_fd: int | None = None,
    parent_name: str | None = None,
    opened_identity: tuple[int, int] | None = None,
) -> _DigestTreeFrame:
    scanner = None
    try:
        scanner = os.scandir(fd)
        directory_before = os.fstat(fd)
    except OSError as exc:
        if scanner is not None:
            scanner.close()
        if owns_fd:
            os.close(fd)
        raise RootedFilesystemError("rooted directory cannot be enumerated") from exc
    return _DigestTreeFrame(
        fd=fd,
        prefix=prefix,
        directory_before=directory_before,
        scanner=scanner,
        owns_fd=owns_fd,
        parent_fd=parent_fd,
        parent_name=parent_name,
        opened_identity=opened_identity,
    )


def _close_digest_tree_frame(frame: _DigestTreeFrame) -> None:
    if frame.closed:
        return
    frame.closed = True
    try:
        frame.scanner.close()
    finally:
        if frame.owns_fd:
            os.close(frame.fd)


def _finish_digest_tree_frame(frame: _DigestTreeFrame) -> None:
    directory_after = os.fstat(frame.fd)
    if _content_identity(frame.directory_before) != _content_identity(directory_after):
        raise RootedFilesystemError(
            "rooted tree directory changed while hashing: "
            f"{frame.prefix.as_posix()}"
        )
    if frame.parent_fd is None:
        return
    assert frame.parent_name is not None
    assert frame.opened_identity is not None
    current = os.stat(
        frame.parent_name,
        dir_fd=frame.parent_fd,
        follow_symlinks=False,
    )
    if _identity(current) != frame.opened_identity:
        raise RootedFilesystemError(
            "rooted tree directory changed while hashing: "
            f"{frame.prefix.as_posix()}"
        )


def _open_digest_tree_child(
    frame: _DigestTreeFrame,
    entry_name: str,
    relative: Path,
) -> _DigestTreeFrame:
    child_fd = os.open(entry_name, _DIRECTORY_FLAGS, dir_fd=frame.fd)
    try:
        opened = os.fstat(child_fd)
    except OSError:
        os.close(child_fd)
        raise
    return _new_digest_tree_frame(
        child_fd,
        relative,
        owns_fd=True,
        parent_fd=frame.fd,
        parent_name=entry_name,
        opened_identity=_identity(opened),
    )


def _digest_tree_regular_entry(
    frame: _DigestTreeFrame,
    entry_name: str,
    relative_text: str,
) -> tuple[int, str]:
    child_fd = os.open(
        entry_name,
        os.O_RDONLY | _FILE_NOFOLLOW,
        dir_fd=frame.fd,
    )
    try:
        before = os.fstat(child_fd)
        observed, digest = _digest_fd(child_fd)
        after = os.fstat(child_fd)
        current = os.stat(entry_name, dir_fd=frame.fd, follow_symlinks=False)
        if _content_identity(before) != _content_identity(after):
            raise RootedFilesystemError(
                f"rooted tree file changed while hashing: {relative_text}"
            )
        if observed != after.st_size or _identity(current) != _identity(after):
            raise RootedFilesystemError(
                f"rooted tree file changed while hashing: {relative_text}"
            )
        return observed, digest
    finally:
        os.close(child_fd)


def _visit_digest_tree_entry(
    frame: _DigestTreeFrame,
    entry_name: str,
    files: dict[str, tuple[int, str]],
    directories: set[str],
    stack: list[_DigestTreeFrame],
) -> None:
    metadata = os.stat(entry_name, dir_fd=frame.fd, follow_symlinks=False)
    relative = frame.prefix / entry_name
    relative_text = relative.as_posix()
    if stat.S_ISDIR(metadata.st_mode):
        directories.add(relative_text)
        stack.append(_open_digest_tree_child(frame, entry_name, relative))
        return
    if stat.S_ISREG(metadata.st_mode):
        files[relative_text] = _digest_tree_regular_entry(
            frame, entry_name, relative_text
        )
        return
    raise RootedFilesystemError(
        f"rooted tree contains a symlink or special entry: {relative_text}"
    )


def _digest_tree_fd(
    fd: int, prefix: Path
) -> tuple[dict[str, tuple[int, str]], set[str]]:
    files: dict[str, tuple[int, str]] = {}
    directories: set[str] = set()
    stack = [_new_digest_tree_frame(fd, prefix, owns_fd=False)]
    try:
        while stack:
            frame = stack[-1]
            try:
                entry = next(frame.scanner)
            except StopIteration:
                _finish_digest_tree_frame(frame)
                _close_digest_tree_frame(frame)
                stack.pop()
                continue
            _visit_digest_tree_entry(
                frame, entry.name, files, directories, stack
            )
    finally:
        for frame in reversed(stack):
            try:
                _close_digest_tree_frame(frame)
            except OSError:
                pass
    return files, directories


def digest_tree(path: str | Path) -> tuple[dict[str, tuple[int, str]], set[str]]:
    """Hash a trusted regular-file tree without retaining file payloads."""
    fd = _open_directory(path, create=False)
    try:
        try:
            result = _digest_tree_fd(fd, Path("."))
        except OSError as exc:
            raise RootedFilesystemError("rooted tree changed while hashing") from exc
        _assert_directory_fd_matches_path(fd, path)
        return result
    finally:
        os.close(fd)


def _read_tree_fd(fd: int, prefix: Path) -> tuple[dict[str, bytes], set[str]]:
    files: dict[str, bytes] = {}
    directories: set[str] = set()
    try:
        with os.scandir(fd) as scanner:
            entries = sorted(scanner, key=lambda entry: entry.name)
    except OSError as exc:
        raise RootedFilesystemError("rooted directory cannot be enumerated") from exc
    for entry in entries:
        metadata = os.stat(entry.name, dir_fd=fd, follow_symlinks=False)
        relative = prefix / entry.name
        relative_text = relative.as_posix()
        if stat.S_ISDIR(metadata.st_mode):
            child_fd = os.open(entry.name, _DIRECTORY_FLAGS, dir_fd=fd)
            try:
                directories.add(relative_text)
                child_files, child_directories = _read_tree_fd(child_fd, relative)
                files.update(child_files)
                directories.update(child_directories)
            finally:
                os.close(child_fd)
        elif stat.S_ISREG(metadata.st_mode):
            child_fd = os.open(
                entry.name,
                os.O_RDONLY | _FILE_NOFOLLOW,
                dir_fd=fd,
            )
            try:
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(child_fd, _IO_CHUNK_BYTES)
                    if not chunk:
                        break
                    chunks.append(chunk)
                files[relative_text] = b"".join(chunks)
            finally:
                os.close(child_fd)
        else:
            raise RootedFilesystemError(
                f"rooted tree contains a symlink or special entry: {relative_text}"
            )
    return files, directories


def read_tree(path: str | Path) -> tuple[dict[str, bytes], set[str]]:
    fd = _open_directory(path, create=False)
    try:
        result = _read_tree_fd(fd, Path("."))
        _assert_directory_fd_matches_path(fd, path)
        return result
    finally:
        os.close(fd)


def _remove_tree_fd(parent_fd: int, name: str) -> None:
    child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    try:
        with os.scandir(child_fd) as scanner:
            entries = list(scanner)
        for entry in entries:
            metadata = os.stat(entry.name, dir_fd=child_fd, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                _remove_tree_fd(child_fd, entry.name)
            elif stat.S_ISREG(metadata.st_mode):
                os.unlink(entry.name, dir_fd=child_fd)
            else:
                raise RootedFilesystemError(
                    f"refusing to remove symlink or special entry: {entry.name}"
                )
        os.fsync(child_fd)
    finally:
        os.close(child_fd)
    os.rmdir(name, dir_fd=parent_fd)


def remove_tree(
    path: str | Path,
    *,
    expected_device: int | None = None,
    expected_inode: int | None = None,
) -> None:
    if not path_exists(path):
        return
    parent_fd, name, absolute = _open_parent(path, create=False)
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(metadata.st_mode):
            raise RootedFilesystemError(
                f"refusing to remove a non-directory tree root: {absolute}"
            )
        if expected_device is not None and metadata.st_dev != expected_device:
            raise RootedFilesystemError(
                f"tree device changed before removal: {absolute}"
            )
        if expected_inode is not None and metadata.st_ino != expected_inode:
            raise RootedFilesystemError(
                f"tree inode changed before removal: {absolute}"
            )
        _remove_tree_fd(parent_fd, name)
        os.fsync(parent_fd)
        _assert_directory_fd_matches_path(parent_fd, absolute.parent)
    finally:
        os.close(parent_fd)


@contextlib.contextmanager
def exclusive_file_lock(path: str | Path, *, mode: int = 0o600) -> Iterator[None]:
    parent_fd, name, absolute = _open_parent(path, create=True)
    try:
        fd = os.open(
            name,
            os.O_RDWR | os.O_CREAT | _FILE_NOFOLLOW,
            mode,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        os.close(parent_fd)
        raise RootedFilesystemError(f"lock file cannot be opened: {absolute}") from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise RootedFilesystemError(f"lock entry is not a regular file: {absolute}")
        os.fchmod(fd, mode)
        fcntl.flock(fd, fcntl.LOCK_EX)
        _assert_directory_fd_matches_path(parent_fd, absolute.parent)
        yield
        _assert_directory_fd_matches_path(parent_fd, absolute.parent)
    except OSError as exc:
        if isinstance(exc, RootedFilesystemError):
            raise
        raise RootedFilesystemError(f"lock cannot be acquired: {absolute}") from exc
    finally:
        os.close(fd)
        os.close(parent_fd)
