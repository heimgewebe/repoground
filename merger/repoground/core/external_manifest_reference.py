"""External manifest reference surface for RepoGround consumers."""

from __future__ import annotations

from .bundle_identity import is_bundle_manifest

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from .rooted_filesystem import (
    RootedFilesystemError,
    atomic_write_bytes,
    bind_directory,
    copy_verified_file,
    digest_regular_file,
    make_directories,
    make_temporary_directory,
    open_regular_file,
    path_exists,
    path_is_real_directory,
    read_regular_bytes,
    read_tree,
    remove_tree,
    rename_path,
    secure_absolute,
)

SUPPORTED_FAMILIES = {"repobrief", "lenskit"}
DOES_NOT_ESTABLISH = (
    "dump_freshness_truth",
    "claim_truth",
    "runtime_correctness",
    "semantic_correctness",
    "task_approval",
    "dump_generation_permission",
    "repo_understood",
    "merge_readiness",
    "distributed_consensus",
    "cross_host_transactionality",
    "remote_freshness",
    "kernel_bug_resistance",
    "network_filesystem_equivalence",
    "privilege_boundary_isolation",
    "untested_platform_security",
)


class ExternalManifestReferenceError(ValueError):
    """Raised when an external manifest reference cannot be built."""


def _relative_path(target: Path, base_dir: Path) -> str:
    return Path(
        os.path.relpath(secure_absolute(target), secure_absolute(base_dir))
    ).as_posix()


def _registry_segment(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "/" in value
        or "\\" in value
    ):
        raise ExternalManifestReferenceError(
            f"{label} must be a non-empty registry segment"
        )
    if value in {".", ".."}:
        raise ExternalManifestReferenceError(f"{label} must not be a traversal segment")
    return value


def _open_regular_file(path: Path, label: str) -> tuple[int, int]:
    try:
        return open_regular_file(path)
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"{label} must be an existing regular file: {path}"
        ) from exc


def _digest_regular_file(path: Path, label: str) -> tuple[int, str]:
    try:
        return digest_regular_file(path)
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"{label} must be an existing stable regular file: {path}"
        ) from exc


def _read_json_object_with_integrity(
    path: Path,
) -> tuple[dict[str, Any], int, str]:
    try:
        payload = read_regular_bytes(path)
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"bundle manifest must be an existing regular file with stable identity: {path}"
        ) from exc
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalManifestReferenceError(
            f"bundle manifest is not valid UTF-8 JSON: {path}"
        ) from exc
    if not isinstance(data, dict):
        raise ExternalManifestReferenceError("bundle manifest must be a JSON object")
    return data, len(payload), hashlib.sha256(payload).hexdigest()


def _bundle_member(bundle_dir: Path, raw_path: str, label: str) -> tuple[Path, str]:
    if not isinstance(raw_path, str) or not raw_path or raw_path.strip() != raw_path:
        raise ExternalManifestReferenceError(
            f"{label} must be a non-empty relative path"
        )
    relative = Path(raw_path)
    if (
        relative.is_absolute()
        or "\\" in raw_path
        or any(part in {".", ".."} for part in relative.parts)
    ):
        raise ExternalManifestReferenceError(
            f"{label} must stay inside the bundle directory"
        )
    trusted_bundle_dir = secure_absolute(bundle_dir)
    resolved = secure_absolute(trusted_bundle_dir / relative)
    try:
        normalized = resolved.relative_to(trusted_bundle_dir)
    except ValueError as exc:
        raise ExternalManifestReferenceError(
            f"{label} must stay inside the bundle directory"
        ) from exc
    if not path_exists(resolved):
        raise ExternalManifestReferenceError(f"{label} does not exist: {raw_path}")
    fd, _ = _open_regular_file(resolved, label)
    os.close(fd)
    return resolved, normalized.as_posix()


def _artifact_rows(
    bundle_manifest_path: Path,
    bundle_manifest: dict[str, Any],
    output_base: Path,
) -> list[dict[str, Any]]:
    artifacts = bundle_manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ExternalManifestReferenceError("bundle manifest artifacts must be a list")
    rows: list[dict[str, Any]] = []
    bundle_dir = secure_absolute(bundle_manifest_path.parent)
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        role = artifact.get("role")
        raw_path = artifact.get("path")
        sha256 = artifact.get("sha256")
        if not isinstance(role, str) or not isinstance(raw_path, str):
            continue
        artifact_path, _ = _bundle_member(
            bundle_dir, raw_path, f"bundle artifact {role}"
        )
        row: dict[str, Any] = {
            "role": role,
            "path": _relative_path(artifact_path, output_base),
            "sha256": sha256 if isinstance(sha256, str) else None,
        }
        if isinstance(artifact.get("bytes"), int):
            row["bytes"] = artifact["bytes"]
        if isinstance(artifact.get("content_type"), str):
            row["contentType"] = artifact["content_type"]
        rows.append(row)
    return rows


def _linked_sidecar_rows(
    bundle_manifest_path: Path,
    bundle_manifest: dict[str, Any],
    output_base: Path,
) -> list[dict[str, Any]]:
    links = bundle_manifest.get("links")
    if not isinstance(links, dict):
        return []
    linked_roles = {
        "post_emit_health_path": "post_emit_health",
        "bundle_surface_validation_path": "bundle_surface_validation",
        "surface_validation_path": "bundle_surface_validation",
    }
    rows: list[dict[str, Any]] = []
    bundle_dir = secure_absolute(bundle_manifest_path.parent)
    seen_paths: set[str] = set()
    for link_key, role in linked_roles.items():
        raw_path = links.get(link_key)
        if not isinstance(raw_path, str) or not raw_path:
            continue
        linked_path, normalized = _bundle_member(
            bundle_dir, raw_path, f"bundle manifest link {link_key}"
        )
        if normalized in seen_paths:
            continue
        seen_paths.add(normalized)
        linked_bytes, linked_sha256 = _digest_regular_file(
            linked_path, f"bundle manifest link {link_key}"
        )
        rows.append(
            {
                "role": role,
                "path": _relative_path(linked_path, output_base),
                "sha256": linked_sha256,
                "bytes": linked_bytes,
                "contentType": "application/json",
            }
        )
    return rows


def _combined_artifact_rows(
    bundle_manifest_path: Path,
    bundle_manifest: dict[str, Any],
    output_base: Path,
) -> list[dict[str, Any]]:
    rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    rows = _artifact_rows(bundle_manifest_path, bundle_manifest, output_base)
    rows += _linked_sidecar_rows(bundle_manifest_path, bundle_manifest, output_base)
    for row in rows:
        rows_by_key[(row["role"], row["path"])] = row
    return sorted(rows_by_key.values(), key=lambda item: (item["role"], item["path"]))


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value == value.lower()
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _verify_file(
    path: Path, *, expected_sha256: str, expected_bytes: int, label: str
) -> None:
    observed_bytes, observed_sha256 = _digest_regular_file(path, label)
    if observed_bytes != expected_bytes:
        raise ExternalManifestReferenceError(
            f"{label} byte count mismatch: expected {expected_bytes}, observed {observed_bytes}"
        )
    if observed_sha256 != expected_sha256:
        raise ExternalManifestReferenceError(
            f"{label} sha256 mismatch: expected {expected_sha256}, observed {observed_sha256}"
        )


def _copy_verified_file(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str,
    expected_bytes: int,
    label: str,
) -> None:
    try:
        copy_verified_file(
            source,
            destination,
            expected_sha256=expected_sha256,
            expected_bytes=expected_bytes,
        )
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"{label} could not be copied through trusted directory descriptors: {exc}"
        ) from exc


def _require_path_inside_root(path: Path, root: Path, label: str) -> None:
    try:
        secure_absolute(path).relative_to(secure_absolute(root))
    except ValueError as exc:
        raise ExternalManifestReferenceError(
            f"{label} must stay inside publication_root"
        ) from exc


def _read_materialization_manifest(
    source_manifest: Path,
) -> tuple[dict[str, Any], int, str]:
    bundle, manifest_bytes, manifest_sha256 = _read_json_object_with_integrity(
        source_manifest
    )
    if not is_bundle_manifest(bundle):
        raise ExternalManifestReferenceError(
            "bundle manifest identity must be RepoGround v2 or documented legacy v1"
        )
    return bundle, manifest_bytes, manifest_sha256


def _declared_materialization_rows(
    source_manifest: Path,
    bundle: dict[str, Any],
) -> list[dict[str, Any]]:
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, list):
        raise ExternalManifestReferenceError("bundle manifest artifacts must be a list")
    source_dir = secure_absolute(source_manifest.parent)
    rows: list[dict[str, Any]] = []
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            raise ExternalManifestReferenceError(
                f"bundle artifact at index {index} must be a JSON object"
            )
        role = artifact.get("role")
        raw_path = artifact.get("path")
        expected_sha256 = artifact.get("sha256")
        expected_bytes = artifact.get("bytes")
        if not isinstance(role, str) or not role:
            raise ExternalManifestReferenceError(
                f"bundle artifact at index {index} must declare a non-empty role"
            )
        source_path, normalized = _bundle_member(
            source_dir,
            raw_path,
            f"bundle artifact {role}",
        )
        if (
            not _valid_sha256(expected_sha256)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
        ):
            raise ExternalManifestReferenceError(
                f"bundle artifact {role} must declare valid sha256 and bytes for materialization"
            )
        rows.append(
            {
                "role": role,
                "path": normalized,
                "source": source_path,
                "sha256": expected_sha256,
                "bytes": expected_bytes,
            }
        )
    for row in _linked_sidecar_rows(source_manifest, bundle, source_dir):
        source_path, normalized = _bundle_member(
            source_dir,
            row["path"],
            f"bundle artifact {row['role']}",
        )
        rows.append(
            {
                "role": row["role"],
                "path": normalized,
                "source": source_path,
                "sha256": row["sha256"],
                "bytes": row["bytes"],
            }
        )
    return rows


def _materialization_members(
    source_manifest: Path,
    bundle: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    members: dict[str, dict[str, Any]] = {}
    for row in _declared_materialization_rows(source_manifest, bundle):
        normalized = row["path"]
        previous = members.get(normalized)
        if previous is not None and (
            previous["sha256"] != row["sha256"] or previous["bytes"] != row["bytes"]
        ):
            raise ExternalManifestReferenceError(
                f"bundle artifact path has conflicting integrity declarations: {normalized}"
            )
        members[normalized] = {
            "source": row["source"],
            "sha256": row["sha256"],
            "bytes": row["bytes"],
        }
    if source_manifest.name in members:
        raise ExternalManifestReferenceError(
            "bundle artifact path must not collide with the bundle manifest filename"
        )
    return members


def _expected_materialized_entries(
    localized_manifest: Path,
    members: dict[str, dict[str, Any]],
) -> tuple[set[str], set[str]]:
    expected_files = {localized_manifest.name, *members.keys()}
    expected_directories: set[str] = set()
    for relative_path in expected_files:
        parent = Path(relative_path).parent
        while parent != Path("."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    return expected_files, expected_directories


def _observed_materialized_entries(localized_dir: Path) -> tuple[set[str], set[str]]:
    try:
        files, directories = read_tree(localized_dir)
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            "localized bundle tree must contain only regular files and directories: "
            f"{localized_dir}: {exc}"
        ) from exc
    return set(files), directories


def _verify_materialized_tree(
    localized_dir: Path,
    localized_manifest: Path,
    *,
    manifest_sha256: str,
    manifest_bytes: int,
    members: dict[str, dict[str, Any]],
) -> None:
    expected_files, expected_directories = _expected_materialized_entries(
        localized_manifest,
        members,
    )
    actual_files, actual_directories = _observed_materialized_entries(localized_dir)
    if actual_files != expected_files or actual_directories != expected_directories:
        missing = sorted(
            (expected_files - actual_files)
            | (expected_directories - actual_directories)
        )
        unexpected = sorted(
            (actual_files - expected_files)
            | (actual_directories - expected_directories)
        )
        raise ExternalManifestReferenceError(
            "localized bundle tree entries mismatch: "
            f"missing={missing}, unexpected={unexpected}"
        )

    _verify_file(
        localized_manifest,
        expected_sha256=manifest_sha256,
        expected_bytes=manifest_bytes,
        label="localized bundle manifest",
    )
    for relative_path, member in members.items():
        _verify_file(
            localized_dir / relative_path,
            expected_sha256=member["sha256"],
            expected_bytes=member["bytes"],
            label=f"localized bundle artifact {relative_path}",
        )


def _build_materialization_stage(
    source_manifest: Path,
    localized_dir: Path,
    *,
    publication_root: Path,
    manifest_sha256: str,
    manifest_bytes: int,
    members: dict[str, dict[str, Any]],
) -> Path:
    try:
        make_directories(localized_dir.parent)
        _require_path_inside_root(
            localized_dir.parent, publication_root, "localized bundle parent"
        )
        stage = make_temporary_directory(
            localized_dir.parent,
            prefix=manifest_sha256,
        )
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"localized bundle stage cannot be prepared safely: {exc}"
        ) from exc
    try:
        for relative_path, member in sorted(members.items()):
            _copy_verified_file(
                member["source"],
                stage / relative_path,
                expected_sha256=member["sha256"],
                expected_bytes=member["bytes"],
                label=f"bundle artifact {relative_path}",
            )
        _copy_verified_file(
            source_manifest,
            stage / source_manifest.name,
            expected_sha256=manifest_sha256,
            expected_bytes=manifest_bytes,
            label="bundle manifest",
        )
    except Exception:
        try:
            remove_tree(stage)
        except RootedFilesystemError:
            pass
        raise
    return stage


def _install_materialized_tree(
    source_manifest: Path,
    localized_dir: Path,
    localized_manifest: Path,
    *,
    publication_root: Path,
    manifest_sha256: str,
    manifest_bytes: int,
    members: dict[str, dict[str, Any]],
) -> bool:
    if path_exists(localized_dir):
        if not path_is_real_directory(localized_dir):
            raise ExternalManifestReferenceError(
                f"localized bundle path is not a directory: {localized_dir}"
            )
        _verify_materialized_tree(
            localized_dir,
            localized_manifest,
            manifest_sha256=manifest_sha256,
            manifest_bytes=manifest_bytes,
            members=members,
        )
        return True

    stage = _build_materialization_stage(
        source_manifest,
        localized_dir,
        publication_root=publication_root,
        manifest_sha256=manifest_sha256,
        manifest_bytes=manifest_bytes,
        members=members,
    )
    try:
        try:
            rename_path(stage, localized_dir)
        except RootedFilesystemError:
            if not path_is_real_directory(localized_dir):
                raise
            _verify_materialized_tree(
                localized_dir,
                localized_manifest,
                manifest_sha256=manifest_sha256,
                manifest_bytes=manifest_bytes,
                members=members,
            )
            return True
        _verify_materialized_tree(
            localized_dir,
            localized_manifest,
            manifest_sha256=manifest_sha256,
            manifest_bytes=manifest_bytes,
            members=members,
        )
        return False
    finally:
        try:
            remove_tree(stage)
        except RootedFilesystemError:
            pass


def _materialize_external_bundle_bound(
    source_manifest: Path,
    root: Path,
    *,
    repository: str,
    ref: str,
) -> dict[str, Any]:
    bundle, manifest_bytes, manifest_sha256 = _read_materialization_manifest(
        source_manifest
    )

    localized_dir = root / "external" / "_bundles" / repository / ref / manifest_sha256
    localized_manifest = localized_dir / source_manifest.name
    _require_path_inside_root(localized_dir, root, "localized bundle directory")

    members = _materialization_members(source_manifest, bundle)
    reused = _install_materialized_tree(
        source_manifest,
        localized_dir,
        localized_manifest,
        publication_root=root,
        manifest_sha256=manifest_sha256,
        manifest_bytes=manifest_bytes,
        members=members,
    )

    return {
        "kind": "repobrief.external_bundle_materialization",
        "version": "1",
        "sourceBundleManifest": str(source_manifest),
        "sourceManifestSha256": manifest_sha256,
        "sourceManifestBytes": manifest_bytes,
        "localizedRoot": str(localized_dir),
        "bundleManifest": str(localized_manifest),
        "artifactCount": len(members),
        "reused": reused,
        "doesNotEstablish": list(DOES_NOT_ESTABLISH),
    }


def materialize_external_bundle(
    bundle_manifest_path: str | Path,
    publication_root: str | Path,
    *,
    repository: str,
    ref: str,
) -> dict[str, Any]:
    """Copy one bundle through source- and publication-root directory bindings."""
    repository = _registry_segment(repository, "repository")
    ref = _registry_segment(ref, "ref")
    source_manifest = secure_absolute(bundle_manifest_path)
    root = secure_absolute(publication_root)
    try:
        with bind_directory(root, create=True) as root_binding:
            with bind_directory(source_manifest.parent) as source_binding:
                result = _materialize_external_bundle_bound(
                    source_manifest,
                    root,
                    repository=repository,
                    ref=ref,
                )
                source_binding.assert_current_path_identity()
                root_binding.assert_current_path_identity()
                return result
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"external bundle materialization lost a trusted directory identity: {exc}"
        ) from exc


def _require_inside_publication_root(
    bundle_manifest_path: Path, publication_root: Path | None
) -> None:
    if publication_root is None:
        return
    root = secure_absolute(publication_root)
    try:
        bundle_manifest_path.relative_to(root)
    except ValueError as exc:
        raise ExternalManifestReferenceError(
            "bundle manifest must be inside publication_root for portable external publication"
        ) from exc


def _build_external_manifest_reference_bound(
    manifest_path: Path,
    *,
    family: str,
    repository: str,
    ref: str,
    output_base: Path,
) -> dict[str, Any]:
    bundle, manifest_bytes, manifest_sha256 = _read_json_object_with_integrity(
        manifest_path
    )
    if not is_bundle_manifest(bundle):
        raise ExternalManifestReferenceError(
            "bundle manifest identity must be RepoGround v2 or documented legacy v1"
        )
    created_at = bundle.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        raise ExternalManifestReferenceError(
            "bundle manifest created_at must be present"
        )
    snapshot_provenance = bundle.get("snapshot_provenance")
    return {
        "kind": f"{family}_bundle_manifest",
        "version": "1",
        "artifactFamily": family,
        "repository": repository,
        "ref": ref,
        "generatedAt": created_at,
        "freshnessBasis": "bundle_manifest.created_at",
        "bundleManifest": {
            "kind": bundle.get("kind"),
            "version": bundle.get("version"),
            "path": _relative_path(manifest_path, output_base),
            "runId": bundle.get("run_id"),
            "createdAt": created_at,
            "sha256": manifest_sha256,
            "bytes": manifest_bytes,
        },
        "snapshotProvenance": snapshot_provenance
        if isinstance(snapshot_provenance, dict)
        else None,
        "artifacts": _combined_artifact_rows(manifest_path, bundle, output_base),
        "doesNotEstablish": list(DOES_NOT_ESTABLISH),
    }


def build_external_manifest_reference(
    bundle_manifest_path: str | Path,
    *,
    repository: str,
    ref: str,
    artifact_family: str = "repobrief",
    output_path: str | Path | None = None,
    publication_root: str | Path | None = None,
) -> dict[str, Any]:
    """Build a bounded reference while holding one source-directory identity."""
    family = artifact_family.strip().lower() if isinstance(artifact_family, str) else ""
    if family not in SUPPORTED_FAMILIES:
        raise ExternalManifestReferenceError(
            "artifact_family must be repobrief or lenskit"
        )
    repository = _registry_segment(repository, "repository")
    ref = _registry_segment(ref, "ref")
    manifest_path = secure_absolute(bundle_manifest_path)
    _require_inside_publication_root(
        manifest_path,
        Path(publication_root) if publication_root is not None else None,
    )
    output_base = (
        secure_absolute(output_path).parent
        if output_path is not None
        else manifest_path.parent
    )
    try:
        with bind_directory(manifest_path.parent) as source_binding:
            result = _build_external_manifest_reference_bound(
                manifest_path,
                family=family,
                repository=repository,
                ref=ref,
                output_base=output_base,
            )
            source_binding.assert_current_path_identity()
            return result
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"external manifest build lost its source-directory identity: {manifest_path.parent}: {exc}"
        ) from exc


def publication_generation_pointer_path(
    publication_root: str | Path,
    *,
    repository: str,
    ref: str,
) -> Path:
    """Return the authoritative generation pointer while preserving the public API."""
    from .external_manifest_generation import (
        publication_generation_pointer_path as impl,
    )

    return impl(
        publication_root,
        repository=repository,
        ref=ref,
    )


def read_external_manifest_publication(
    publication_root: str | Path,
    *,
    repository: str,
    ref: str,
) -> dict[str, Any]:
    """Read one verified committed generation through the public API."""
    from .external_manifest_generation import read_external_manifest_publication as impl

    return impl(
        publication_root,
        repository=repository,
        ref=ref,
    )


def recover_external_manifest_publication(
    publication_root: str | Path,
    *,
    repository: str,
    ref: str,
) -> dict[str, Any]:
    """Rebuild compatibility projections from the committed generation."""
    from .external_manifest_generation import (
        recover_external_manifest_publication as impl,
    )

    return impl(
        publication_root,
        repository=repository,
        ref=ref,
    )


def publication_manifest_path(
    publication_root: str | Path,
    *,
    repository: str,
    ref: str,
    artifact_family: str,
) -> Path:
    """Return the stable external manifest publication path for a registry segment."""
    family = artifact_family.strip().lower() if isinstance(artifact_family, str) else ""
    if family not in SUPPORTED_FAMILIES:
        raise ExternalManifestReferenceError(
            "artifact_family must be repobrief or lenskit"
        )
    repository = _registry_segment(repository, "repository")
    ref = _registry_segment(ref, "ref")
    return (
        secure_absolute(publication_root)
        / "external"
        / family
        / repository
        / ref
        / "manifest.json"
    )


def _normalized_artifact_families(
    artifact_families: Iterable[str] | None,
) -> list[str]:
    requested = (
        sorted(SUPPORTED_FAMILIES) if artifact_families is None else artifact_families
    )
    families: list[str] = []
    for raw_family in requested:
        family = raw_family.strip().lower() if isinstance(raw_family, str) else ""
        if family not in SUPPORTED_FAMILIES:
            raise ExternalManifestReferenceError(
                "artifact family must be repobrief or lenskit"
            )
        if family not in families:
            families.append(family)
    if not families:
        raise ExternalManifestReferenceError("at least one artifact family is required")
    return families


def publish_external_manifest_references(
    bundle_manifest_path: str | Path,
    publication_root: str | Path,
    *,
    repository: str,
    ref: str,
    artifact_families: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Publish one complete generation while preserving the public API."""
    from .external_manifest_generation import (
        publish_external_manifest_references as impl,
    )

    return impl(
        bundle_manifest_path,
        publication_root,
        repository=repository,
        ref=ref,
        artifact_families=artifact_families,
    )


def write_external_manifest_reference(
    bundle_manifest_path: str | Path,
    output_path: str | Path,
    *,
    repository: str,
    ref: str,
    artifact_family: str = "repobrief",
    publication_root: str | Path | None = None,
) -> dict[str, Any]:
    """Write one reference through trusted source and output directory identities."""
    out = secure_absolute(output_path)
    root = (
        secure_absolute(publication_root)
        if publication_root is not None
        else out.parent
    )
    try:
        with bind_directory(root, create=True) as root_binding:
            _require_path_inside_root(out, root, "external manifest output")
            data = build_external_manifest_reference(
                bundle_manifest_path,
                repository=repository,
                ref=ref,
                artifact_family=artifact_family,
                output_path=out,
                publication_root=publication_root,
            )
            atomic_write_bytes(
                out, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")
            )
            root_binding.assert_current_path_identity()
            return data
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"external manifest write lost a trusted directory identity: {out}: {exc}"
        ) from exc
