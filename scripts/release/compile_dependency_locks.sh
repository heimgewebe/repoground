#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

image='mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d'

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp/home \
  --env PIP_CONFIG_FILE=/dev/null \
  --volume "$repo_root:/work" \
  --workdir /work \
  "$image" \
  bash --noprofile --norc -euo pipefail -c '
    mkdir -p /tmp/home
    python -m pip install --disable-pip-version-check --require-hashes \
      -r requirements/repoground-lock-tools.lock.txt
    for name in runtime dev browser lock-tools; do
      extra=()
      if [[ "$name" == "lock-tools" ]]; then
        extra+=(--allow-unsafe)
      fi
      python -m piptools compile \
        --generate-hashes \
        --resolver=backtracking \
        --strip-extras \
        --no-emit-index-url \
        "${extra[@]}" \
        --output-file "requirements/repoground-${name}.lock.txt" \
        "requirements/repoground-${name}.in"
    done
  '
