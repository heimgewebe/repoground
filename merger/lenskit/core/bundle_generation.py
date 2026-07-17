"""Immutable RepoBrief bundle generations and atomic current selection."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .rooted_filesystem import (
    DirectoryBinding,
    RootedFilesystemError,
    atomic_replace_symlink,
    atomic_write_bytes,
    bind_directory,
    copy_verified_file,
    digest_regular_file,
    digest_tree,
    exclusive_file_lock,
    fsync_directory,
    lstat_path,
    make_directories,
    make_temporary_directory,
    path_exists,
    path_is_real_directory,
    read_regular_bytes,
    read_symlink_target,
    remove_regular_file,
    remove_symlink,
    remove_tree,
    rename_path_no_replace,
    secure_absolute,
)


class BundleGenerationError(RuntimeError):
    """Raised when a bundle generation cannot be published coherently."""


GENERATION_ROOT_NAME = ".repobrief-generations"
CURRENT_LINK_NAME = "current"
CURRENT_POINTER_JSON_NAME = "current.json"
PUBLISH_LOCK_NAME = ".publish.lock"
POINTER_KIND = "repobrief.bundle_generation_pointer"
POINTER_VERSION = "1"
_MAX_POST_EMIT_HEALTH_BYTES = 16 * 1024 * 1024
_MAX_CURRENT_POINTER_BYTES = 1024 * 1024

_SIDECAR_LINK_KEYS = (
    "post_emit_health_path",
    "bundle_surface_validation_path",
    "agent_export_gate_path",
    "export_safety_report_path",
)


@dataclass(frozen=True, slots=True)
class BundleGenerationResult:
    output_root: Path
    bundle_stem: str
    generation_id: str
    generation_dir: Path
    current_pointer_path: Path
    current_manifest_path: Path
    resolved_manifest_path: Path
    manifest_sha256: str
    reused: bool
    pointer_kind: str
    files: dict[str, str]

    def current_path_for(self, source_path: str | Path) -> Path:
        relative = self.files.get(str(secure_absolute(source_path)))
        if relative is None:
            return Path(source_path)
        if self.pointer_kind == "relative_symlink":
            return self.current_pointer_path / Path(*PurePosixPath(relative).parts)
        return self.generation_dir / Path(*PurePosixPath(relative).parts)

    def generation_path_for(self, source_path: str | Path) -> Path:
        relative = self.files.get(str(secure_absolute(source_path)))
        if relative is None:
            return Path(source_path)
        return self.generation_dir / Path(*PurePosixPath(relative).parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "generation_id": self.generation_id,
            "generation_dir": str(self.generation_dir),
            "current_pointer_path": str(self.current_pointer_path),
            "current_manifest_path": str(self.current_manifest_path),
            "resolved_manifest_path": str(self.resolved_manifest_path),
            "manifest_sha256": self.manifest_sha256,
            "reused": self.reused,
            "pointer_kind": self.pointer_kind,
        }


@dataclass(frozen=True, slots=True)
class _BundleFile:
    relative_path: str
    source_path: Path
    byte_count: int
    sha256: str

    @property
    def bytes(self) -> int:
        return self.byte_count


@dataclass(frozen=True, slots=True)
class _PointerState:
    mode: str
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class _PointerSnapshot:
    mode: str
    symlink_target: str | None = None
    json_payload: bytes | None = None


def bundle_stem_from_manifest(manifest_path: str | Path) -> str:
    name = Path(manifest_path).name
    suffix = ".bundle.manifest.json"
    if name.endswith(suffix):
        return name[: -len(suffix)]
    return Path(name).stem


def generation_lane_root(output_root: str | Path, bundle_stem: str) -> Path:
    return secure_absolute(output_root) / GENERATION_ROOT_NAME / bundle_stem


def current_manifest_path(
    output_root: str | Path,
    bundle_stem: str,
    manifest_relative_path: str,
) -> Path:
    return (
        generation_lane_root(output_root, bundle_stem)
        / CURRENT_LINK_NAME
        / Path(*PurePosixPath(manifest_relative_path).parts)
    )


def _json_bytes(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _safe_relative_path(raw_path: Any, *, label: str) -> str:
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        raise BundleGenerationError(f"{label} path must be a relative POSIX file path")
    pure = PurePosixPath(raw_path)
    if pure.is_absolute():
        raise BundleGenerationError(f"{label} path must be relative")
    parts = pure.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise BundleGenerationError(f"{label} path contains traversal")
    return pure.as_posix()


def _resolve_under_root(output_root: Path, raw_path: Any, *, label: str) -> tuple[str, Path]:
    relative = _safe_relative_path(raw_path, label=label)
    candidate = secure_absolute(output_root / Path(*PurePosixPath(relative).parts))
    try:
        candidate.relative_to(output_root)
    except ValueError as exc:
        raise BundleGenerationError(f"{label} path escapes the bundle output root") from exc
    return relative, candidate


def _read_regular_payload(
    path: Path, *, label: str, max_bytes: int | None = None
) -> bytes:
    try:
        return read_regular_bytes(path, max_bytes=max_bytes)
    except RootedFilesystemError as exc:
        raise BundleGenerationError(
            f"{label} must be a stable regular file inside the bundle root: {path}: {exc}"
        ) from exc


def _digest_regular_payload(path: Path, *, label: str) -> tuple[int, str]:
    try:
        return digest_regular_file(path)
    except RootedFilesystemError as exc:
        raise BundleGenerationError(
            f"{label} must be a stable regular file inside the bundle root: {path}"
        ) from exc


def _validate_post_emit_health_binding(payload: bytes, manifest_sha256: str) -> None:
    try:
        report = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleGenerationError("post_emit_health sidecar must be valid UTF-8 JSON") from exc
    if not isinstance(report, dict):
        raise BundleGenerationError("post_emit_health sidecar must be a JSON object")
    declared = report.get("bundle_manifest_sha256")
    if declared is None:
        return
    if not _is_sha256(declared):
        raise BundleGenerationError("post_emit_health bundle_manifest_sha256 is invalid")
    if declared != manifest_sha256:
        raise BundleGenerationError(
            "post_emit_health bundle_manifest_sha256 does not match the final manifest"
        )


def _add_file(
    files: dict[str, _BundleFile],
    *,
    relative_path: str,
    source_path: Path,
    observed_bytes: int,
    observed_sha256: str,
    expected_bytes: Any = None,
    expected_sha256: Any = None,
    label: str,
) -> None:
    if (
        isinstance(expected_bytes, int)
        and not isinstance(expected_bytes, bool)
        and expected_bytes != observed_bytes
    ):
        raise BundleGenerationError(f"{label} byte count does not match the manifest")
    if _is_sha256(expected_sha256) and expected_sha256 != observed_sha256:
        raise BundleGenerationError(f"{label} sha256 does not match the manifest")
    existing = files.get(relative_path)
    if existing is not None:
        if existing.sha256 != observed_sha256 or existing.bytes != observed_bytes:
            raise BundleGenerationError(
                f"bundle file path is declared with conflicting content: {relative_path}"
            )
        return
    files[relative_path] = _BundleFile(
        relative_path=relative_path,
        source_path=source_path,
        byte_count=observed_bytes,
        sha256=observed_sha256,
    )


def _parse_manifest_payload(manifest_payload: bytes) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleGenerationError("bundle manifest must be valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise BundleGenerationError("bundle manifest must be a JSON object")
    return manifest


def _collect_manifest_artifacts(
    manifest: dict[str, Any],
    *,
    output_root: Path,
    files: dict[str, _BundleFile],
) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise BundleGenerationError("bundle manifest artifacts must be an array")
    for index, row in enumerate(artifacts):
        if not isinstance(row, dict):
            continue
        label = f"artifact[{index}]"
        relative, source = _resolve_under_root(output_root, row.get("path"), label=label)
        observed_bytes, observed_sha256 = _digest_regular_payload(source, label=label)
        _add_file(
            files,
            relative_path=relative,
            source_path=source,
            observed_bytes=observed_bytes,
            observed_sha256=observed_sha256,
            expected_bytes=row.get("bytes"),
            expected_sha256=row.get("sha256"),
            label=label,
        )


def _collect_manifest_links(
    manifest: dict[str, Any],
    *,
    output_root: Path,
    files: dict[str, _BundleFile],
    manifest_sha256: str,
) -> None:
    links = manifest.get("links")
    if not isinstance(links, dict):
        return
    for key in _SIDECAR_LINK_KEYS:
        if not links.get(key):
            continue
        label = f"links.{key}"
        relative, source = _resolve_under_root(output_root, links[key], label=label)
        if key == "post_emit_health_path":
            payload = _read_regular_payload(
                source,
                label=label,
                max_bytes=_MAX_POST_EMIT_HEALTH_BYTES,
            )
            _validate_post_emit_health_binding(payload, manifest_sha256)
            observed_bytes = len(payload)
            observed_sha256 = hashlib.sha256(payload).hexdigest()
        else:
            observed_bytes, observed_sha256 = _digest_regular_payload(
                source, label=label
            )
        _add_file(
            files,
            relative_path=relative,
            source_path=source,
            observed_bytes=observed_bytes,
            observed_sha256=observed_sha256,
            label=label,
        )


def _collect_extra_paths(
    extra_paths: Iterable[str | Path],
    *,
    output_root: Path,
    files: dict[str, _BundleFile],
) -> None:
    for raw_path in extra_paths:
        source = secure_absolute(raw_path)
        try:
            relative = source.relative_to(output_root).as_posix()
        except ValueError as exc:
            raise BundleGenerationError(f"extra bundle file escapes output root: {source}") from exc
        _safe_relative_path(relative, label="extra file")
        observed_bytes, observed_sha256 = _digest_regular_payload(
            source, label="extra file"
        )
        _add_file(
            files,
            relative_path=relative,
            source_path=source,
            observed_bytes=observed_bytes,
            observed_sha256=observed_sha256,
            label="extra file",
        )


def _collect_bundle_files(
    manifest_path: Path,
    *,
    output_root: Path,
    extra_paths: Iterable[str | Path] = (),
) -> tuple[dict[str, Any], list[_BundleFile], str]:
    manifest_payload = _read_regular_payload(manifest_path, label="bundle manifest")
    manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()
    manifest = _parse_manifest_payload(manifest_payload)
    files: dict[str, _BundleFile] = {}
    _collect_manifest_artifacts(manifest, output_root=output_root, files=files)
    _collect_manifest_links(
        manifest,
        output_root=output_root,
        files=files,
        manifest_sha256=manifest_sha256,
    )
    _collect_extra_paths(extra_paths, output_root=output_root, files=files)
    manifest_relative = manifest_path.relative_to(output_root).as_posix()
    _add_file(
        files,
        relative_path=manifest_relative,
        source_path=manifest_path,
        observed_bytes=len(manifest_payload),
        observed_sha256=manifest_sha256,
        label="bundle manifest",
    )
    ordered = sorted(
        files.values(),
        key=lambda item: (item.relative_path == manifest_relative, item.relative_path),
    )
    return manifest, ordered, manifest_sha256


def _generation_id(files: list[_BundleFile], *, manifest_sha256: str) -> str:
    seed = {
        "kind": "repobrief.bundle_generation",
        "version": "1",
        "manifest_sha256": manifest_sha256,
        "files": [
            {
                "path": item.relative_path,
                "bytes": item.bytes,
                "sha256": item.sha256,
            }
            for item in files
        ],
    }
    compact = json.dumps(seed, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(compact).hexdigest()


def _expected_files(files: list[_BundleFile]) -> dict[str, tuple[int, str]]:
    return {
        item.relative_path: (item.bytes, item.sha256)
        for item in files
    }


def _expected_directories(files: list[_BundleFile]) -> set[str]:
    directories: set[str] = set()
    for item in files:
        parent = PurePosixPath(item.relative_path).parent
        while parent != PurePosixPath("."):
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def _verify_existing_generation(generation_dir: Path, files: list[_BundleFile]) -> None:
    try:
        observed_files, observed_directories = digest_tree(generation_dir)
    except RootedFilesystemError as exc:
        raise BundleGenerationError(f"existing generation is not a trusted regular-file tree: {generation_dir}") from exc
    if observed_files != _expected_files(files) or observed_directories != _expected_directories(files):
        raise BundleGenerationError("existing generation directory does not match the final bundle file set")


def _copy_generation_file(stage: Path, item: _BundleFile) -> None:
    try:
        copy_verified_file(
            item.source_path,
            stage / item.relative_path,
            expected_sha256=item.sha256,
            expected_bytes=item.bytes,
        )
    except RootedFilesystemError as exc:
        raise BundleGenerationError(f"failed to copy bundle file into generation: {item.relative_path}: {exc}") from exc


def _fsync_generation_directories(stage: Path, files: list[_BundleFile]) -> None:
    for relative in sorted(_expected_directories(files), key=lambda value: value.count("/"), reverse=True):
        try:
            fsync_directory(stage / relative)
        except RootedFilesystemError as exc:
            raise BundleGenerationError(f"failed to fsync generation directory {relative}: {exc}") from exc
    try:
        fsync_directory(stage)
    except RootedFilesystemError as exc:
        raise BundleGenerationError(f"failed to fsync generation directory: {exc}") from exc


def _install_generation(generations_root: Path, generation_id: str, files: list[_BundleFile]) -> tuple[Path, bool]:
    generation_dir = generations_root / generation_id
    try:
        make_directories(generations_root)
        if path_exists(generation_dir):
            _verify_existing_generation(generation_dir, files)
            return generation_dir, True
        stage = make_temporary_directory(generations_root, prefix=generation_id)
        stage_stat = lstat_path(stage)
        installed = False
        try:
            manifest_file = files[-1]
            for item in files[:-1]:
                _copy_generation_file(stage, item)
            _copy_generation_file(stage, manifest_file)
            _fsync_generation_directories(stage, files)
            try:
                rename_path_no_replace(stage, generation_dir)
                installed = True
            except RootedFilesystemError:
                if path_exists(generation_dir):
                    _verify_existing_generation(generation_dir, files)
                    return generation_dir, True
                raise
            try:
                fsync_directory(generations_root)
            except RootedFilesystemError as exc:
                raise BundleGenerationError(f"failed to fsync generation parent: {exc}") from exc
        finally:
            if not installed and path_exists(stage):
                try:
                    remove_tree(
                        stage,
                        expected_device=stage_stat.st_dev,
                        expected_inode=stage_stat.st_ino,
                    )
                except RootedFilesystemError:
                    pass
    except RootedFilesystemError as exc:
        raise BundleGenerationError(f"generation installation failed before current pointer switch: {exc}") from exc
    return generation_dir, False


def _optional_lstat(path: Path) -> os.stat_result | None:
    try:
        return lstat_path(path)
    except RootedFilesystemError as exc:
        if exc.__cause__ is not None and getattr(exc.__cause__, "errno", None) == errno.ENOENT:
            return None
        raise


def _validate_current_symlink(generations_root: Path, current: Path) -> str:
    try:
        target = read_symlink_target(current)
    except RootedFilesystemError as exc:
        raise BundleGenerationError(f"current symlink cannot be read safely: {exc}") from exc
    if not _is_sha256(target) or "/" in target or "\\" in target:
        raise BundleGenerationError("current symlink target is not a valid generation id")
    if not path_is_real_directory(generations_root / target):
        raise BundleGenerationError("current symlink target does not name a valid generation")
    return target


def _parse_current_json_pointer_payload(payload: bytes) -> dict[str, Any]:
    try:
        pointer = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleGenerationError("current JSON pointer must be valid UTF-8 JSON") from exc
    if (
        not isinstance(pointer, dict)
        or pointer.get("kind") != POINTER_KIND
        or pointer.get("version") != POINTER_VERSION
        or not _is_sha256(pointer.get("generation_id"))
        or not _is_sha256(pointer.get("sha256"))
        or pointer.get("selection_rule")
        != "read_pointer_once_then_verify_generation_manifest"
    ):
        raise BundleGenerationError("current JSON pointer contract mismatch")
    return pointer


def _resolve_current_json_pointer_payload(
    candidate: Path,
    payload: bytes,
    *,
    binding: DirectoryBinding,
) -> Path:
    pointer = _parse_current_json_pointer_payload(payload)
    relative, manifest_path = _resolve_under_root(
        candidate.parent,
        pointer.get("manifest_path"),
        label="current JSON pointer manifest_path",
    )
    relative_parts = PurePosixPath(relative).parts
    if len(relative_parts) < 2 or relative_parts[0] != pointer["generation_id"]:
        raise BundleGenerationError(
            "current JSON pointer manifest path does not match generation_id"
        )
    manifest_payload = _read_regular_payload(
        manifest_path,
        label="current generation manifest",
    )
    if hashlib.sha256(manifest_payload).hexdigest() != pointer["sha256"]:
        raise BundleGenerationError("current JSON pointer manifest sha256 mismatch")
    binding.assert_current_path_identity()
    return manifest_path


def _validate_current_json_pointer(pointer_path: Path) -> None:
    try:
        with bind_directory(pointer_path.parent) as binding:
            payload = _read_regular_payload(
                pointer_path,
                label="current JSON pointer",
                max_bytes=_MAX_CURRENT_POINTER_BYTES,
            )
            _resolve_current_json_pointer_payload(
                pointer_path,
                payload,
                binding=binding,
            )
    except (BundleGenerationError, OSError, ValueError) as exc:
        raise BundleGenerationError(f"current JSON pointer is invalid: {exc}") from exc


def _capture_pointer_state(
    generations_root: Path,
) -> tuple[_PointerState, _PointerSnapshot]:
    current = generations_root / CURRENT_LINK_NAME
    current_json = generations_root / CURRENT_POINTER_JSON_NAME
    current_stat = _optional_lstat(current)
    json_stat = _optional_lstat(current_json)

    if current_stat is not None and json_stat is not None:
        raise BundleGenerationError("conflicting current and current.json pointers exist")

    if current_stat is not None:
        if not stat.S_ISLNK(current_stat.st_mode):
            raise BundleGenerationError("current pointer has an unexpected filesystem type")
        target = _validate_current_symlink(generations_root, current)
        return (
            _PointerState("relative_symlink", current),
            _PointerSnapshot("relative_symlink", symlink_target=target),
        )

    if json_stat is not None:
        if not stat.S_ISREG(json_stat.st_mode):
            raise BundleGenerationError("current.json pointer has an unexpected filesystem type")
        with bind_directory(generations_root) as binding:
            payload = _read_regular_payload(
                current_json,
                label="current JSON pointer snapshot",
                max_bytes=_MAX_CURRENT_POINTER_BYTES,
            )
            _resolve_current_json_pointer_payload(
                current_json,
                payload,
                binding=binding,
            )
        return (
            _PointerState("json_pointer", current_json),
            _PointerSnapshot("json_pointer", json_payload=payload),
        )

    return _PointerState("new"), _PointerSnapshot("new")


def _inspect_pointer_state(generations_root: Path) -> _PointerState:
    state, _snapshot = _capture_pointer_state(generations_root)
    return state


def _snapshot_pointer_state(generations_root: Path) -> _PointerSnapshot:
    _state, snapshot = _capture_pointer_state(generations_root)
    return snapshot


def _pointer_generation_id_from_json_payload(payload: bytes) -> str:
    return _parse_current_json_pointer_payload(payload)["generation_id"]


def _assert_pointer_snapshot_unchanged(
    generations_root: Path,
    expected: _PointerSnapshot,
) -> None:
    _state, observed = _capture_pointer_state(generations_root)
    if observed != expected:
        raise BundleGenerationError(
            "current pointer changed after publication snapshot; refusing blind overwrite"
        )


def _read_symlink_for_rollback(path: Path, *, error: str) -> str:
    try:
        return read_symlink_target(path)
    except RootedFilesystemError as exc:
        raise BundleGenerationError(error) from exc


def _restore_relative_symlink_snapshot(
    generations_root: Path,
    current: Path,
    current_stat: os.stat_result | None,
    snapshot: _PointerSnapshot,
    *,
    attempted_generation_id: str,
) -> None:
    assert snapshot.symlink_target is not None
    if current_stat is None or not stat.S_ISLNK(current_stat.st_mode):
        raise BundleGenerationError("cannot roll back missing current symlink")
    target = _read_symlink_for_rollback(
        current, error="cannot read current symlink during rollback"
    )
    if target == snapshot.symlink_target:
        return
    if target != attempted_generation_id:
        raise BundleGenerationError(
            "current symlink was changed by another writer during rollback"
        )
    _write_current_symlink(generations_root, snapshot.symlink_target)


def _restore_json_pointer_snapshot(
    current_json: Path,
    json_stat: os.stat_result | None,
    snapshot: _PointerSnapshot,
    *,
    attempted_generation_id: str,
) -> None:
    assert snapshot.json_payload is not None
    if json_stat is None or not stat.S_ISREG(json_stat.st_mode):
        raise BundleGenerationError("cannot roll back missing current JSON pointer")
    current_payload = _read_regular_payload(
        current_json,
        label="current JSON pointer rollback",
        max_bytes=_MAX_CURRENT_POINTER_BYTES,
    )
    old_generation_id = _pointer_generation_id_from_json_payload(snapshot.json_payload)
    current_generation_id = _pointer_generation_id_from_json_payload(current_payload)
    if current_generation_id == old_generation_id:
        return
    if current_generation_id != attempted_generation_id:
        raise BundleGenerationError(
            "current JSON pointer was changed by another writer during rollback"
        )
    try:
        atomic_write_bytes(current_json, snapshot.json_payload)
    except RootedFilesystemError as exc:
        raise BundleGenerationError("failed to restore current JSON pointer") from exc
    _validate_current_json_pointer(current_json)


def _remove_new_symlink_pointer(
    current: Path,
    current_stat: os.stat_result,
    *,
    attempted_generation_id: str,
) -> None:
    if not stat.S_ISLNK(current_stat.st_mode):
        raise BundleGenerationError("new current pointer has an unexpected type")
    current_target = _read_symlink_for_rollback(
        current, error="cannot read new current symlink during rollback"
    )
    if current_target != attempted_generation_id:
        raise BundleGenerationError(
            "current symlink was changed by another writer during rollback"
        )
    try:
        remove_symlink(current)
    except RootedFilesystemError as exc:
        raise BundleGenerationError("failed to remove new current symlink") from exc


def _remove_new_json_pointer(
    current_json: Path,
    json_stat: os.stat_result,
    *,
    attempted_generation_id: str,
) -> None:
    if not stat.S_ISREG(json_stat.st_mode):
        raise BundleGenerationError("new current JSON pointer has an unexpected type")
    payload = _read_regular_payload(
        current_json,
        label="new current JSON pointer rollback",
        max_bytes=_MAX_CURRENT_POINTER_BYTES,
    )
    if _pointer_generation_id_from_json_payload(payload) != attempted_generation_id:
        raise BundleGenerationError(
            "current JSON pointer was changed by another writer during rollback"
        )
    try:
        remove_regular_file(current_json)
    except RootedFilesystemError as exc:
        raise BundleGenerationError("failed to remove new current JSON pointer") from exc


def _remove_new_pointer(
    current: Path,
    current_json: Path,
    current_stat: os.stat_result | None,
    json_stat: os.stat_result | None,
    *,
    attempted_generation_id: str,
) -> None:
    if current_stat is not None:
        _remove_new_symlink_pointer(
            current, current_stat, attempted_generation_id=attempted_generation_id
        )
        return
    if json_stat is not None:
        _remove_new_json_pointer(
            current_json, json_stat, attempted_generation_id=attempted_generation_id
        )


def _restore_pointer_snapshot(
    generations_root: Path,
    snapshot: _PointerSnapshot,
    *,
    attempted_generation_id: str,
) -> None:
    current = generations_root / CURRENT_LINK_NAME
    current_json = generations_root / CURRENT_POINTER_JSON_NAME
    current_stat = _optional_lstat(current)
    json_stat = _optional_lstat(current_json)
    if current_stat is not None and json_stat is not None:
        raise BundleGenerationError(
            "cannot roll back conflicting current and current.json pointers"
        )
    if snapshot.mode == "relative_symlink":
        _restore_relative_symlink_snapshot(
            generations_root,
            current,
            current_stat,
            snapshot,
            attempted_generation_id=attempted_generation_id,
        )
        return
    if snapshot.mode == "json_pointer":
        _restore_json_pointer_snapshot(
            current_json,
            json_stat,
            snapshot,
            attempted_generation_id=attempted_generation_id,
        )
        return
    _remove_new_pointer(
        current,
        current_json,
        current_stat,
        json_stat,
        attempted_generation_id=attempted_generation_id,
    )
    if _inspect_pointer_state(generations_root).mode != "new":
        raise BundleGenerationError(
            "new current pointer rollback did not restore an empty lane"
        )


def _write_current_symlink(generations_root: Path, generation_id: str) -> tuple[Path, str]:
    current = generations_root / CURRENT_LINK_NAME
    try:
        atomic_replace_symlink(current, generation_id)
    except NotImplementedError:
        raise
    except RootedFilesystemError as exc:
        raise BundleGenerationError(
            f"failed to publish descriptor-bound current symlink: {exc}"
        ) from exc
    return current, "relative_symlink"


def _write_current_json_pointer(
    generations_root: Path,
    *,
    generation_id: str,
    manifest_relative_path: str,
    manifest_sha256: str,
) -> tuple[Path, str]:
    pointer_path = generations_root / CURRENT_POINTER_JSON_NAME
    payload = {
        "kind": POINTER_KIND,
        "version": POINTER_VERSION,
        "generation_id": generation_id,
        "sha256": manifest_sha256,
        "manifest_path": f"{generation_id}/{manifest_relative_path}",
        "selection_rule": "read_pointer_once_then_verify_generation_manifest",
    }
    try:
        atomic_write_bytes(pointer_path, _json_bytes(payload))
    except RootedFilesystemError as exc:
        raise BundleGenerationError(f"failed to atomically write current JSON pointer: {exc}") from exc
    return pointer_path, "json_pointer"


def _publish_current_pointer(
    generations_root: Path,
    *,
    pointer_mode: str,
    generation_id: str,
    manifest_relative_path: str,
    manifest_sha256: str,
) -> tuple[Path, str]:
    if pointer_mode == "relative_symlink":
        try:
            return _write_current_symlink(generations_root, generation_id)
        except NotImplementedError as exc:
            raise BundleGenerationError(
                "current symlink mode is sticky; refusing JSON fallback after symlink failure"
            ) from exc
    if pointer_mode == "json_pointer":
        return _write_current_json_pointer(
            generations_root,
            generation_id=generation_id,
            manifest_relative_path=manifest_relative_path,
            manifest_sha256=manifest_sha256,
        )
    if pointer_mode != "new":
        raise BundleGenerationError(f"unsupported current pointer mode: {pointer_mode}")
    try:
        return _write_current_symlink(generations_root, generation_id)
    except NotImplementedError:
        return _write_current_json_pointer(
            generations_root,
            generation_id=generation_id,
            manifest_relative_path=manifest_relative_path,
            manifest_sha256=manifest_sha256,
        )


def _publish_bundle_generation_impl(
    bundle_manifest: str | Path,
    *,
    output_root: str | Path | None = None,
    extra_paths: Iterable[str | Path] = (),
) -> BundleGenerationResult:
    manifest_path = secure_absolute(bundle_manifest)
    root = secure_absolute(output_root or manifest_path.parent)
    try:
        manifest_path.relative_to(root)
    except ValueError as exc:
        raise BundleGenerationError("bundle manifest must live inside the bundle output root") from exc
    bundle_stem = bundle_stem_from_manifest(manifest_path)
    generations_root = generation_lane_root(root, bundle_stem)
    with bind_directory(root, create=True) as binding:
        manifest_relative = manifest_path.relative_to(root).as_posix()
        _manifest, files, manifest_sha256 = _collect_bundle_files(
            manifest_path,
            output_root=root,
            extra_paths=extra_paths,
        )
        generation_id = _generation_id(files, manifest_sha256=manifest_sha256)
        make_directories(generations_root)
        with bind_directory(generations_root) as lane_binding:
            with exclusive_file_lock(generations_root / PUBLISH_LOCK_NAME):
                lane_binding.assert_current_path_identity()
                pointer_snapshot = _snapshot_pointer_state(generations_root)
                generation_dir, reused = _install_generation(
                    generations_root, generation_id, files
                )
                pointer_publication_started = False
                pointer_published = False
                try:
                    with bind_directory(generation_dir) as generation_binding:
                        _verify_existing_generation(generation_dir, files)
                        generation_binding.assert_current_path_identity()
                        lane_binding.assert_current_path_identity()
                        binding.assert_current_path_identity()
                        _assert_pointer_snapshot_unchanged(
                            generations_root, pointer_snapshot
                        )
                        pointer_publication_started = True
                        pointer_path, pointer_kind = _publish_current_pointer(
                            generations_root,
                            pointer_mode=pointer_snapshot.mode,
                            generation_id=generation_id,
                            manifest_relative_path=manifest_relative,
                            manifest_sha256=manifest_sha256,
                        )
                        pointer_published = True
                        _verify_existing_generation(generation_dir, files)
                        generation_binding.assert_current_path_identity()
                        lane_binding.assert_current_path_identity()
                        binding.assert_current_path_identity()
                except (BundleGenerationError, RootedFilesystemError) as exc:
                    if pointer_publication_started:
                        try:
                            _restore_pointer_snapshot(
                                generations_root,
                                pointer_snapshot,
                                attempted_generation_id=generation_id,
                            )
                            lane_binding.assert_current_path_identity()
                            binding.assert_current_path_identity()
                        except (BundleGenerationError, RootedFilesystemError) as rollback_exc:
                            raise BundleGenerationError(
                                "current pointer publication failed and rollback also failed: "
                                f"{rollback_exc}"
                            ) from exc
                        if pointer_published:
                            raise BundleGenerationError(
                                "generation verification failed after current pointer switch; "
                                "the previous pointer state was restored"
                            ) from exc
                        raise
                    if isinstance(exc, BundleGenerationError):
                        raise
                    raise BundleGenerationError(
                        "generation changed while the current pointer was being published: "
                        f"{generation_dir}"
                    ) from exc
    if pointer_kind == "relative_symlink":
        selected_manifest_path = current_manifest_path(root, bundle_stem, manifest_relative)
    else:
        selected_manifest_path = generation_dir / Path(*PurePosixPath(manifest_relative).parts)
    resolved_manifest = generation_dir / Path(*PurePosixPath(manifest_relative).parts)
    # The complete tree, including this manifest hash, was already reverified
    # inside the lane lock where failure can still trigger pointer rollback.
    return BundleGenerationResult(
        output_root=root,
        bundle_stem=bundle_stem,
        generation_id=generation_id,
        generation_dir=generation_dir,
        current_pointer_path=pointer_path,
        current_manifest_path=selected_manifest_path,
        resolved_manifest_path=resolved_manifest,
        manifest_sha256=manifest_sha256,
        reused=reused,
        pointer_kind=pointer_kind,
        files={str(item.source_path): item.relative_path for item in files},
    )


def publish_bundle_generation(
    bundle_manifest: str | Path,
    *,
    output_root: str | Path | None = None,
    extra_paths: Iterable[str | Path] = (),
) -> BundleGenerationResult:
    try:
        return _publish_bundle_generation_impl(
            bundle_manifest,
            output_root=output_root,
            extra_paths=extra_paths,
        )
    except BundleGenerationError:
        raise
    except RootedFilesystemError as exc:
        raise BundleGenerationError(
            f"bundle generation filesystem guard failed: {exc}"
        ) from exc


def resolve_bundle_manifest_path(path: str | Path) -> Path:
    candidate = secure_absolute(path)
    if candidate.name != CURRENT_POINTER_JSON_NAME:
        return candidate.resolve(strict=True)
    with bind_directory(candidate.parent) as binding:
        payload = _read_regular_payload(
            candidate,
            label="current JSON pointer",
            max_bytes=_MAX_CURRENT_POINTER_BYTES,
        )
        return _resolve_current_json_pointer_payload(
            candidate,
            payload,
            binding=binding,
        )
