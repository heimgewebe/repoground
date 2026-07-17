from __future__ import annotations
import ctypes
import errno
import hashlib

import os
import stat
import sys
from pathlib import Path

import pytest

from merger.lenskit.core import rooted_filesystem
from merger.lenskit.core.rooted_filesystem import (
    RootedFilesystemError,
    atomic_replace_symlink,
    atomic_write_bytes,
    bind_directory,
    copy_verified_file,
    digest_regular_file,
    digest_tree,
    make_directory_exclusive,
    exclusive_file_lock,
    read_regular_bytes,
    read_symlink_target,
    rename_path_no_replace,
    remove_regular_file,
    remove_symlink,
    remove_tree,
    read_tree,
)


def test_atomic_write_uses_bound_directory_and_reads_back(tmp_path: Path) -> None:
    root = tmp_path / "publication"
    with bind_directory(root, create=True) as binding:
        result = atomic_write_bytes(root / "external" / "manifest.json", b"ok\n")
        assert result["durability"] == "durable"
        assert read_regular_bytes(root / "external" / "manifest.json") == b"ok\n"
        binding.assert_current_path_identity()


def test_bound_traversal_rejects_symlinked_parent_component(tmp_path: Path) -> None:
    root = tmp_path / "publication"
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)

    with bind_directory(root):
        with pytest.raises(RootedFilesystemError, match="not a trusted|not trusted"):
            atomic_write_bytes(root / "linked" / "escaped.json", b"no\n")

    assert not (outside / "escaped.json").exists()


def test_exclusive_directory_creation_rejects_existing_entry(tmp_path: Path) -> None:
    root = tmp_path / "publication"
    root.mkdir()
    target = root / "transaction"

    with bind_directory(root):
        make_directory_exclusive(target)
        with pytest.raises(RootedFilesystemError, match="exclusive directory"):
            make_directory_exclusive(target)

    assert target.is_dir()


def test_atomic_write_detects_parent_replacement_without_writing_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "publication"
    lane = root / "lane"
    lane.mkdir(parents=True)
    old_lane = root / "lane-before-swap"
    original_write_all = rooted_filesystem._write_all
    swapped = False

    def swap_parent_then_write(fd: int, payload: bytes) -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            lane.rename(old_lane)
            lane.mkdir()
        original_write_all(fd, payload)

    monkeypatch.setattr(rooted_filesystem, "_write_all", swap_parent_then_write)

    with bind_directory(root):
        with pytest.raises(RootedFilesystemError, match="after replace"):
            atomic_write_bytes(lane / "manifest.json", b"anchored\n")

    assert (old_lane / "manifest.json").read_bytes() == b"anchored\n"
    assert not (lane / "manifest.json").exists()


def test_binding_detects_replacement_of_publication_root(tmp_path: Path) -> None:
    root = tmp_path / "publication"
    root.mkdir()
    moved = tmp_path / "publication-moved"

    with bind_directory(root) as binding:
        root.rename(moved)
        root.mkdir()
        with pytest.raises(RootedFilesystemError, match="identity changed"):
            binding.assert_current_path_identity()


def test_regular_file_open_rejects_symlink(tmp_path: Path) -> None:
    root = tmp_path / "publication"
    root.mkdir()
    target = tmp_path / "target.json"
    target.write_text("outside", encoding="utf-8")
    linked = root / "manifest.json"
    linked.symlink_to(target)

    with bind_directory(root):
        with pytest.raises(RootedFilesystemError, match="regular file"):
            read_regular_bytes(linked)


def test_remove_regular_file_rejects_symlink_and_removes_regular_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "publication"
    root.mkdir()
    victim = tmp_path / "victim.json"
    victim.write_text("keep", encoding="utf-8")
    linked = root / "linked.json"
    linked.symlink_to(victim)

    with bind_directory(root):
        with pytest.raises(RootedFilesystemError, match="non-regular"):
            remove_regular_file(linked)
        regular = root / "pin.json"
        regular.write_text("{}", encoding="utf-8")
        assert remove_regular_file(regular) is True
        assert remove_regular_file(regular, missing_ok=True) is False

    assert victim.read_text(encoding="utf-8") == "keep"


def test_tree_read_rejects_symlink_and_special_entries(tmp_path: Path) -> None:
    root = tmp_path / "publication"
    root.mkdir()
    (root / "regular.txt").write_text("ok", encoding="utf-8")
    (root / "linked.txt").symlink_to(root / "regular.txt")

    with bind_directory(root):
        with pytest.raises(RootedFilesystemError, match="symlink or special"):
            read_tree(root)


def test_lock_normalizes_existing_file_mode(tmp_path: Path) -> None:
    root = tmp_path / "publication"
    lock = root / "lane" / "publish.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("", encoding="utf-8")
    lock.chmod(0o666)

    with bind_directory(root):
        with exclusive_file_lock(lock, mode=0o600):
            assert stat.S_IMODE(lock.stat().st_mode) == 0o600


def test_remove_tree_binds_expected_root_identity(tmp_path: Path) -> None:
    root = tmp_path / "publication"
    tree = root / "tree"
    tree.mkdir(parents=True)
    (tree / "payload").write_text("keep", encoding="utf-8")
    metadata = tree.stat()

    with bind_directory(root):
        with pytest.raises(RootedFilesystemError, match="inode changed"):
            remove_tree(
                tree,
                expected_device=metadata.st_dev,
                expected_inode=metadata.st_ino + 1,
            )
        remove_tree(
            tree,
            expected_device=metadata.st_dev,
            expected_inode=metadata.st_ino,
        )

    assert not tree.exists()


def test_lock_rejects_parent_identity_change(tmp_path: Path) -> None:
    root = tmp_path / "publication"
    lane = root / "lane"
    lane.mkdir(parents=True)
    old_lane = root / "lane-before-swap"

    with bind_directory(root):
        with pytest.raises(RootedFilesystemError, match="identity changed"):
            with exclusive_file_lock(lane / "publish.lock"):
                lane.rename(old_lane)
                lane.mkdir()

    assert (old_lane / "publish.lock").is_file()
    assert not (lane / "publish.lock").exists()


def test_unsupported_platform_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        rooted_filesystem,
        "_required_primitives_supported",
        lambda: False,
    )

    with pytest.raises(RootedFilesystemError, match="unsupported"):
        with bind_directory(tmp_path / "publication", create=True):
            pass


def test_read_tree_returns_only_bound_regular_tree(tmp_path: Path) -> None:
    root = tmp_path / "publication"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "manifest.json").write_bytes(b"{}\n")

    with bind_directory(root):
        files, directories = read_tree(root)

    assert files == {"a/b/manifest.json": b"{}\n"}
    assert directories == {"a", "a/b"}
    assert os.path.samefile(root, root)


def test_verified_copy_rejects_source_file_identity_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(b"trusted\n")
    replacement = tmp_path / "replacement.txt"
    replacement.write_bytes(b"trusted\n")
    destination = tmp_path / "publication" / "copy.txt"
    original = rooted_filesystem._copy_stream

    def copy_then_swap(source_fd: int, destination_fd: int) -> tuple[int, str]:
        result = original(source_fd, destination_fd)
        source.unlink()
        replacement.rename(source)
        return result

    monkeypatch.setattr(rooted_filesystem, "_copy_stream", copy_then_swap)

    with pytest.raises(RootedFilesystemError, match="identity changed"):
        copy_verified_file(
            source,
            destination,
            expected_bytes=8,
            expected_sha256="7bd39a7cbcf687fd60f819645b8bcaf731a9f19cb102484a7b84530516d7e8b8",
        )

    assert not destination.exists()

class _FakeRenameFunction:
    def __init__(self, callback):
        self.callback = callback
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.callback(*args)


def test_darwin_create_only_rename_uses_renameatx_np_exclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "publication"
    root.mkdir()
    source = root / "staged"
    destination = root / "generation"
    source.mkdir()
    (source / "payload").write_bytes(b"ok\n")
    loaded = []

    def emulate_rename(source_fd, source_name, destination_fd, destination_name, flags):
        assert flags == rooted_filesystem._RENAME_EXCL
        destination_text = os.fsdecode(destination_name)
        try:
            os.stat(destination_text, dir_fd=destination_fd, follow_symlinks=False)
        except FileNotFoundError:
            os.rename(
                os.fsdecode(source_name),
                destination_text,
                src_dir_fd=source_fd,
                dst_dir_fd=destination_fd,
            )
            return 0
        ctypes.set_errno(errno.EEXIST)
        return -1

    fake = _FakeRenameFunction(emulate_rename)
    monkeypatch.setattr(rooted_filesystem, "_rename_platform", lambda: "darwin")
    monkeypatch.setattr(
        rooted_filesystem,
        "_load_libc_rename_function",
        lambda name: loaded.append(name) or fake,
    )

    with bind_directory(root):
        rename_path_no_replace(source, destination)

    assert loaded == ["renameatx_np"]
    assert (destination / "payload").read_bytes() == b"ok\n"
    assert not source.exists()


def test_darwin_create_only_rename_preserves_existing_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "publication"
    root.mkdir()
    source = root / "staged"
    destination = root / "generation"
    source.mkdir()
    destination.mkdir()
    (source / "payload").write_bytes(b"new\n")
    (destination / "payload").write_bytes(b"old\n")

    def reject_existing(*_args):
        ctypes.set_errno(errno.EEXIST)
        return -1

    monkeypatch.setattr(rooted_filesystem, "_rename_platform", lambda: "darwin")
    monkeypatch.setattr(
        rooted_filesystem,
        "_load_libc_rename_function",
        lambda _name: _FakeRenameFunction(reject_existing),
    )

    with bind_directory(root):
        with pytest.raises(RootedFilesystemError, match="File exists"):
            rename_path_no_replace(source, destination)

    assert (source / "payload").read_bytes() == b"new\n"
    assert (destination / "payload").read_bytes() == b"old\n"


def test_create_only_rename_unknown_platform_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rooted_filesystem, "_rename_platform", lambda: "unknown-os")
    with pytest.raises(RootedFilesystemError, match="unknown-os"):
        rooted_filesystem._rename_no_replace(10, "source", 11, "destination")

def test_digest_tree_streams_nested_file_metadata(tmp_path: Path) -> None:
    root = tmp_path / "publication"
    nested = root / "a" / "b" / "payload.bin"
    nested.parent.mkdir(parents=True)
    payload = b"streamed-content\n"
    nested.write_bytes(payload)

    with bind_directory(root):
        files, directories = digest_tree(root)

    assert files == {
        "a/b/payload.bin": (len(payload), hashlib.sha256(payload).hexdigest())
    }
    assert directories == {"a", "a/b"}


def test_digest_regular_file_rejects_in_place_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"before\n")
    original = rooted_filesystem._digest_fd

    def digest_then_mutate(fd: int) -> tuple[int, str]:
        result = original(fd)
        source.write_bytes(b"after!\n")
        return result

    monkeypatch.setattr(rooted_filesystem, "_digest_fd", digest_then_mutate)

    with pytest.raises(RootedFilesystemError, match="changed while hashing"):
        digest_regular_file(source)


def test_digest_tree_rejects_in_place_file_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "publication"
    source = root / "payload.bin"
    root.mkdir()
    source.write_bytes(b"before\n")
    original = rooted_filesystem._digest_fd

    def digest_then_mutate(fd: int) -> tuple[int, str]:
        result = original(fd)
        source.write_bytes(b"after!\n")
        return result

    monkeypatch.setattr(rooted_filesystem, "_digest_fd", digest_then_mutate)

    with bind_directory(root):
        with pytest.raises(RootedFilesystemError, match="changed while hashing"):
            digest_tree(root)


def test_native_create_only_rename_captures_eexist_immediately() -> None:
    def fail_existing(*_args):
        ctypes.set_errno(errno.EEXIST)
        return -1

    with pytest.raises(FileExistsError) as captured:
        rooted_filesystem._call_rename_no_replace(
            _FakeRenameFunction(fail_existing), 10, "source", 11, "destination", 1
        )

    assert captured.value.errno == errno.EEXIST
    assert captured.value.filename == "destination"


def test_native_create_only_rename_without_errno_fails_as_eio() -> None:
    def fail_without_errno(*_args):
        return -1

    with pytest.raises(OSError) as captured:
        rooted_filesystem._call_rename_no_replace(
            _FakeRenameFunction(fail_without_errno), 10, "source", 11, "destination", 1
        )

    assert captured.value.errno == errno.EIO


def test_native_create_only_rename_success_ignores_stale_errno() -> None:
    def succeed_with_stale_errno(*_args):
        ctypes.set_errno(errno.EEXIST)
        return 0

    rooted_filesystem._call_rename_no_replace(
        _FakeRenameFunction(succeed_with_stale_errno),
        10,
        "source",
        11,
        "destination",
        1,
    )


def test_digest_tree_is_not_limited_by_python_recursion_depth(tmp_path: Path) -> None:
    root = tmp_path / "publication"
    current = root
    current.mkdir()
    depth = 120
    for index in range(depth):
        current = current / f"d{index}"
        current.mkdir()
    payload = b"deep-leaf\n"
    (current / "leaf.bin").write_bytes(payload)

    previous_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(100)
    try:
        files, directories = digest_tree(root)
    finally:
        sys.setrecursionlimit(previous_limit)

    relative = "/".join([*(f"d{index}" for index in range(depth)), "leaf.bin"])
    assert files[relative] == (len(payload), hashlib.sha256(payload).hexdigest())
    assert len(directories) == depth


def test_read_regular_bytes_enforces_size_ceiling(tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"0123456789")

    with pytest.raises(RootedFilesystemError, match="exceeds maximum size 9"):
        read_regular_bytes(payload, max_bytes=9)

    assert read_regular_bytes(payload, max_bytes=10) == b"0123456789"


def test_remove_symlink_rejects_regular_file_and_removes_only_link(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("preserved\n", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target.name)

    assert remove_symlink(link) is True
    assert target.read_text(encoding="utf-8") == "preserved\n"
    with pytest.raises(RootedFilesystemError, match="not a symlink"):
        remove_symlink(target)


def test_atomic_replace_symlink_round_trips_through_bound_parent(tmp_path: Path) -> None:
    lane = tmp_path / "lane"
    lane.mkdir()
    current = lane / "current"

    atomic_replace_symlink(current, "generation-a")
    assert read_symlink_target(current) == "generation-a"

    atomic_replace_symlink(current, "generation-b")
    assert read_symlink_target(current) == "generation-b"


def test_atomic_replace_symlink_rejects_parent_swap_during_temp_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = tmp_path / "lane"
    displaced = tmp_path / "lane-displaced"
    lane.mkdir()
    current = lane / "current"
    original_symlink = os.symlink

    def create_then_swap(
        target: str,
        name: str,
        *,
        dir_fd: int | None = None,
    ) -> None:
        original_symlink(target, name, dir_fd=dir_fd)
        lane.rename(displaced)
        lane.mkdir()

    monkeypatch.setattr(rooted_filesystem.os, "symlink", create_then_swap)

    with pytest.raises(RootedFilesystemError, match="identity changed"):
        atomic_replace_symlink(current, "generation-a")

    assert not os.path.lexists(current)
    assert not any(path.name.startswith(".current.") for path in displaced.iterdir())


@pytest.mark.parametrize("swap_phase", ["before", "after"])
def test_atomic_replace_symlink_rejects_parent_swap_around_atomic_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    swap_phase: str,
) -> None:
    lane = tmp_path / "lane"
    displaced = tmp_path / "lane-displaced"
    lane.mkdir()
    current = lane / "current"
    original_rename = os.rename

    def rename_with_swap(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        pointer_exchange = (
            isinstance(source, str)
            and source.startswith(".current.")
            and destination == "current"
            and src_dir_fd is not None
            and dst_dir_fd is not None
        )
        if pointer_exchange and swap_phase == "before":
            original_rename(lane, displaced)
            lane.mkdir()
        original_rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        if pointer_exchange and swap_phase == "after":
            original_rename(lane, displaced)
            lane.mkdir()

    monkeypatch.setattr(rooted_filesystem.os, "rename", rename_with_swap)

    with pytest.raises(RootedFilesystemError, match="identity changed"):
        atomic_replace_symlink(current, "generation-a")

    assert not os.path.lexists(current)
    assert read_symlink_target(displaced / "current") == "generation-a"


def test_read_symlink_target_uses_bound_parent_and_rejects_path_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = tmp_path / "lane"
    displaced = tmp_path / "lane-displaced"
    lane.mkdir()
    current = lane / "current"
    current.symlink_to("generation-a")
    original_readlink = os.readlink
    swapped = False

    def readlink_with_swap(
        name: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        dir_fd: int | None = None,
    ) -> str:
        nonlocal swapped
        if not swapped and name == "current" and dir_fd is not None:
            swapped = True
            lane.rename(displaced)
            lane.mkdir()
            (lane / "current").symlink_to("generation-b")
        return original_readlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(rooted_filesystem.os, "readlink", readlink_with_swap)

    with pytest.raises(RootedFilesystemError, match="identity changed"):
        read_symlink_target(current)

    assert original_readlink(displaced / "current") == "generation-a"
    assert original_readlink(current) == "generation-b"


def test_atomic_replace_symlink_cleanup_preserves_replaced_temp_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = tmp_path / "lane"
    lane.mkdir()
    current = lane / "current"
    original_rename = os.rename

    def replace_temp_then_fail(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        if (
            isinstance(source, str)
            and source.startswith(".current.")
            and destination == "current"
            and src_dir_fd is not None
        ):
            os.unlink(source, dir_fd=src_dir_fd)
            replacement_fd = os.open(
                source,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=src_dir_fd,
            )
            try:
                os.write(replacement_fd, b"foreign-temp\n")
            finally:
                os.close(replacement_fd)
            raise OSError(errno.EIO, "simulated rename failure")
        original_rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(rooted_filesystem.os, "rename", replace_temp_then_fail)

    with pytest.raises(RootedFilesystemError, match="before replace"):
        atomic_replace_symlink(current, "generation-a")

    leftovers = list(lane.glob(".current.*.tmp"))
    assert len(leftovers) == 1
    assert leftovers[0].read_bytes() == b"foreign-temp\n"
    assert not os.path.lexists(current)


def test_atomic_replace_symlink_reports_failure_after_successful_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = tmp_path / "lane"
    lane.mkdir()
    current = lane / "current"
    original_fsync = os.fsync
    failed = False

    def fail_first_fsync(fd: int) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise OSError(errno.EIO, "simulated parent fsync failure")
        original_fsync(fd)

    monkeypatch.setattr(rooted_filesystem.os, "fsync", fail_first_fsync)

    with pytest.raises(RootedFilesystemError, match="after replace"):
        atomic_replace_symlink(current, "generation-a")

    assert os.readlink(current) == "generation-a"
