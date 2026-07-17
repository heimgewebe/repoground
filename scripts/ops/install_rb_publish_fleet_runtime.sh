#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' 'install_rb_publish_fleet_runtime.sh is deprecated; use install_repoground_publish_fleet_runtime.sh' >&2
exec "$(dirname "$0")/install_repoground_publish_fleet_runtime.sh" "$@"
