#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  printf 'usage: %s <semantic-dependency-target>\n' "$0" >&2
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
runtime_root="$(
  mktemp -d "${TMPDIR:-/tmp}/repoground-semantic-runtime.XXXXXX"
)"
cleanup() {
  status=$?
  # Signal handlers pass an explicit 128+signal status; it intentionally wins
  # over the command status captured for the ordinary EXIT-trap path.
  if [[ "$#" -gt 0 ]]; then
    status="$1"
  fi
  trap - EXIT HUP INT TERM
  chmod -R u+rwX -- "$runtime_root" 2>/dev/null || true
  rm -rf -- "$runtime_root" || true
  exit "$status"
}
handle_signal() {
  cleanup "$1"
}
trap cleanup EXIT
trap 'handle_signal 129' HUP
trap 'handle_signal 130' INT
trap 'handle_signal 143' TERM
runtime_work="$runtime_root/work"
mkdir -- "$runtime_work"

python3 -I -S - "$repo_root" "$runtime_work" <<'PY'
from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

repo_root = Path(sys.argv[1])
target = Path(sys.argv[2])


def _archive_member_kind(member: tarfile.TarInfo) -> str:
    if member.isdir():
        return "directory"
    if member.isfile():
        return "regular file"
    if member.issym():
        return "symbolic link"
    if member.islnk():
        return "hard link"
    if member.ischr():
        return "character device"
    if member.isblk():
        return "block device"
    if member.isfifo():
        return "FIFO"
    return f"unknown type {member.type!r}"


with tempfile.TemporaryFile() as archive:
    subprocess.run(
        ["git", "-C", str(repo_root), "archive", "--format=tar", "HEAD"],
        check=True,
        stdout=archive,
    )
    archive.seek(0)
    with tarfile.open(fileobj=archive, mode="r:") as handle:
        members = handle.getmembers()
        for member in members:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"unsafe archive path: {member.name!r}")
            member_kind = _archive_member_kind(member)
            if member_kind not in {"directory", "regular file"}:
                raise RuntimeError(
                    "runtime archive contains unsafe "
                    f"{member_kind}: {member.name!r}"
                )

        directories: set[Path] = {target}
        for member in members:
            relative = PurePosixPath(member.name)
            destination = target.joinpath(*relative.parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                directories.add(destination)
                continue

            destination.parent.mkdir(parents=True, exist_ok=True)
            directories.add(destination.parent)
            source = handle.extractfile(member)
            if source is None:
                raise RuntimeError(f"archive file has no payload: {member.name!r}")
            with source, destination.open("xb") as output:
                shutil.copyfileobj(source, output)
            destination.chmod(0o444)

for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
    directory.chmod(0o555)
PY

runner="$runtime_work/scripts/ci/run_semantic_real_model_integration.py"
dependency_target="$(
  python3 -I -S "$runner" \
    --validate-dependency-target "$1"
)"
image="$(
  python3 -I -S "$runner" --compiler-image
)"
sandbox_uid=65532
sandbox_gid=65532

docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 256 \
  --memory 2g \
  --memory-swap 2g \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=256m,mode=1777 \
  --user "$sandbox_uid:$sandbox_gid" \
  --env HOME=/tmp \
  --env PYTHONPATH=/semantic-target:/work \
  --env PYTHONSAFEPATH=1 \
  --env PYTHONNOUSERSITE=1 \
  --env HF_HOME=/tmp/hf-home \
  --env HF_HUB_OFFLINE=1 \
  --env TRANSFORMERS_OFFLINE=1 \
  --env HF_HUB_DISABLE_TELEMETRY=1 \
  --volume "$runtime_work:/work:ro" \
  --volume "$dependency_target:/semantic-target:ro" \
  --workdir /work \
  "$image" \
  python -P -S scripts/ci/run_semantic_real_model_integration.py \
    --dependency-target /semantic-target
