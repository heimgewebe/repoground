#!/bin/bash
set -euo pipefail
echo "[repoground] rlens-post-merge-surface-smoke.sh is deprecated; use repoground-post-merge-surface-smoke.sh" >&2
exec "$(dirname "$0")/repoground-post-merge-surface-smoke.sh" "$@"
