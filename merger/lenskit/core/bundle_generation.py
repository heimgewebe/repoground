"""Immutable RepoBrief bundle generations and atomic current selection."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .rooted_filesystem import (
    RootedFilesystemError,
    atomic_write_bytes,
    bind_directory,
    copy_verified_file,
    fsync_directory,
    lstat_path,
    make_directories,
    make_temporary_directory,
    path_exists,
    path_is_real_directory,
    read_regular_bytes,
    read_tree,
    remove_tree,
    rename_path_no_replace,
    secure_absolute,
)


class BundleGenerationError(RuntimeError):
    """Raised when a bundle generation cannot be published coherently."""


GENERATION_ROOT_NAME = ".repobrief-generations"
CURRENT_LINK_NAME = "current"
CURRENT_POINTER_JSON_NAME = "current.json"
POINTER_KIND = "repobrief.bundle_generation_pointer"
POINTER_VERSION = "1"

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
    payload: bytes
    sha256: str

    @property
    def bytes(self) -> int:
        return len(self.payload)


@dataclass(frozen=True, slots=True)
class _PointerState:
    mode: str
    path: Path | None = None


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


def _read_regular_payload(path: Path, *, label: str) -> bytes:
    try:
        return read_regular_bytes(path)
    except RootedFilesystemError as exc:
        raise BundleGenerationError(f"{label} must be a regular file inside the bundle root: {path}") from exc


def _add_file(
    files: dict[str, _BundleFile],
    *,
    relative_path: str,
    source_path: Path,
    payload: bytes,
    expected_bytes: Any = None,
    expected_sha256: Any = None,
    label: str,
) -> None:
    sha256 = hashlib.sha256(payload).hexdigest()
    if (
        isinstance(expected_bytes, int)
        and not isinstance(expected_bytes, bool)
        and expected_bytes != len(payload)
    ):
        raise BundleGenerationError(f"{label} byte count does not match the manifest")
    if _is_sha256(expected_sha256) and expected_sha256 != sha256:
        raise BundleGenerationError(f"{label} sha256 does not match the manifest")
    existing = files.get(relative_path)
    if existing is not None:
        if existing.sha256 != sha256 or existing.bytes != len(payload):
            raise BundleGenerationError(f"bundle file path is declared with conflicting content: {relative_path}")
        return
    files[relative_path] = _BundleFile(
        relative_path=relative_path,
        source_path=source_path,
        payload=payload,
        sha256=sha256,
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
        payload = _read_regular_payload(source, label=label)
        _add_file(
            files,
            relative_path=relative,
            source_path=source,
            payload=payload,
            expected_bytes=row.get("bytes"),
            expected_sha256=row.get("sha256"),
            label=label,
        )


def _collect_manifest_links(
    manifest: dict[str, Any],
    *,
    output_root: Path,
    files: dict[str, _BundleFile],
) -> None:
    links = manifest.get("links")
    if not isinstance(links, dict):
        return
    for key in _SIDECAR_LINK_KEYS:
        if not links.get(key):
            continue
        label = f"links.{key}"
        relative, source = _resolve_under_root(output_root, links[key], label=label)
        payload = _read_regular_payload(source, label=label)
        _add_file(
            files,
            relative_path=relative,
            source_path=source,
            payload=payload,
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
        payload = _read_regular_payload(source, label="extra file")
        _add_file(
            files,
            relative_path=relative,
            source_path=source,
            payload=payload,
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
    _collect_manifest_links(manifest, output_root=output_root, files=files)
    _collect_extra_paths(extra_paths, output_root=output_root, files=files)
    manifest_relative = manifest_path.relative_to(output_root).as_posix()
    _add_file(
        files,
        relative_path=manifest_relative,
        source_path=manifest_path,
        payload=manifest_payload,
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


def _expected_files(files: list[_BundleFile]) -> dict[str, bytes]:
    return {item.relative_path: item.payload for item in files}


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
        observed_files, observed_directories = read_tree(generation_dir)
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


def _validate_current_symlink(generations_root: Path, current: Path) -> None:
    try:
        target = os.readlink(current)
    except OSError as exc:
        raise BundleGenerationError(f"current symlink cannot be read safely: {exc}") from exc
    if not _is_sha256(target) or "/" in target or "\\" in target:
        raise BundleGenerationError("current symlink target is not a valid generation id")
    if not path_is_real_directory(generations_root / target):
        raise BundleGenerationError("current symlink target does not name a valid generation")


def _validate_current_json_pointer(pointer_path: Path) -> None:
    try:
        resolve_bundle_manifest_path(pointer_path)
    except (BundleGenerationError, OSError, ValueError) as exc:
        raise BundleGenerationError(f"current JSON pointer is invalid: {exc}") from exc


def _inspect_pointer_state(generations_root: Path) -> _PointerState:
    current = generations_root / CURRENT_LINK_NAME
    current_json = generations_root / CURRENT_POINTER_JSON_NAME
    current_stat = _optional_lstat(current)
    json_stat = _optional_lstat(current_json)

    if current_stat is not None and json_stat is not None:
        raise BundleGenerationError("conflicting current and current.json pointers exist")

    if current_stat is not None:
        if not stat.S_ISLNK(current_stat.st_mode):
            raise BundleGenerationError("current pointer has an unexpected filesystem type")
        _validate_current_symlink(generations_root, current)
        return _PointerState("relative_symlink", current)

    if json_stat is not None:
        if not stat.S_ISREG(json_stat.st_mode):
            raise BundleGenerationError("current.json pointer has an unexpected filesystem type")
        _validate_current_json_pointer(current_json)
        return _PointerState("json_pointer", current_json)

    return _PointerState("new")


def _write_current_symlink(generations_root: Path, generation_id: str) -> tuple[Path, str]:
    current = generations_root / CURRENT_LINK_NAME
    temporary = generations_root / f".{CURRENT_LINK_NAME}.{secrets.token_hex(12)}.tmp"
    try:
        os.symlink(generation_id, temporary)
    except OSError as exc:
        if exc.errno in {errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS, errno.EACCES}:
            raise NotImplementedError(str(exc)) from exc
        raise BundleGenerationError(f"failed to create temporary current symlink: {exc}") from exc
    try:
        os.replace(temporary, current)
        fsync_directory(generations_root)
        if os.readlink(current) != generation_id:
            raise BundleGenerationError("current symlink readback selected the wrong generation")
    except OSError as exc:
        raise BundleGenerationError(f"failed to atomically replace current symlink: {exc}") from exc
    except RootedFilesystemError as exc:
        raise BundleGenerationError(f"failed to fsync current symlink parent: {exc}") from exc
    finally:
        try:
            if os.path.lexists(temporary):
                temporary.unlink()
        except OSError:
            pass
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
    generation_id: str,
    manifest_relative_path: str,
    manifest_sha256: str,
) -> tuple[Path, str]:
    state = _inspect_pointer_state(generations_root)
    if state.mode == "relative_symlink":
        try:
            return _write_current_symlink(generations_root, generation_id)
        except NotImplementedError as exc:
            raise BundleGenerationError(
                "current symlink mode is sticky; refusing JSON fallback after symlink failure"
            ) from exc
    if state.mode == "json_pointer":
        return _write_current_json_pointer(
            generations_root,
            generation_id=generation_id,
            manifest_relative_path=manifest_relative_path,
            manifest_sha256=manifest_sha256,
        )
    try:
        return _write_current_symlink(generations_root, generation_id)
    except NotImplementedError:
        return _write_current_json_pointer(
            generations_root,
            generation_id=generation_id,
            manifest_relative_path=manifest_relative_path,
            manifest_sha256=manifest_sha256,
        )


def publish_bundle_generation(
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
        generation_dir, reused = _install_generation(generations_root, generation_id, files)
        binding.assert_current_path_identity()
        pointer_path, pointer_kind = _publish_current_pointer(
            generations_root,
            generation_id=generation_id,
            manifest_relative_path=manifest_relative,
            manifest_sha256=manifest_sha256,
        )
        binding.assert_current_path_identity()
    if pointer_kind == "relative_symlink":
        selected_manifest_path = current_manifest_path(root, bundle_stem, manifest_relative)
    else:
        selected_manifest_path = generation_dir / Path(*PurePosixPath(manifest_relative).parts)
    resolved_manifest = generation_dir / Path(*PurePosixPath(manifest_relative).parts)
    resolved_payload = _read_regular_payload(resolved_manifest, label="published bundle manifest")
    if hashlib.sha256(resolved_payload).hexdigest() != manifest_sha256:
        raise BundleGenerationError("published generation manifest readback hash mismatch")
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


def resolve_bundle_manifest_path(path: str | Path) -> Path:
    candidate = secure_absolute(path)
    if candidate.name != CURRENT_POINTER_JSON_NAME:
        return candidate.resolve(strict=True)
    with bind_directory(candidate.parent) as binding:
        payload = _read_regular_payload(candidate, label="current JSON pointer")
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
        relative, manifest_path = _resolve_under_root(
            candidate.parent,
            pointer.get("manifest_path"),
            label="current JSON pointer manifest_path",
        )
        expected_prefix = f"{pointer['generation_id']}/"
        if not relative.startswith(expected_prefix):
            raise BundleGenerationError(
                "current JSON pointer manifest path does not match generation_id"
            )
        manifest_payload = _read_regular_payload(manifest_path, label="current generation manifest")
        if hashlib.sha256(manifest_payload).hexdigest() != pointer["sha256"]:
            raise BundleGenerationError("current JSON pointer manifest sha256 mismatch")
        binding.assert_current_path_identity()
        return manifest_path
