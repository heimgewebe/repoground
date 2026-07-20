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
  rm -rf -- "$runtime_root"
}
trap cleanup EXIT
runtime_work="$runtime_root/work"
mkdir -- "$runtime_work"

python3 -P -S - "$repo_root" "$runtime_work" <<'PY'
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

repo_root = Path(sys.argv[1])
target = Path(sys.argv[2])
archive = subprocess.run(
    ["git", "-C", str(repo_root), "archive", "--format=tar", "HEAD"],
    check=True,
    stdout=subprocess.PIPE,
).stdout

with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as handle:
    members = handle.getmembers()
    for member in members:
        relative = PurePosixPath(member.name)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe archive path: {member.name!r}")
        if not member.isdir() and not member.isfile():
            raise RuntimeError(
                f"runtime archive contains non-regular entry: {member.name!r}"
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
platform_contract="$runtime_work/docs/release/repoground-semantic-platforms.v1.json"
dependency_target="$(
  python3 -P -S "$runner" \
    --validate-dependency-target "$1"
)"
image="$(
  python3 -P -S -c '
import json
import sys
from pathlib import Path

contract = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
image = contract.get("compiler", {}).get("image")
if not isinstance(image, str) or "@sha256:" not in image:
    raise SystemExit("semantic platform contract has no digest-pinned compiler image")
print(image)
' "$platform_contract"
)"
sandbox_uid=65532
sandbox_gid=65532

docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=256m,mode=1777 \
  --user "$sandbox_uid:$sandbox_gid" \
  --env HOME=/tmp \
  --env PYTHONPATH=/semantic-target:/work \
  --env PYTHONSAFEPATH=1 \
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
