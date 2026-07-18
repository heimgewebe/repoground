from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.release.build_release_candidate import (
    CONTRACT_VERSION,
    DISTRIBUTION_STATUS,
    DOES_NOT_ESTABLISH,
    KIND,
    LICENSE_EXPRESSION,
    LOCK_PATHS,
    SEMANTIC_CONSTRAINTS_PATH,
    SEMANTIC_INPUT_PATH,
    SEMANTIC_LOCK_PATH,
    SEMANTIC_PLATFORM_CONTRACT_PATH,
    SEMANTIC_TARGET_ID,
    SCHEMA_URI,
    VERSION_RE,
    list_tree,
    read_blob,
    resolve_tree,
    safe_symlink_target,
)


@dataclass(frozen=True)
class ReleaseContract:
    kind: str
    version: str
    schema_uri: str
    license_expression: str
    lock_paths: tuple[str, ...]
    semantic_target_id: str
    semantic_platform_contract_path: str
    semantic_input_path: str
    semantic_constraints_path: str
    semantic_lock_path: str
    project_name: str
    repository: str
    archive_slug: str
    compatibility_mode: str


CANONICAL_CONTRACT = ReleaseContract(
    kind=KIND,
    version=CONTRACT_VERSION,
    schema_uri=SCHEMA_URI,
    license_expression=LICENSE_EXPRESSION,
    lock_paths=LOCK_PATHS,
    semantic_target_id=SEMANTIC_TARGET_ID,
    semantic_platform_contract_path=SEMANTIC_PLATFORM_CONTRACT_PATH,
    semantic_input_path=SEMANTIC_INPUT_PATH,
    semantic_constraints_path=SEMANTIC_CONSTRAINTS_PATH,
    semantic_lock_path=SEMANTIC_LOCK_PATH,
    project_name="RepoGround",
    repository="heimgewebe/repoground",
    archive_slug="repoground",
    compatibility_mode="canonical_repoground_v1",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(name: str) -> bool:
    path = Path(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def _load_candidate(
    candidate_dir: Path, contract: ReleaseContract
) -> tuple[dict[str, object], Path, Path, Path]:
    manifests = sorted(candidate_dir.glob("*.release.json"))
    if len(manifests) != 1:
        raise ValueError(f"expected exactly one release manifest, found {len(manifests)}")
    manifest_path = manifests[0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != contract.kind or manifest.get("version") != contract.version:
        raise ValueError("release manifest kind/version mismatch")
    archive = manifest.get("archive")
    if not isinstance(archive, dict) or not isinstance(archive.get("path"), str):
        raise ValueError("release manifest archive path is missing")
    archive_name = archive["path"]
    if not _safe_name(archive_name) or Path(archive_name).name != archive_name:
        raise ValueError("release manifest archive path is unsafe")
    archive_path = candidate_dir / archive_name
    sums_path = candidate_dir / "SHA256SUMS"
    expected_names = {manifest_path.name, archive_name, sums_path.name}
    observed_names = {item.name for item in candidate_dir.iterdir()}
    if observed_names != expected_names:
        raise ValueError(
            "candidate directory file set mismatch: "
            f"expected={sorted(expected_names)!r} observed={sorted(observed_names)!r}"
        )
    if any(
        not item.is_file() or item.is_symlink()
        for item in candidate_dir.iterdir()
    ):
        raise ValueError("candidate directory may contain regular files only")
    return manifest, manifest_path, archive_path, sums_path


def _verify_sums(
    manifest_path: Path,
    archive_path: Path,
    sums_path: Path,
) -> None:
    if not sums_path.is_file():
        raise ValueError("SHA256SUMS is missing")
    expected = {
        archive_path.name: _sha256(archive_path),
        manifest_path.name: _sha256(manifest_path),
    }
    observed: dict[str, str] = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/]+)", line)
        if not match:
            raise ValueError(f"invalid SHA256SUMS line: {line!r}")
        digest, name = match.groups()
        if name in observed:
            raise ValueError(f"duplicate SHA256SUMS entry: {name}")
        observed[name] = digest
    if observed != expected:
        raise ValueError("SHA256SUMS does not match candidate files")


def _archive_members(
    manifest: dict[str, object],
    archive_path: Path,
) -> dict[str, tarfile.TarInfo]:
    archive = manifest["archive"]
    assert isinstance(archive, dict)
    expected_sha = archive.get("sha256")
    expected_bytes = archive.get("bytes")
    prefix = archive.get("prefix")
    if _sha256(archive_path) != expected_sha:
        raise ValueError("archive SHA-256 does not match manifest")
    if archive_path.stat().st_size != expected_bytes:
        raise ValueError("archive byte size does not match manifest")
    if not isinstance(prefix, str) or not prefix.endswith("/") or not _safe_name(prefix):
        raise ValueError("archive prefix is invalid")
    raw = archive_path.read_bytes()
    if len(raw) < 8 or int.from_bytes(raw[4:8], "little") != 0:
        raise ValueError("gzip timestamp is not normalized to zero")

    members: dict[str, tarfile.TarInfo] = {}
    observed_order: list[str] = []
    with gzip.open(archive_path, "rb") as gz:
        with tarfile.open(fileobj=gz, mode="r:") as tar:
            for member in tar.getmembers():
                if member.name in members:
                    raise ValueError(f"duplicate archive member: {member.name}")
                observed_order.append(member.name)
                if not _safe_name(member.name):
                    raise ValueError(f"unsafe archive member: {member.name!r}")
                if member.name != prefix.rstrip("/") and not member.name.startswith(prefix):
                    raise ValueError(f"member outside archive prefix: {member.name!r}")
                if member.uid != 0 or member.gid != 0 or member.mtime != 0:
                    raise ValueError(f"non-normalized metadata: {member.name!r}")
                if not (member.isdir() or member.isfile() or member.issym()):
                    raise ValueError(f"unsupported archive member type: {member.name!r}")
                if member.issym():
                    relative_path = member.name[len(prefix):]
                    if not safe_symlink_target(relative_path, member.linkname):
                        raise ValueError(
                            f"unsafe symlink target {member.linkname!r} "
                            f"at {member.name!r}"
                        )
                members[member.name] = member
    expected_count = archive.get("tracked_entry_count")
    if len(members) != expected_count + 1:
        raise ValueError("archive member count does not match manifest")
    root_name = prefix.rstrip("/")
    child_names = [name for name in observed_order if name != root_name]
    expected_order = [
        root_name,
        *sorted(
            child_names,
            key=lambda name: name[len(prefix) :].encode(
                "utf-8", errors="surrogateescape"
            ),
        ),
    ]
    if observed_order != expected_order:
        raise ValueError("archive member order is not canonical")
    return members


def _read_archive_member(archive_path: Path, name: str) -> bytes:
    with gzip.open(archive_path, "rb") as gz:
        with tarfile.open(fileobj=gz, mode="r:") as tar:
            try:
                member = tar.getmember(name)
            except KeyError as exc:
                raise ValueError(f"required archive member is missing: {name}") from exc
            if not member.isfile():
                raise ValueError(f"required archive member is not a file: {name}")
            handle = tar.extractfile(member)
            if handle is None:
                raise ValueError(f"cannot read required archive member: {name}")
            return handle.read()



def _verify_dependency_locks(
    manifest: dict[str, object],
    archive_path: Path,
    expected_prefix: str,
    contract: ReleaseContract,
) -> None:
    lock_records = manifest.get("dependency_locks")
    if not isinstance(lock_records, list) or len(lock_records) != len(contract.lock_paths):
        raise ValueError("manifest dependency lock count mismatch")
    observed_paths: list[str] = []
    for record in lock_records:
        if not isinstance(record, dict):
            raise ValueError("manifest dependency lock entry is invalid")
        path = record.get("path")
        if not isinstance(path, str):
            raise ValueError("manifest dependency lock path is invalid")
        observed_paths.append(path)
        content = _read_archive_member(archive_path, f"{expected_prefix}{path}")
        if record.get("bytes") != len(content):
            raise ValueError(f"dependency lock byte size mismatch: {path}")
        if record.get("sha256") != hashlib.sha256(content).hexdigest():
            raise ValueError(f"dependency lock SHA-256 mismatch: {path}")
    if tuple(observed_paths) != contract.lock_paths:
        raise ValueError("manifest dependency lock path/order mismatch")


def _verify_semantic_record(
    archive_path: Path,
    expected_prefix: str,
    record: object,
    expected_path: str,
) -> None:
    if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
        raise ValueError(f"semantic extension record is invalid: {expected_path}")
    if record.get("path") != expected_path:
        raise ValueError(f"semantic extension path mismatch: {expected_path}")
    content = _read_archive_member(archive_path, f"{expected_prefix}{expected_path}")
    if record.get("bytes") != len(content):
        raise ValueError(f"semantic extension byte size mismatch: {expected_path}")
    if record.get("sha256") != hashlib.sha256(content).hexdigest():
        raise ValueError(f"semantic extension SHA-256 mismatch: {expected_path}")


def _verify_semantic_target(
    archive_path: Path,
    expected_prefix: str,
    target: object,
    contract: ReleaseContract,
) -> None:
    if not isinstance(target, dict) or set(target) != {
        "id", "input", "constraints", "lock"
    }:
        raise ValueError("semantic extension target record is invalid")
    if target.get("id") != contract.semantic_target_id:
        raise ValueError("semantic extension target identity mismatch")
    _verify_semantic_record(
        archive_path, expected_prefix, target.get("input"), contract.semantic_input_path
    )
    _verify_semantic_record(
        archive_path,
        expected_prefix,
        target.get("constraints"),
        contract.semantic_constraints_path,
    )
    _verify_semantic_record(
        archive_path, expected_prefix, target.get("lock"), contract.semantic_lock_path
    )


def _verify_semantic_extension(
    manifest: dict[str, object],
    archive_path: Path,
    expected_prefix: str,
    contract: ReleaseContract,
) -> None:
    semantic = manifest.get("semantic_extension")
    if not isinstance(semantic, dict):
        raise ValueError("semantic extension boundary is missing")
    if semantic.get("status") != "optional_locked":
        raise ValueError("semantic extension status mismatch")
    if semantic.get("default_enabled") is not False:
        raise ValueError("semantic extension must remain disabled by default")
    if semantic.get("unsupported_target_policy") != "fail_closed":
        raise ValueError("semantic extension unsupported-target policy mismatch")
    _verify_semantic_record(
        archive_path,
        expected_prefix,
        semantic.get("platform_contract"),
        contract.semantic_platform_contract_path,
    )
    targets = semantic.get("targets")
    if not isinstance(targets, list) or len(targets) != 1:
        raise ValueError("semantic extension target count mismatch")
    _verify_semantic_target(archive_path, expected_prefix, targets[0], contract)


def _verify_manifest_contract(
    manifest: dict[str, object],
    archive_path: Path,
    contract: ReleaseContract,
) -> None:
    if manifest.get("$schema") != contract.schema_uri:
        raise ValueError("release manifest schema URI mismatch")

    project = manifest.get("project")
    source = manifest.get("source")
    archive = manifest.get("archive")
    if not all(isinstance(value, dict) for value in (project, source, archive)):
        raise ValueError("manifest project/source/archive objects are missing")
    assert isinstance(project, dict)
    assert isinstance(source, dict)
    assert isinstance(archive, dict)

    release_version = project.get("release_version")
    commit = source.get("git_commit")
    tree = source.get("git_tree")
    if project.get("name") != contract.project_name:
        raise ValueError("manifest project name mismatch")
    if project.get("repository") != contract.repository:
        raise ValueError("manifest repository mismatch")
    if not isinstance(release_version, str) or not VERSION_RE.fullmatch(release_version):
        raise ValueError("manifest release version is invalid")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("manifest commit is invalid")
    if not isinstance(tree, str) or not re.fullmatch(r"[0-9a-f]{40}", tree):
        raise ValueError("manifest tree is invalid")
    if source.get("git_dirty") is not False or source.get("archive_timestamp") != 0:
        raise ValueError("manifest source normalization mismatch")

    candidate_id = f"{release_version}-g{commit[:12]}"
    if project.get("candidate_id") != candidate_id:
        raise ValueError("manifest candidate id does not match version and commit")
    expected_prefix = f"{contract.archive_slug}-{candidate_id}/"
    expected_archive_name = f"{contract.archive_slug}-{candidate_id}.tar.gz"
    if archive.get("prefix") != expected_prefix:
        raise ValueError("manifest archive prefix mismatch")
    if archive.get("path") != expected_archive_name:
        raise ValueError("manifest archive filename mismatch")
    if archive.get("format") != "tar.gz":
        raise ValueError("manifest archive format mismatch")
    if archive.get("normalization") != {
        "uid": 0,
        "gid": 0,
        "mtime": 0,
        "gzip_mtime": 0,
        "path_order": "git_path_bytes_ascending",
    }:
        raise ValueError("manifest archive normalization mismatch")

    _verify_dependency_locks(manifest, archive_path, expected_prefix, contract)

    license_content = _read_archive_member(
        archive_path, f"{expected_prefix}LICENSE"
    ).decode("utf-8")
    if "Apache License" not in license_content or "Version 2.0" not in license_content:
        raise ValueError("archived LICENSE does not contain Apache-2.0")

    _verify_semantic_extension(manifest, archive_path, expected_prefix, contract)

    nonclaims = manifest.get("does_not_establish")
    if not isinstance(nonclaims, list) or not set(DOES_NOT_ESTABLISH).issubset(nonclaims):
        raise ValueError("manifest does_not_establish boundary is incomplete")

def _compare_with_repo(
    repo: Path,
    manifest: dict[str, object],
    archive_path: Path,
    members: dict[str, tarfile.TarInfo],
) -> None:
    source = manifest.get("source")
    archive = manifest.get("archive")
    if not isinstance(source, dict) or not isinstance(archive, dict):
        raise ValueError("manifest source/archive objects are missing")
    commit = source.get("git_commit")
    tree = source.get("git_tree")
    prefix = archive.get("prefix")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("manifest commit is invalid")
    if resolve_tree(repo, commit) != tree:
        raise ValueError("manifest tree does not match repository commit")
    if not isinstance(prefix, str):
        raise ValueError("manifest prefix is invalid")

    expected_entries = list_tree(repo, commit)
    expected_names = {f"{prefix}{entry.path}" for entry in expected_entries}
    observed_names = {name for name in members if name != prefix.rstrip("/")}
    if observed_names != expected_names:
        raise ValueError("archive path set does not match Git tree")

    with gzip.open(archive_path, "rb") as gz:
        with tarfile.open(fileobj=gz, mode="r:") as tar:
            for entry in expected_entries:
                member = tar.getmember(f"{prefix}{entry.path}")
                blob = read_blob(repo, commit, entry.path)
                if entry.mode == "120000":
                    target = blob.decode("utf-8", errors="surrogateescape")
                    if not member.issym() or member.linkname != target:
                        raise ValueError(f"symlink mismatch: {entry.path}")
                    continue
                expected_mode = 0o755 if entry.mode == "100755" else 0o644
                if not member.isfile() or member.mode != expected_mode:
                    raise ValueError(f"mode/type mismatch: {entry.path}")
                handle = tar.extractfile(member)
                if handle is None or handle.read() != blob:
                    raise ValueError(f"content mismatch: {entry.path}")


def _contract_for_manifest(manifest: dict[str, object]) -> ReleaseContract:
    identity = (manifest.get("kind"), manifest.get("version"), manifest.get("$schema"))
    for contract in (CANONICAL_CONTRACT,):
        if identity == (contract.kind, contract.version, contract.schema_uri):
            return contract
    raise ValueError("unsupported or contradictory release manifest identity")


def _verify_release_candidate(
    candidate_path: Path,
    *,
    contract: ReleaseContract,
    repo: str | Path | None,
) -> dict[str, object]:
    manifest, manifest_path, archive_path, sums_path = _load_candidate(
        candidate_path, contract
    )
    if not archive_path.is_file():
        raise ValueError("candidate archive is missing")
    _verify_sums(manifest_path, archive_path, sums_path)

    license_data = manifest.get("license")
    if not isinstance(license_data, dict):
        raise ValueError("license object is missing")
    if license_data.get("expression") != contract.license_expression:
        raise ValueError("license expression mismatch")
    if license_data.get("distribution_status") != DISTRIBUTION_STATUS:
        raise ValueError("distribution boundary mismatch")

    members = _archive_members(manifest, archive_path)
    _verify_manifest_contract(manifest, archive_path, contract)
    if repo is not None:
        _compare_with_repo(
            Path(repo).expanduser().resolve(), manifest, archive_path, members
        )
    project = manifest.get("project")
    assert isinstance(project, dict)
    return {
        "status": "pass",
        "candidate_id": project["candidate_id"],
        "archive_sha256": _sha256(archive_path),
        "manifest_sha256": _sha256(manifest_path),
        "member_count": len(members),
        "source_bound": repo is not None,
        "distribution_status": DISTRIBUTION_STATUS,
        "compatibility_mode": contract.compatibility_mode,
    }


def verify_release_candidate(
    candidate_dir: str | Path,
    *,
    repo: str | Path | None = None,
) -> dict[str, object]:
    candidate_path = Path(candidate_dir).expanduser().resolve()
    if not candidate_path.is_dir():
        raise ValueError(f"candidate directory is missing: {candidate_path}")
    manifests = sorted(candidate_path.glob("*.release.json"))
    if len(manifests) != 1:
        raise ValueError(f"expected exactly one release manifest, found {len(manifests)}")
    preview = json.loads(manifests[0].read_text(encoding="utf-8"))
    if not isinstance(preview, dict):
        raise ValueError("release manifest must be a JSON object")
    contract = _contract_for_manifest(preview)
    return _verify_release_candidate(candidate_path, contract=contract, repo=repo)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a RepoGround release candidate")
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--repo")
    args = parser.parse_args()
    try:
        report = verify_release_candidate(args.candidate_dir, repo=args.repo)
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
