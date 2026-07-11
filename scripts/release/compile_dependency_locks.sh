#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

image='mcr.microsoft.com/playwright/python:v1.61.0-noble@sha256:a9731514f24121d1dcd25d58d0a38146646d290a5998fd80d3e533e7b5e21c69'

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
      -r requirements/repobrief-lock-tools.lock.txt
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
        --output-file "requirements/repobrief-${name}.lock.txt" \
        "requirements/repobrief-${name}.in"
    done
  '
