#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
BIN_DIR=${HOME}/.local/bin
UNIT_DIR=${HOME}/.config/systemd/user

install -d -m 0755 "$BIN_DIR" "$UNIT_DIR"
install -m 0755 "$ROOT/scripts/ops/repobrief-publish-heimgewebe-katalog-main" "$BIN_DIR/repobrief-publish-heimgewebe-katalog-main"
install -m 0755 "$ROOT/scripts/ops/repobrief-publish-heimgewebe-katalog-main-if-changed" "$BIN_DIR/repobrief-publish-heimgewebe-katalog-main-if-changed"
for unit in "$ROOT"/ops/systemd/systemkatalog-publish/*.{service,timer}; do
  install -m 0644 "$unit" "$UNIT_DIR/$(basename "$unit")"
done
systemctl --user daemon-reload
systemctl --user enable --now repobrief-publish-heimgewebe-katalog-main-watch.timer
systemctl --user enable --now repobrief-publish-heimgewebe-katalog-main.timer
