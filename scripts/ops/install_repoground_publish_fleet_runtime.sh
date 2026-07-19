#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
BIN_DIR=${HOME}/.local/bin
UNIT_DIR=${HOME}/.config/systemd/user
ENABLE=0
OLD_STATE_ROOT=${HOME}/.local/state/repobrief-publish/fleet
STATE_ROOT=${HOME}/.local/state/repoground-publish/fleet
LOG_ROOT=${HOME}/logs/repoground-publish

if [[ ${1:-} == "--enable" ]]; then
  ENABLE=1
elif [[ $# -gt 0 ]]; then
  echo "usage: $0 [--enable]" >&2
  exit 2
fi

OLD_TIMERS=(
  rb-publish-fleet-watch.timer
  rb-publish-fleet-daily.timer
  repobrief-publish-systemkatalog-main-watch.timer
  repobrief-publish-systemkatalog-main.timer
  systemkatalog-repobrief-localize.timer
  systemkatalog-repobrief-localize.path
)
OLD_UNITS=(
  rb-publish-fleet-watch.service
  rb-publish-fleet-daily.service
  rb-publish-fleet-daily.timer
  repobrief-publish-systemkatalog-main-watch.service
  repobrief-publish-systemkatalog-main-watch.timer
  repobrief-publish-systemkatalog-main.service
  repobrief-publish-systemkatalog-main.timer
)

install -d -m 0755 "$BIN_DIR" "$UNIT_DIR"
systemctl --user disable --now repoground-publish-fleet-watch.timer 2>/dev/null || true
systemctl --user stop repoground-publish-fleet-watch.service 2>/dev/null || true
for unit in "${OLD_TIMERS[@]}"; do
  systemctl --user disable --now "$unit" 2>/dev/null || true
done

if [[ -L $OLD_STATE_ROOT || -L $STATE_ROOT ]]; then
  echo "publisher state roots must not be symlinks" >&2
  exit 1
fi
if [[ -e $OLD_STATE_ROOT && ! -d $OLD_STATE_ROOT ]]; then
  echo "old publisher state root is not a directory: $OLD_STATE_ROOT" >&2
  exit 1
fi
if [[ -e $STATE_ROOT && ! -d $STATE_ROOT ]]; then
  echo "RepoGround publisher state root is not a directory: $STATE_ROOT" >&2
  exit 1
fi
if [[ -d $OLD_STATE_ROOT && -d $STATE_ROOT ]]; then
  echo "both old and RepoGround publisher state roots exist; refusing dual truth" >&2
  exit 1
fi
if [[ -d $OLD_STATE_ROOT ]]; then
  install -d -m 0755 "$(dirname "$STATE_ROOT")"
  mv -- "$OLD_STATE_ROOT" "$STATE_ROOT"
fi
install -d -m 0755 "$STATE_ROOT" "$LOG_ROOT"

install -m 0755 "$ROOT/scripts/ops/repoground-publish-fleet" "$BIN_DIR/repoground-publish-fleet"
install -m 0755 "$ROOT/scripts/ops/repoground-publication-policy" "$BIN_DIR/repoground-publication-policy"
install -m 0755 "$ROOT/scripts/ops/repoground-publish-systemkatalog-main" \
  "$BIN_DIR/repoground-publish-systemkatalog-main"
install -m 0755 "$ROOT/scripts/ops/repoground-publish-systemkatalog-main-if-changed" \
  "$BIN_DIR/repoground-publish-systemkatalog-main-if-changed"
for unit in "$ROOT"/ops/systemd/repoground-fleet/*.{service,timer}; do
  install -m 0644 "$unit" "$UNIT_DIR/$(basename "$unit")"
done
for unit in "${OLD_TIMERS[@]}" "${OLD_UNITS[@]}"; do
  rm -f -- "$UNIT_DIR/$unit"
done

systemctl --user daemon-reload
for unit in "${OLD_TIMERS[@]}" "${OLD_UNITS[@]}"; do
  systemctl --user reset-failed "$unit" 2>/dev/null || true
done
systemctl --user reset-failed repoground-publish-fleet-watch.service 2>/dev/null || true
if (( ENABLE )); then
  systemctl --user enable --now repoground-publish-fleet-watch.timer
  echo "INSTALL-REPOGROUND-PUBLISH-FLEET-RUNTIME: PASS enabled"
else
  systemctl --user disable --now repoground-publish-fleet-watch.timer 2>/dev/null || true
  echo "INSTALL-REPOGROUND-PUBLISH-FLEET-RUNTIME: PASS paused"
fi
