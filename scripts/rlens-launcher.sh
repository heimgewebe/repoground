#!/bin/bash
set -euo pipefail
echo "[repoground] rlens-launcher.sh is deprecated; use repoground-launcher.sh" >&2
exec "$(dirname "$0")/repoground-launcher.sh" "$@"
