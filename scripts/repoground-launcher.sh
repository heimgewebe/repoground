#!/bin/bash
set -euo pipefail

# Canonical RepoGround Launcher (Systemd Wrapper)
# Wraps systemctl with robust health checks.
# Intended to be installed as ~/.local/bin/repoground.

HOST=${REPOGROUND_HOST:-${RLENS_HOST:-127.0.0.1}}
PORT=${REPOGROUND_PORT:-${RLENS_PORT:-8787}}
URL="http://${HOST}:${PORT}"

# 1. Start Service
echo "[repoground] Starting service via systemd..."
systemctl --user start repoground

# Check if unit is actually active (fast fail)
if ! systemctl --user is-active --quiet repoground; then
    echo "[repoground] Warning: Service unit is not active immediately after start." >&2
fi

# 2. Wait for Health (Retry Loop)
# 30 retries * 0.5s = ~15s timeout (generous for python imports on slow machines)
echo "[repoground] Waiting for health check at ${URL}/health ..."
MAX_RETRIES=30
for ((i=1; i<=MAX_RETRIES; i++)); do
    if curl -sf "${URL}/health" >/dev/null; then
        echo "[repoground] Service is HEALTHY."
        echo "[repoground] URL: ${URL}"

        # Optional: Open Browser
        if command -v xdg-open >/dev/null; then
            echo "[repoground] Opening browser..."
            xdg-open "${URL}" || true
        fi

        exit 0
    fi
    sleep 0.5
done

# 3. Failure Handler
echo "[repoground] ERROR: Health check failed after startup (${MAX_RETRIES} attempts)." >&2
echo "[repoground] Dumping diagnostic info:" >&2

echo "--- Unit Status ---" >&2
systemctl --user status repoground --no-pager >&2 || true

echo "--- Unit Definition ---" >&2
systemctl --user cat repoground >&2 || true

echo "--- Recent Logs ---" >&2
journalctl --user -u repoground -n 50 --no-pager >&2 || true

exit 1
