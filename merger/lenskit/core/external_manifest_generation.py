"""Generation-coherent external RepoBrief/Lenskit publication protocol."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from .rooted_filesystem import (
    RootedFilesystemError,
    atomic_write_bytes,
    bind_directory,
    exclusive_file_lock,
    exclusive_write_bytes,
    fsync_directory,
    make_directories,
    make_temporary_directory,
    path_exists,
    read_regular_bytes,
    read_tree,
    remove_tree,
    rename_path,
    secure_absolute,
)

from .external_manifest_reference import (
    BUNDLE_KIND,
    DOES_NOT_ESTABLISH,
    SUPPORTED_FAMILIES,
    ExternalManifestReferenceError,
    _digest_regular_file,
    _normalized_artifact_families,
    _registry_segment,
    _relative_path,
    _require_path_inside_root,
    build_external_manifest_reference,
    materialize_external_bundle,
    publication_manifest_path,
)

GENERATION_KIND = "repobrief.external_manifest_generation"
GENERATION_POINTER_KIND = "repobrief.external_manifest_generation_pointer"
GENERATION_SELECTION_KIND = "repobrief.external_manifest_generation_selection"
GENERATION_VERSION = "1"


def _json_bytes(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_regular_bytes(path: Path, label: str) -> bytes:
    try:
        return read_regular_bytes(path)
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"{label} must be an existing regular file with stable identity: {path}"
        ) from exc


def _read_json_regular_file(
    path: Path,
    label: str,
) -> tuple[dict[str, Any], int, str]:
    payload = _read_regular_bytes(path, label)
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalManifestReferenceError(
            f"{label} must be valid UTF-8 JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise ExternalManifestReferenceError(f"{label} must be a JSON object")
    return parsed, len(payload), hashlib.sha256(payload).hexdigest()


def _fsync_directory(path: Path) -> None:
    try:
        fsync_directory(path)
    except RootedFilesystemError as exc:
        raise OSError(str(exc)) from exc


def _atomic_write_json(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    payload = _json_bytes(data)
    try:
        result = atomic_write_bytes(path, payload)
        if result["durability"] == "durable":
            try:
                _fsync_directory(path.parent)
            except OSError as exc:
                if _read_regular_bytes(path, "replaced JSON file") == payload:
                    return {
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "durability": "uncertain_after_directory_fsync",
                        "error": str(exc),
                    }
                raise
        return result
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"atomic JSON write failed through trusted descriptors: {path}: {exc}"
        ) from exc


def _write_generation_manifest_file(path: Path, data: dict[str, Any]) -> None:
    try:
        exclusive_write_bytes(path, _json_bytes(data))
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"generation manifest write failed through trusted descriptors: {path}: {exc}"
        ) from exc


def _write_generation_descriptor(path: Path, data: dict[str, Any]) -> None:
    _write_generation_manifest_file(path, data)


def _write_generation_pointer(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    return _atomic_write_json(path, data)


def _write_compatibility_manifest(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    return _atomic_write_json(path, data)


def publication_generation_pointer_path(
    publication_root: str | Path,
    *,
    repository: str,
    ref: str,
) -> Path:
    """Return the one authoritative generation-selection pointer for a lane."""
    repository = _registry_segment(repository, "repository")
    ref = _registry_segment(ref, "ref")
    return (
        secure_absolute(publication_root)
        / "external"
        / "_current"
        / repository
        / ref
        / "generation.json"
    )


def _generation_directory(
    publication_root: Path,
    repository: str,
    ref: str,
    generation_id: str,
) -> Path:
    return (
        publication_root
        / "external"
        / "_generations"
        / repository
        / ref
        / generation_id
    )


def _generation_identity(
    *,
    repository: str,
    ref: str,
    source_manifest_sha256: str,
    artifact_families: Iterable[str],
) -> str:
    seed = {
        "kind": GENERATION_KIND,
        "version": GENERATION_VERSION,
        "repository": repository,
        "ref": ref,
        "sourceManifestSha256": source_manifest_sha256,
        "artifactFamilies": sorted(artifact_families),
    }
    compact = json.dumps(seed, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(compact).hexdigest()


def _generation_binding(
    *,
    generation_id: str,
    pointer_path: Path,
    manifest_path: Path,
    authoritative: bool,
    authoritative_manifest_path: Path | None = None,
) -> dict[str, Any]:
    binding: dict[str, Any] = {
        "kind": GENERATION_KIND,
        "version": GENERATION_VERSION,
        "id": generation_id,
        "authoritative": authoritative,
        "pointerPath": _relative_path(pointer_path, manifest_path.parent),
        "selectionRule": "read_pointer_once_then_verify_complete_generation",
    }
    if authoritative_manifest_path is not None:
        binding["authoritativeManifestPath"] = _relative_path(
            authoritative_manifest_path,
            manifest_path.parent,
        )
    return binding


def _prepare_generation_package(
    *,
    localized_manifest: Path,
    materialization: dict[str, Any],
    publication_root: Path,
    repository: str,
    ref: str,
    families: list[str],
) -> dict[str, Any]:
    generation_id = _generation_identity(
        repository=repository,
        ref=ref,
        source_manifest_sha256=str(materialization["sourceManifestSha256"]),
        artifact_families=families,
    )
    generation_dir = _generation_directory(
        publication_root,
        repository,
        ref,
        generation_id,
    )
    pointer_path = publication_generation_pointer_path(
        publication_root,
        repository=repository,
        ref=ref,
    )
    family_rows: list[dict[str, Any]] = []
    generated_at: str | None = None
    for family in families:
        manifest_path = generation_dir / "families" / family / "manifest.json"
        manifest = build_external_manifest_reference(
            localized_manifest,
            repository=repository,
            ref=ref,
            artifact_family=family,
            output_path=manifest_path,
            publication_root=publication_root,
        )
        generated_at = generated_at or str(manifest["generatedAt"])
        manifest["generatedAt"] = generated_at
        manifest["publicationGeneration"] = _generation_binding(
            generation_id=generation_id,
            pointer_path=pointer_path,
            manifest_path=manifest_path,
            authoritative=True,
        )
        payload = _json_bytes(manifest)
        family_rows.append(
            {
                "artifactFamily": family,
                "kind": manifest["kind"],
                "path": str(manifest_path),
                "relativePath": _relative_path(manifest_path, generation_dir),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "manifest": manifest,
            }
        )
    descriptor_path = generation_dir / "generation.json"
    descriptor = {
        "kind": GENERATION_KIND,
        "version": GENERATION_VERSION,
        "generationId": generation_id,
        "repository": repository,
        "ref": ref,
        "generatedAt": generated_at,
        "complete": True,
        "artifactFamilies": list(families),
        "sourceBundleManifest": {
            "path": _relative_path(localized_manifest, generation_dir),
            "sha256": materialization["sourceManifestSha256"],
            "bytes": materialization["sourceManifestBytes"],
        },
        "familyManifests": [
            {
                "artifactFamily": row["artifactFamily"],
                "kind": row["kind"],
                "path": row["relativePath"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
            }
            for row in family_rows
        ],
        "selectionRule": "only a verified pointer selects this complete generation",
        "doesNotEstablish": list(DOES_NOT_ESTABLISH),
    }
    descriptor_payload = _json_bytes(descriptor)
    pointer = {
        "kind": GENERATION_POINTER_KIND,
        "version": GENERATION_VERSION,
        "repository": repository,
        "ref": ref,
        "generationId": generation_id,
        "generatedAt": generated_at,
        "artifactFamilies": list(families),
        "generationDescriptor": {
            "path": Path(os.path.relpath(descriptor_path, publication_root)).as_posix(),
            "bytes": len(descriptor_payload),
            "sha256": hashlib.sha256(descriptor_payload).hexdigest(),
        },
        "selectionRule": "read this file once, then verify the descriptor and every declared family manifest; fail closed on any mismatch",
        "doesNotEstablish": list(DOES_NOT_ESTABLISH),
    }
    return {
        "generationId": generation_id,
        "generationDirectory": generation_dir,
        "descriptorPath": descriptor_path,
        "descriptor": descriptor,
        "descriptorPayload": descriptor_payload,
        "pointerPath": pointer_path,
        "pointer": pointer,
        "families": family_rows,
    }


def _regular_generation_files(root: Path) -> dict[str, bytes]:
    try:
        observed, _ = read_tree(root)
        return observed
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"generation tree must contain only trusted regular files and directories: {root}: {exc}"
        ) from exc


def _expected_generation_files(package: dict[str, Any]) -> dict[str, bytes]:
    expected = {"generation.json": package["descriptorPayload"]}
    for row in package["families"]:
        expected[str(row["relativePath"])] = _json_bytes(row["manifest"])
    return expected


def _install_generation(package: dict[str, Any]) -> bool:
    generation_dir = Path(package["generationDirectory"])
    expected = _expected_generation_files(package)
    try:
        make_directories(generation_dir.parent)
        if path_exists(generation_dir):
            observed = _regular_generation_files(generation_dir)
            if observed != expected:
                raise ExternalManifestReferenceError(
                    "existing generation directory does not match the expected immutable generation"
                )
            return True

        stage = make_temporary_directory(
            generation_dir.parent,
            prefix=str(package["generationId"]),
        )
        try:
            for row in package["families"]:
                relative_path = Path(str(row["relativePath"]))
                _write_generation_manifest_file(stage / relative_path, row["manifest"])
            _write_generation_descriptor(
                stage / "generation.json", package["descriptor"]
            )
            for family in package["families"]:
                _fsync_directory(stage / "families" / str(family["artifactFamily"]))
            _fsync_directory(stage / "families")
            _fsync_directory(stage)
            rename_path(stage, generation_dir)
            _fsync_directory(generation_dir.parent)
        finally:
            try:
                remove_tree(stage)
            except RootedFilesystemError:
                pass
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"generation installation failed before pointer commit: {exc}"
        ) from exc
    return False


def _resolve_declared_path(
    *,
    base: Path,
    raw_path: Any,
    publication_root: Path,
    label: str,
) -> Path:
    if not isinstance(raw_path, str) or not raw_path or Path(raw_path).is_absolute():
        raise ExternalManifestReferenceError(f"{label} path must be relative")
    candidate = secure_absolute(base / raw_path)
    _require_path_inside_root(candidate, publication_root, label)
    return candidate


def _verify_integrity_row(
    path: Path,
    row: dict[str, Any],
    label: str,
) -> tuple[dict[str, Any], int, str]:
    expected_sha = row.get("sha256")
    expected_bytes = row.get("bytes")
    if (
        not isinstance(expected_sha, str)
        or len(expected_sha) != 64
        or any(char not in "0123456789abcdef" for char in expected_sha)
        or not isinstance(expected_bytes, int)
        or isinstance(expected_bytes, bool)
        or expected_bytes < 0
    ):
        raise ExternalManifestReferenceError(f"{label} integrity row is invalid")
    data, observed_bytes, observed_sha = _read_json_regular_file(path, label)
    if observed_bytes != expected_bytes or observed_sha != expected_sha:
        raise ExternalManifestReferenceError(f"{label} integrity mismatch")
    return data, observed_bytes, observed_sha


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _validated_generation_pointer(
    pointer: dict[str, Any],
    *,
    repository: str,
    ref: str,
) -> tuple[str, dict[str, Any]]:
    if (
        pointer.get("kind") != GENERATION_POINTER_KIND
        or pointer.get("version") != GENERATION_VERSION
        or pointer.get("repository") != repository
        or pointer.get("ref") != ref
        or pointer.get("selectionRule")
        != "read this file once, then verify the descriptor and every declared family manifest; fail closed on any mismatch"
    ):
        raise ExternalManifestReferenceError("generation pointer contract mismatch")
    generation_id = pointer.get("generationId")
    if not _is_sha256(generation_id):
        raise ExternalManifestReferenceError("generation pointer id is invalid")
    descriptor_row = pointer.get("generationDescriptor")
    if not isinstance(descriptor_row, dict):
        raise ExternalManifestReferenceError("generation pointer descriptor is invalid")
    return generation_id, descriptor_row


def _read_generation_descriptor(
    *,
    root: Path,
    repository: str,
    ref: str,
    generation_id: str,
    descriptor_row: dict[str, Any],
) -> tuple[Path, dict[str, Any], int, str]:
    descriptor_path = _resolve_declared_path(
        base=root,
        raw_path=descriptor_row.get("path"),
        publication_root=root,
        label="generation descriptor",
    )
    expected_path = (
        _generation_directory(root, repository, ref, generation_id) / "generation.json"
    )
    if descriptor_path != expected_path:
        raise ExternalManifestReferenceError(
            "generation descriptor path is not canonical"
        )
    descriptor, descriptor_bytes, descriptor_sha = _verify_integrity_row(
        descriptor_path,
        descriptor_row,
        "generation descriptor",
    )
    return descriptor_path, descriptor, descriptor_bytes, descriptor_sha


def _validated_generation_descriptor(
    descriptor: dict[str, Any],
    *,
    repository: str,
    ref: str,
    generation_id: str,
) -> tuple[list[Any], list[str], dict[str, Any]]:
    if (
        descriptor.get("kind") != GENERATION_KIND
        or descriptor.get("version") != GENERATION_VERSION
        or descriptor.get("generationId") != generation_id
        or descriptor.get("repository") != repository
        or descriptor.get("ref") != ref
        or descriptor.get("complete") is not True
        or descriptor.get("selectionRule")
        != "only a verified pointer selects this complete generation"
    ):
        raise ExternalManifestReferenceError("generation descriptor contract mismatch")
    family_rows = descriptor.get("familyManifests")
    artifact_families = descriptor.get("artifactFamilies")
    source_row = descriptor.get("sourceBundleManifest")
    if (
        not isinstance(family_rows, list)
        or not family_rows
        or not isinstance(artifact_families, list)
        or not isinstance(source_row, dict)
    ):
        raise ExternalManifestReferenceError("generation descriptor is incomplete")
    normalized_families = _normalized_artifact_families(artifact_families)
    if normalized_families != sorted(normalized_families):
        raise ExternalManifestReferenceError(
            "generation artifact families are not canonical"
        )
    expected_generation_id = _generation_identity(
        repository=repository,
        ref=ref,
        source_manifest_sha256=str(source_row.get("sha256")),
        artifact_families=normalized_families,
    )
    if expected_generation_id != generation_id:
        raise ExternalManifestReferenceError("generation identity mismatch")
    return family_rows, normalized_families, source_row


def _verify_generation_source(
    *,
    root: Path,
    descriptor_path: Path,
    source_row: dict[str, Any],
) -> Path:
    source_path = _resolve_declared_path(
        base=descriptor_path.parent,
        raw_path=source_row.get("path"),
        publication_root=root,
        label="generation source bundle manifest",
    )
    source_bytes, source_sha = _digest_regular_file(
        source_path,
        "generation source bundle manifest",
    )
    if source_bytes != source_row.get("bytes") or source_sha != source_row.get(
        "sha256"
    ):
        raise ExternalManifestReferenceError(
            "generation source bundle integrity mismatch"
        )
    return source_path


def _read_generation_family(
    row: Any,
    *,
    root: Path,
    descriptor_path: Path,
    pointer_path: Path,
    generation_id: str,
    repository: str,
    ref: str,
    descriptor_generated_at: Any,
    source_path: Path,
    source_row: dict[str, Any],
    seen_families: set[str],
) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ExternalManifestReferenceError("generation family row must be an object")
    family = row.get("artifactFamily")
    if family not in SUPPORTED_FAMILIES or family in seen_families:
        raise ExternalManifestReferenceError("generation family row is invalid")
    family_name = str(family)
    seen_families.add(family_name)
    manifest_path = _resolve_declared_path(
        base=descriptor_path.parent,
        raw_path=row.get("path"),
        publication_root=root,
        label=f"{family_name} generation manifest",
    )
    expected_path = descriptor_path.parent / "families" / family_name / "manifest.json"
    if manifest_path != expected_path:
        raise ExternalManifestReferenceError(
            f"{family_name} generation manifest path is not canonical"
        )
    manifest, manifest_bytes, manifest_sha = _verify_integrity_row(
        manifest_path,
        row,
        f"{family_name} generation manifest",
    )
    binding = manifest.get("publicationGeneration")
    bundle_row = manifest.get("bundleManifest")
    expected_pointer_path = _relative_path(pointer_path, manifest_path.parent)
    expected_bundle_path = _relative_path(source_path, manifest_path.parent)
    if (
        row.get("kind") != manifest.get("kind")
        or manifest.get("kind") != f"{family_name}_bundle_manifest"
        or manifest.get("version") != "1"
        or manifest.get("artifactFamily") != family_name
        or manifest.get("repository") != repository
        or manifest.get("ref") != ref
        or manifest.get("generatedAt") != descriptor_generated_at
        or manifest.get("freshnessBasis") != "bundle_manifest.created_at"
        or not isinstance(bundle_row, dict)
        or bundle_row.get("kind") != BUNDLE_KIND
        or bundle_row.get("path") != expected_bundle_path
        or bundle_row.get("sha256") != source_row.get("sha256")
        or bundle_row.get("bytes") != source_row.get("bytes")
        or bundle_row.get("createdAt") != descriptor_generated_at
        or not isinstance(binding, dict)
        or binding.get("kind") != GENERATION_KIND
        or binding.get("version") != GENERATION_VERSION
        or binding.get("id") != generation_id
        or binding.get("authoritative") is not True
        or binding.get("pointerPath") != expected_pointer_path
        or binding.get("selectionRule")
        != "read_pointer_once_then_verify_complete_generation"
    ):
        raise ExternalManifestReferenceError(
            f"{family_name} generation manifest binding mismatch"
        )
    return {
        "artifactFamily": family_name,
        "kind": manifest.get("kind"),
        "path": str(manifest_path),
        "relativePublicationPath": Path(
            os.path.relpath(manifest_path, root)
        ).as_posix(),
        "generatedAt": manifest.get("generatedAt"),
        "generationId": generation_id,
        "bytes": manifest_bytes,
        "sha256": manifest_sha,
    }


def _read_external_manifest_publication_bound(
    publication_root: str | Path,
    *,
    repository: str,
    ref: str,
) -> dict[str, Any]:
    """Read one authoritative, complete generation through its atomic pointer."""
    repository = _registry_segment(repository, "repository")
    ref = _registry_segment(ref, "ref")
    root = secure_absolute(publication_root)
    pointer_path = publication_generation_pointer_path(
        root,
        repository=repository,
        ref=ref,
    )
    pointer, pointer_bytes, pointer_sha = _read_json_regular_file(
        pointer_path,
        "generation pointer",
    )
    generation_id, descriptor_row = _validated_generation_pointer(
        pointer,
        repository=repository,
        ref=ref,
    )
    descriptor_path, descriptor, descriptor_bytes, descriptor_sha = (
        _read_generation_descriptor(
            root=root,
            repository=repository,
            ref=ref,
            generation_id=generation_id,
            descriptor_row=descriptor_row,
        )
    )
    family_rows, normalized_families, source_row = _validated_generation_descriptor(
        descriptor,
        repository=repository,
        ref=ref,
        generation_id=generation_id,
    )
    pointer_families = pointer.get("artifactFamilies")
    if not isinstance(pointer_families, list):
        raise ExternalManifestReferenceError(
            "generation pointer artifact families are invalid"
        )
    normalized_pointer_families = _normalized_artifact_families(pointer_families)
    if (
        normalized_pointer_families != sorted(normalized_pointer_families)
        or normalized_pointer_families != normalized_families
        or pointer.get("generatedAt") != descriptor.get("generatedAt")
    ):
        raise ExternalManifestReferenceError(
            "generation pointer and descriptor metadata mismatch"
        )
    source_path = _verify_generation_source(
        root=root,
        descriptor_path=descriptor_path,
        source_row=source_row,
    )
    seen_families: set[str] = set()
    published = [
        _read_generation_family(
            row,
            root=root,
            descriptor_path=descriptor_path,
            pointer_path=pointer_path,
            generation_id=generation_id,
            repository=repository,
            ref=ref,
            descriptor_generated_at=descriptor.get("generatedAt"),
            source_path=source_path,
            source_row=source_row,
            seen_families=seen_families,
        )
        for row in family_rows
    ]
    if seen_families != set(normalized_families):
        raise ExternalManifestReferenceError("generation family set mismatch")
    return {
        "kind": GENERATION_SELECTION_KIND,
        "version": GENERATION_VERSION,
        "status": "committed",
        "repository": repository,
        "ref": ref,
        "publicationRoot": str(root),
        "generationId": generation_id,
        "pointerPath": str(pointer_path),
        "pointerBytes": pointer_bytes,
        "pointerSha256": pointer_sha,
        "descriptorPath": str(descriptor_path),
        "descriptorBytes": descriptor_bytes,
        "descriptorSha256": descriptor_sha,
        "sourceBundleManifest": str(source_path),
        "published": published,
        "doesNotEstablish": list(DOES_NOT_ESTABLISH),
    }


def read_external_manifest_publication(
    publication_root: str | Path,
    *,
    repository: str,
    ref: str,
) -> dict[str, Any]:
    """Read one complete generation through a bound publication-root identity."""
    root = secure_absolute(publication_root)
    try:
        with bind_directory(root, create=False) as binding:
            result = _read_external_manifest_publication_bound(
                root,
                repository=repository,
                ref=ref,
            )
            binding.assert_current_path_identity()
            return result
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"publication read lost its trusted root identity: {root}: {exc}"
        ) from exc


@contextmanager
def _publication_lock(
    publication_root: Path,
    repository: str,
    ref: str,
):
    lock_path = (
        publication_root / "external" / "_locks" / repository / ref / "publish.lock"
    )
    try:
        with exclusive_file_lock(lock_path):
            yield lock_path
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"publication lock lost its trusted directory identity: {lock_path}: {exc}"
        ) from exc


def _compatibility_projection(
    *,
    selection: dict[str, Any],
    publication_root: Path,
    repository: str,
    ref: str,
) -> dict[str, Any]:
    published: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    pointer_path = Path(str(selection["pointerPath"]))
    generation_id = str(selection["generationId"])
    for row in selection["published"]:
        family = str(row["artifactFamily"])
        authoritative_path = Path(str(row["path"]))
        try:
            authoritative, _, _ = _read_json_regular_file(
                authoritative_path,
                f"{family} authoritative generation manifest",
            )
            bundle_row = authoritative.get("bundleManifest")
            if not isinstance(bundle_row, dict):
                raise ExternalManifestReferenceError(
                    f"{family} authoritative manifest has no bundleManifest"
                )
            localized_manifest = _resolve_declared_path(
                base=authoritative_path.parent,
                raw_path=bundle_row.get("path"),
                publication_root=publication_root,
                label=f"{family} localized bundle manifest",
            )
            stable_path = publication_manifest_path(
                publication_root,
                repository=repository,
                ref=ref,
                artifact_family=family,
            )
            compatibility = build_external_manifest_reference(
                localized_manifest,
                repository=repository,
                ref=ref,
                artifact_family=family,
                output_path=stable_path,
                publication_root=publication_root,
            )
            compatibility["publicationGeneration"] = _generation_binding(
                generation_id=generation_id,
                pointer_path=pointer_path,
                manifest_path=stable_path,
                authoritative=False,
                authoritative_manifest_path=authoritative_path,
            )
            write_result = _write_compatibility_manifest(
                stable_path,
                compatibility,
            )
            published.append(
                {
                    "artifactFamily": family,
                    "kind": compatibility["kind"],
                    "path": str(stable_path),
                    "generatedAt": compatibility["generatedAt"],
                    "relativePublicationPath": Path(
                        os.path.relpath(stable_path, publication_root)
                    ).as_posix(),
                    "generationId": generation_id,
                    "authoritative": False,
                    "authoritativePath": str(authoritative_path),
                    "durability": write_result["durability"],
                }
            )
        except (ExternalManifestReferenceError, OSError) as exc:
            errors.append({"artifactFamily": family, "error": str(exc)})
    uncertain = [
        {
            "artifactFamily": str(row["artifactFamily"]),
            "durability": str(row["durability"]),
        }
        for row in published
        if row["durability"] != "durable"
    ]
    status = "degraded" if errors else "uncertain" if uncertain else "ok"
    return {
        "status": status,
        "published": published,
        "errors": errors,
        "uncertain": uncertain,
        "migrationRule": "legacy stable family paths are compatibility projections; authoritative readers must use the generation pointer",
    }


def recover_external_manifest_publication(
    publication_root: str | Path,
    *,
    repository: str,
    ref: str,
) -> dict[str, Any]:
    """Rebuild compatibility projections below one bound publication root."""
    repository = _registry_segment(repository, "repository")
    ref = _registry_segment(ref, "ref")
    root = secure_absolute(publication_root)
    try:
        with bind_directory(root, create=False) as binding:
            with _publication_lock(root, repository, ref):
                selection = read_external_manifest_publication(
                    root,
                    repository=repository,
                    ref=ref,
                )
                compatibility = _compatibility_projection(
                    selection=selection,
                    publication_root=root,
                    repository=repository,
                    ref=ref,
                )
            binding.assert_current_path_identity()
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"publication recovery lost its trusted root identity: {root}: {exc}"
        ) from exc
    return {
        "kind": "repobrief.external_manifest_publication_recovery",
        "version": GENERATION_VERSION,
        "status": "recovered" if compatibility["status"] == "ok" else "degraded",
        "generationId": selection["generationId"],
        "selection": selection,
        "compatibility": compatibility,
        "doesNotEstablish": list(DOES_NOT_ESTABLISH),
    }


def publish_external_manifest_references(
    bundle_manifest_path: str | Path,
    publication_root: str | Path,
    *,
    repository: str,
    ref: str,
    artifact_families: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Publish one complete generation below one trusted publication-root identity."""
    families = sorted(_normalized_artifact_families(artifact_families))
    repository = _registry_segment(repository, "repository")
    ref = _registry_segment(ref, "ref")
    root = secure_absolute(publication_root)
    try:
        with bind_directory(root, create=True) as binding:
            with _publication_lock(root, repository, ref) as lock_path:
                materialization = materialize_external_bundle(
                    bundle_manifest_path,
                    root,
                    repository=repository,
                    ref=ref,
                )
                localized_manifest = Path(str(materialization["bundleManifest"]))
                package = _prepare_generation_package(
                    localized_manifest=localized_manifest,
                    materialization=materialization,
                    publication_root=root,
                    repository=repository,
                    ref=ref,
                    families=families,
                )
                generation_reused = _install_generation(package)
                pointer_write = _write_generation_pointer(
                    Path(package["pointerPath"]),
                    package["pointer"],
                )
                selection = read_external_manifest_publication(
                    root,
                    repository=repository,
                    ref=ref,
                )
                if selection["generationId"] != package["generationId"]:
                    raise ExternalManifestReferenceError(
                        "generation pointer readback selected an unexpected generation"
                    )
                compatibility = _compatibility_projection(
                    selection=selection,
                    publication_root=root,
                    repository=repository,
                    ref=ref,
                )
            binding.assert_current_path_identity()
    except RootedFilesystemError as exc:
        raise ExternalManifestReferenceError(
            f"publication lost a trusted directory identity: {root}: {exc}"
        ) from exc

    if compatibility["status"] != "ok":
        status = "committed_compatibility_degraded"
    elif pointer_write["durability"] != "durable":
        status = "committed_durability_uncertain"
    else:
        status = "committed"
    return {
        "kind": "repobrief.external_manifest_publication",
        "version": "1",
        "publicationProtocolVersion": GENERATION_VERSION,
        "status": status,
        "repository": repository,
        "ref": ref,
        "publicationRoot": str(root),
        "sourceBundleManifest": str(secure_absolute(bundle_manifest_path)),
        "bundleManifest": str(localized_manifest),
        "materialization": materialization,
        "generation": {
            "id": package["generationId"],
            "directory": str(package["generationDirectory"]),
            "descriptorPath": str(package["descriptorPath"]),
            "pointerPath": str(package["pointerPath"]),
            "reused": generation_reused,
            "pointerDurability": pointer_write["durability"],
            "selectionRule": "read_pointer_once_then_verify_complete_generation",
            "serialization": "exclusive_lane_flock",
            "lockPath": str(lock_path),
            "filesystemBinding": "trusted_dirfd_openat",
        },
        "authoritativePublished": selection["published"],
        "published": compatibility["published"],
        "compatibility": compatibility,
        "doesNotEstablish": list(DOES_NOT_ESTABLISH),
    }
