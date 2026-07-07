"""External manifest reference surface for RepoBrief/Lenskit consumers."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

SUPPORTED_FAMILIES = {"repobrief", "lenskit"}
BUNDLE_KIND = "repolens.bundle.manifest"
DOES_NOT_ESTABLISH = (
    "dump_freshness_truth",
    "claim_truth",
    "runtime_correctness",
    "semantic_correctness",
    "task_approval",
    "dump_generation_permission",
    "repo_understood",
    "merge_readiness",
)


class ExternalManifestReferenceError(ValueError):
    """Raised when an external manifest reference cannot be built."""


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExternalManifestReferenceError(f"bundle manifest does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExternalManifestReferenceError(f"bundle manifest is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ExternalManifestReferenceError("bundle manifest must be a JSON object")
    return data


def _relative_path(target: Path, base_dir: Path) -> str:
    return Path(os.path.relpath(target.resolve(), base_dir.resolve())).as_posix()


def _registry_segment(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "/" in value or "\\" in value:
        raise ExternalManifestReferenceError(f"{label} must be a non-empty registry segment")
    if value in {".", ".."}:
        raise ExternalManifestReferenceError(f"{label} must not be a traversal segment")
    return value


def _artifact_rows(bundle_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = bundle_manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ExternalManifestReferenceError("bundle manifest artifacts must be a list")
    rows: list[dict[str, Any]] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        role = artifact.get("role")
        path = artifact.get("path")
        sha256 = artifact.get("sha256")
        if not isinstance(role, str) or not isinstance(path, str):
            continue
        row: dict[str, Any] = {
            "role": role,
            "path": path,
            "sha256": sha256 if isinstance(sha256, str) else None,
        }
        if isinstance(artifact.get("bytes"), int):
            row["bytes"] = artifact["bytes"]
        if isinstance(artifact.get("content_type"), str):
            row["contentType"] = artifact["content_type"]
        rows.append(row)
    rows.sort(key=lambda item: (item["role"], item["path"]))
    return rows


def build_external_manifest_reference(
    bundle_manifest_path: str | Path,
    *,
    repository: str,
    ref: str,
    artifact_family: str = "repobrief",
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a bounded external manifest reference from an existing bundle manifest."""
    family = artifact_family.strip().lower() if isinstance(artifact_family, str) else ""
    if family not in SUPPORTED_FAMILIES:
        raise ExternalManifestReferenceError("artifact_family must be repobrief or lenskit")
    repository = _registry_segment(repository, "repository")
    ref = _registry_segment(ref, "ref")
    manifest_path = Path(bundle_manifest_path).expanduser().resolve()
    bundle = _read_json_object(manifest_path)
    if bundle.get("kind") != BUNDLE_KIND:
        raise ExternalManifestReferenceError("bundle manifest kind must be repolens.bundle.manifest")
    created_at = bundle.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        raise ExternalManifestReferenceError("bundle manifest created_at must be present")
    output_base = Path(output_path).expanduser().resolve().parent if output_path is not None else manifest_path.parent
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
            "kind": BUNDLE_KIND,
            "path": _relative_path(manifest_path, output_base),
            "runId": bundle.get("run_id"),
            "createdAt": created_at,
        },
        "snapshotProvenance": snapshot_provenance if isinstance(snapshot_provenance, dict) else None,
        "artifacts": _artifact_rows(bundle),
        "doesNotEstablish": list(DOES_NOT_ESTABLISH),
    }


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
        raise ExternalManifestReferenceError("artifact_family must be repobrief or lenskit")
    repository = _registry_segment(repository, "repository")
    ref = _registry_segment(ref, "ref")
    return Path(publication_root).expanduser().resolve() / "external" / family / repository / ref / "manifest.json"


def publish_external_manifest_references(
    bundle_manifest_path: str | Path,
    publication_root: str | Path,
    *,
    repository: str,
    ref: str,
    artifact_families: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Publish one or more external manifest references under a stable root."""
    families = list(dict.fromkeys(artifact_families)) if artifact_families is not None else sorted(SUPPORTED_FAMILIES)
    if not families:
        raise ExternalManifestReferenceError("at least one artifact family is required")
    published = []
    for family in families:
        out = publication_manifest_path(
            publication_root,
            repository=repository,
            ref=ref,
            artifact_family=family,
        )
        manifest = write_external_manifest_reference(
            bundle_manifest_path,
            out,
            repository=repository,
            ref=ref,
            artifact_family=family,
        )
        published.append({
            "artifactFamily": manifest["artifactFamily"],
            "kind": manifest["kind"],
            "path": str(out),
            "generatedAt": manifest["generatedAt"],
            "relativePublicationPath": Path(os.path.relpath(out, Path(publication_root).expanduser().resolve())).as_posix(),
        })
    return {
        "kind": "repobrief.external_manifest_publication",
        "version": "1",
        "repository": _registry_segment(repository, "repository"),
        "ref": _registry_segment(ref, "ref"),
        "publicationRoot": str(Path(publication_root).expanduser().resolve()),
        "bundleManifest": str(Path(bundle_manifest_path).expanduser().resolve()),
        "published": published,
        "doesNotEstablish": list(DOES_NOT_ESTABLISH),
    }


def write_external_manifest_reference(
    bundle_manifest_path: str | Path,
    output_path: str | Path,
    *,
    repository: str,
    ref: str,
    artifact_family: str = "repobrief",
) -> dict[str, Any]:
    """Write an external manifest reference atomically and return it."""
    out = Path(output_path).expanduser().resolve()
    data = build_external_manifest_reference(
        bundle_manifest_path,
        repository=repository,
        ref=ref,
        artifact_family=artifact_family,
        output_path=out,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(out.parent),
            prefix=f".{out.name}.",
            suffix=".tmp",
        ) as tmp_file:
            json.dump(data, tmp_file, indent=2, sort_keys=True)
            tmp_file.write("\n")
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            tmp_path = Path(tmp_file.name)
        os.replace(tmp_path, out)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
    return data
