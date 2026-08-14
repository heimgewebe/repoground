#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

image='mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d'

args=()
volume="$repo_root:/work"
case "${1:-}" in
  "") ;;
  --check)
    args+=(--check)
    volume="$repo_root:/work:ro"
    ;;
  *)
    echo "usage: $0 [--check]" >&2
    exit 2
    ;;
esac
if (( $# > 1 )); then
  echo "usage: $0 [--check]" >&2
  exit 2
fi

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp/home \
  --env PIP_CONFIG_FILE=/dev/null \
  --volume "$volume" \
  --workdir /work \
  "$image" \
  bash --noprofile --norc -euo pipefail -c '
    mkdir -p /tmp/home
    install_source="$(python scripts/release/compile_dependency_locks.py --print-install-source)"
    case "$install_source" in
      lock)
        python -m pip install --disable-pip-version-check --root-user-action=ignore --require-hashes \
          -r requirements/repoground-lock-tools.lock.txt
        ;;
      input)
        echo "RepoGround lock-toolchain self-bootstrap: exact input pins differ from the checked-in tool lock." >&2
        python -m pip install --disable-pip-version-check --root-user-action=ignore \
          -r requirements/repoground-lock-tools.in
        ;;
      *)
        echo "ERROR: unsupported lock-toolchain install source: $install_source" >&2
        exit 2
        ;;
    esac

    python scripts/release/compile_dependency_locks.py "$@"

    if [[ "$install_source" == input && "${1:-}" != "--check" ]]; then
      echo "RepoGround lock-toolchain self-bootstrap: verifying fresh hashed tool lock." >&2
      verify_target=/tmp/repoground-lock-verify
      mkdir -p "$verify_target"
      python -m pip install \
        --disable-pip-version-check --require-hashes --target "$verify_target" \
        -r requirements/repoground-lock-tools.lock.txt
      PYTHONPATH="$verify_target" PYTHONNOUSERSITE=1 \
        exec python -S scripts/release/compile_dependency_locks.py --check
    fi
  ' repoground-lock-generator "${args[@]}"
