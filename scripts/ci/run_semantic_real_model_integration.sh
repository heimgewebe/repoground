#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  printf 'usage: %s <semantic-dependency-target>\n' "$0" >&2
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
dependency_target="$1"
if [[ ! -d "$dependency_target" || -L "$dependency_target" ]]; then
  printf 'semantic dependency target must be a real directory: %s\n' \
    "$dependency_target" >&2
  exit 2
fi
dependency_target="$(cd "$dependency_target" && pwd -P)"

image='mcr.microsoft.com/playwright/python:v1.61.0-noble@sha256:a9731514f24121d1dcd25d58d0a38146646d290a5998fd80d3e533e7b5e21c69'

docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=256m \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp/home \
  --env HF_HOME=/tmp/hf-home \
  --env HF_HUB_OFFLINE=1 \
  --env TRANSFORMERS_OFFLINE=1 \
  --env HF_HUB_DISABLE_TELEMETRY=1 \
  --volume "$repo_root:/work:ro" \
  --volume "$dependency_target:/semantic-target:ro" \
  --workdir /work \
  "$image" \
  python -S scripts/ci/run_semantic_real_model_integration.py \
    --dependency-target /semantic-target
