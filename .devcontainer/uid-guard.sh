#!/usr/bin/env bash
set -euo pipefail

repo="${DEVCONTAINER_WORKSPACE:-/workspaces/weltgewebe}"

if [ ! -d "$repo" ]; then
  echo "UID-GUARD: workspace not found: $repo" >&2
  exit 66
fi

workspace_uid="$(stat -c '%u' "$repo")"
workspace_gid="$(stat -c '%g' "$repo")"
current_uid="$(id -u)"
current_gid="$(id -g)"

if [ "$current_uid" != "$workspace_uid" ] || [ "$current_gid" != "$workspace_gid" ]; then
  cat >&2 <<EOF
UID-GUARD: mismatch detected.
container uid/gid: ${current_uid}:${current_gid}
workspace uid/gid: ${workspace_uid}:${workspace_gid}
workspace: ${repo}

Refusing to run devcontainer lifecycle command because this would create host files
owned by the wrong UID/GID and break host-side git/omnipull.
EOF
  exit 67
fi

echo "UID-GUARD: ok uid/gid=${current_uid}:${current_gid} workspace=${repo}"
