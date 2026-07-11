from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

KIND = "repobrief.release_candidate"
CONTRACT_VERSION = "v1"
SCHEMA_URI = "https://heimgewebe.local/schema/repobrief-release-candidate.v1.schema.json"
LICENSE_EXPRESSION = "LicenseRef-RepoBrief-All-Rights-Reserved"
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
LOCK_PATHS = (
    "requirements/repobrief-runtime.lock.txt",
    "requirements/repobrief-dev.lock.txt",
    "requirements/repobrief-browser.lock.txt",
    "requirements/repobrief-lock-tools.lock.txt",
)
DOES_NOT_ESTABLISH = (
    "public_distribution_permission",
    "open_source_status",
    "product_readiness",
    "deployment_authorization",
    "runtime_correctness",
    "test_completeness",
    "absence_of_vulnerabilities",
    "semantic_extension_reproducibility",
)


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    object_type: str
    object_id: str
    path: str


def _run_git(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_repo(repo: Path) -> Path:
    resolved = repo.expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"repository is not a directory: {resolved}")
    root = Path(_run_git(resolved, "rev-parse", "--show-toplevel").decode().strip())
    if root.resolve() != resolved:
        raise ValueError(f"--repo must be the Git top level: {root}")
    dirty = _run_git(resolved, "status", "--porcelain=v1", "--untracked-files=all")
    if dirty:
        raise ValueError("release candidate requires a clean working tree")
    return resolved


def resolve_commit(repo: Path, ref: str) -> str:
    commit = _run_git(repo, "rev-parse", f"{ref}^{{commit}}").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError(f"unexpected commit id: {commit!r}")
    return commit


def resolve_tree(repo: Path, commit: str) -> str:
    tree = _run_git(repo, "rev-parse", f"{commit}^{{tree}}").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", tree):
        raise ValueError(f"unexpected tree id: {tree!r}")
    return tree


def read_blob(repo: Path, commit: str, path: str) -> bytes:
    return _run_git(repo, "show", f"{commit}:{path}")


def read_release_version(repo: Path, commit: str) -> str:
    value = read_blob(repo, commit, "RELEASE_VERSION").decode("utf-8").strip()
    if not VERSION_RE.fullmatch(value):
        raise ValueError(f"invalid RELEASE_VERSION: {value!r}")
    return value


def list_tree(repo: Path, commit: str) -> tuple[TreeEntry, ...]:
    raw = _run_git(repo, "ls-tree", "-rz", "--full-tree", commit)
    entries: list[TreeEntry] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split(" ")
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if path.startswith("/") or ".." in Path(path).parts:
            raise ValueError(f"unsafe Git path: {path!r}")
        if object_type != "blob":
            raise ValueError(
                f"unsupported Git tree entry {object_type!r} at {path!r}"
            )
        if mode not in {"100644", "100755", "120000"}:
            raise ValueError(f"unsupported Git mode {mode!r} at {path!r}")
        entries.append(TreeEntry(mode, object_type, object_id, path))
    entries.sort(key=lambda item: item.path.encode("utf-8", errors="surrogateescape"))
    return tuple(entries)


def safe_symlink_target(path: str, target: str) -> bool:
    if not target or "\x00" in target or target.startswith("/"):
        return False
    stack = list(PurePosixPath(path).parent.parts)
    for part in PurePosixPath(target).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not stack:
                return False
            stack.pop()
            continue
        stack.append(part)
    return True


def _tar_info(name: str, *, mode: int, entry_type: bytes) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.type = entry_type
    return info


def build_archive_bytes(
    repo: Path,
    commit: str,
    prefix: str,
    entries: Iterable[TreeEntry],
) -> bytes:
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.GNU_FORMAT) as tar:
        root_info = _tar_info(prefix.rstrip("/"), mode=0o755, entry_type=tarfile.DIRTYPE)
        tar.addfile(root_info)
        for entry in entries:
            archive_name = f"{prefix}{entry.path}"
            blob = read_blob(repo, commit, entry.path)
            if entry.mode == "120000":
                target = blob.decode("utf-8", errors="surrogateescape")
                if not safe_symlink_target(entry.path, target):
                    raise ValueError(
                        f"unsafe symlink target {target!r} at {entry.path!r}"
                    )
                info = _tar_info(archive_name, mode=0o777, entry_type=tarfile.SYMTYPE)
                info.linkname = target
                info.size = 0
                tar.addfile(info)
                continue
            mode = 0o755 if entry.mode == "100755" else 0o644
            info = _tar_info(archive_name, mode=mode, entry_type=tarfile.REGTYPE)
            info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob))
    compressed = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        fileobj=compressed,
        compresslevel=9,
        mtime=0,
    ) as gz:
        gz.write(tar_buffer.getvalue())
    return compressed.getvalue()


def _lock_records(repo: Path, commit: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in LOCK_PATHS:
        data = read_blob(repo, commit, path)
        records.append(
            {
                "path": path,
                "bytes": len(data),
                "sha256": _sha256_bytes(data),
            }
        )
    return records


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _json_bytes(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_release_candidate(
    repo: str | Path,
    out: str | Path,
    *,
    ref: str = "HEAD",
) -> dict[str, object]:
    repo_path = _validate_repo(Path(repo))
    out_path = Path(out).expanduser().resolve()
    if out_path == repo_path or repo_path in out_path.parents:
        raise ValueError("candidate output must be outside the source repository")
    out_path.mkdir(parents=True, exist_ok=True)
    if any(out_path.iterdir()):
        raise ValueError("candidate output directory must be empty")

    commit = resolve_commit(repo_path, ref)
    tree = resolve_tree(repo_path, commit)
    release_version = read_release_version(repo_path, commit)
    license_text = read_blob(repo_path, commit, "LICENSE").decode("utf-8")
    if LICENSE_EXPRESSION not in license_text:
        raise ValueError("LICENSE does not declare the required LicenseRef")

    entries = list_tree(repo_path, commit)
    candidate_id = f"{release_version}-g{commit[:12]}"
    prefix = f"repobrief-{candidate_id}/"
    archive_name = f"repobrief-{candidate_id}.tar.gz"
    manifest_name = f"repobrief-{candidate_id}.release.json"
    sums_name = "SHA256SUMS"

    archive_bytes = build_archive_bytes(repo_path, commit, prefix, entries)
    archive_path = out_path / archive_name
    _write_bytes(archive_path, archive_bytes)

    manifest: dict[str, object] = {
        "$schema": SCHEMA_URI,
        "kind": KIND,
        "version": CONTRACT_VERSION,
        "project": {
            "name": "RepoBrief",
            "repository": "heimgewebe/lenskit",
            "release_version": release_version,
            "candidate_id": candidate_id,
        },
        "source": {
            "git_commit": commit,
            "git_tree": tree,
            "git_dirty": False,
            "archive_timestamp": 0,
        },
        "license": {
            "expression": LICENSE_EXPRESSION,
            "file": "LICENSE",
            "distribution_status": "blocked_without_separate_written_permission",
        },
        "archive": {
            "path": archive_name,
            "prefix": prefix,
            "format": "tar.gz",
            "bytes": len(archive_bytes),
            "sha256": _sha256_bytes(archive_bytes),
            "tracked_entry_count": len(entries),
            "normalization": {
                "uid": 0,
                "gid": 0,
                "mtime": 0,
                "gzip_mtime": 0,
                "path_order": "git_path_bytes_ascending",
            },
        },
        "dependency_locks": _lock_records(repo_path, commit),
        "semantic_extension": {
            "status": "excluded",
            "reason": "platform-specific transitive closure is not hash-locked",
            "input": "merger/lenskit/requirements-semantic.txt",
        },
        "verification": {
            "self_contained_command": (
                "python scripts/release/verify_release_candidate.py "
                "--candidate-dir <candidate-dir>"
            ),
            "source_bound_command": (
                "python scripts/release/verify_release_candidate.py "
                "--candidate-dir <candidate-dir> --repo ."
            ),
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    manifest_path = out_path / manifest_name
    manifest_bytes = _json_bytes(manifest)
    _write_bytes(manifest_path, manifest_bytes)

    sums_lines = [
        f"{_sha256_file(archive_path)}  {archive_name}",
        f"{_sha256_file(manifest_path)}  {manifest_name}",
    ]
    sums_path = out_path / sums_name
    sums_path.write_text("\n".join(sorted(sums_lines)) + "\n", encoding="utf-8")

    return {
        "status": "pass",
        "candidate_id": candidate_id,
        "commit": commit,
        "tree": tree,
        "archive": str(archive_path),
        "manifest": str(manifest_path),
        "checksums": str(sums_path),
        "archive_sha256": _sha256_file(archive_path),
        "manifest_sha256": _sha256_file(manifest_path),
        "tracked_entry_count": len(entries),
        "distribution_status": "blocked_without_separate_written_permission",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic RepoBrief source candidate")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args()
    try:
        result = build_release_candidate(args.repo, args.out, ref=args.ref)
    except ValueError as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
