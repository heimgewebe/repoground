#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
BIN_DIR=${HOME}/.local/bin
UNIT_DIR=${HOME}/.config/systemd/user
NEW_BASE=repobrief-publish-systemkatalog-main
OLD_BASE=repobrief-publish-heimgewebe-katalog-main
NEW_TIMERS=("$NEW_BASE-watch.timer" "$NEW_BASE.timer")
OLD_TIMERS=("$OLD_BASE-watch.timer" "$OLD_BASE.timer")
OLD_UNITS=("$OLD_BASE.service" "$OLD_BASE.timer" "$OLD_BASE-watch.service" "$OLD_BASE-watch.timer")

install -d -m 0755 "$BIN_DIR" "$UNIT_DIR"

for unit in "${NEW_TIMERS[@]}" "${OLD_TIMERS[@]}"; do
  systemctl --user stop "$unit" 2>/dev/null || true
done
for unit in "${OLD_TIMERS[@]}"; do
  systemctl --user disable "$unit" 2>/dev/null || true
done

install -m 0755 "$ROOT/scripts/ops/$NEW_BASE" "$BIN_DIR/$NEW_BASE"
install -m 0755 "$ROOT/scripts/ops/$NEW_BASE-if-changed" "$BIN_DIR/$NEW_BASE-if-changed"
for unit in "$ROOT"/ops/systemd/systemkatalog-publish/*.{service,timer}; do
  install -m 0644 "$unit" "$UNIT_DIR/$(basename "$unit")"
done

rm -f -- "$BIN_DIR/$OLD_BASE" "$BIN_DIR/$OLD_BASE-if-changed"
for unit in "${OLD_UNITS[@]}"; do
  rm -f -- "$UNIT_DIR/$unit"
done

systemctl --user daemon-reload
for unit in "$OLD_BASE.service" "$OLD_BASE-watch.service"; do
  systemctl --user reset-failed "$unit" 2>/dev/null || true
done
for unit in "${NEW_TIMERS[@]}"; do
  systemctl --user enable --now "$unit"
done

echo "INSTALL-SYSTEMKATALOG-PUBLISH-RUNTIME: PASS"
