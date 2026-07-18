#!/bin/bash
set -euo pipefail

# Canonical RepoGround launcher (systemd wrapper).
# It validates the API contract, authentication boundary and running version.
HOST=${REPOGROUND_HOST:-${RLENS_HOST:-127.0.0.1}}
PORT=${REPOGROUND_PORT:-${RLENS_PORT:-8787}}
URL="http://${HOST}:${PORT}"
HEALTH_URL="${URL}/api/health"
UNIT=${REPOGROUND_SERVICE_UNIT:-repoground}
MAX_RETRIES=${REPOGROUND_HEALTH_RETRIES:-30}
RETRY_INTERVAL=${REPOGROUND_HEALTH_INTERVAL:-0.5}
HEALTH_FILE=$(mktemp)
trap 'rm -f "$HEALTH_FILE"' EXIT

echo "[repoground] Starting service via systemd..."
systemctl --user start "$UNIT"

if ! systemctl --user is-active --quiet "$UNIT"; then
    echo "[repoground] Warning: Service unit is not active immediately after start." >&2
fi

expected_server_version() {
    if [[ -n "${REPOGROUND_EXPECTED_VERSION:-}" ]]; then
        printf '%s\n' "$REPOGROUND_EXPECTED_VERSION"
        return 0
    fi

    local pid
    pid=$(systemctl --user show "$UNIT" --property=MainPID --value 2>/dev/null || true)
    if [[ "$pid" =~ ^[1-9][0-9]*$ ]] && [[ -r "/proc/${pid}/environ" ]]; then
        local process_version
        process_version=$(
            tr '\0' '\n' <"/proc/${pid}/environ" |
                sed -n -e 's/^REPOGROUND_VERSION=//p' -e 's/^RLENS_VERSION=//p' |
                head -n 1
        )
        if [[ -n "$process_version" ]]; then
            printf '%s\n' "$process_version"
            return 0
        fi
    fi

    local workdir
    workdir=$(systemctl --user show "$UNIT" --property=WorkingDirectory --value 2>/dev/null || true)
    if [[ -n "$workdir" ]] && git -C "$workdir" rev-parse HEAD >/dev/null 2>&1; then
        git -C "$workdir" rev-parse HEAD
        return 0
    fi
    return 1
}

validate_health_payload() {
    local expected_version=$1
    python3 - "$HEALTH_FILE" "$expected_version" <<'PY_VALIDATE'
import json
import re
import sys
from pathlib import Path


def versions_match(expected: str, actual: str) -> bool:
    if actual == expected:
        return True

    expected_lower = expected.lower()
    actual_lower = actual.lower()
    sha_pattern = re.compile(r"[0-9a-f]{7,40}")
    if not sha_pattern.fullmatch(expected_lower):
        return False
    if not sha_pattern.fullmatch(actual_lower):
        return False

    shorter, longer = sorted((expected_lower, actual_lower), key=len)
    return longer.startswith(shorter)


payload_path = Path(sys.argv[1])
expected = sys.argv[2].strip()
try:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError):
    raise SystemExit(1)

if not isinstance(payload, dict) or payload.get("status") != "ok":
    raise SystemExit(1)
if not isinstance(payload.get("version"), str) or not payload["version"]:
    raise SystemExit(1)
actual = payload.get("server_version")
if not isinstance(actual, str) or not actual or not expected:
    raise SystemExit(1)
if not versions_match(expected, actual):
    raise SystemExit(1)
if not isinstance(payload.get("hub"), str) or not payload["hub"]:
    raise SystemExit(1)
if payload.get("auth_enabled") is not True:
    raise SystemExit(1)
PY_VALIDATE
}

echo "[repoground] Waiting for verified health at ${HEALTH_URL} ..."
for ((i=1; i<=MAX_RETRIES; i++)); do
    expected_version=$(expected_server_version || true)
    if [[ -n "$expected_version" ]] &&
        curl -fsS "$HEALTH_URL" -o "$HEALTH_FILE" &&
        validate_health_payload "$expected_version"; then
        echo "[repoground] Service is HEALTHY and version-bound."
        echo "[repoground] URL: ${URL}"
        if command -v xdg-open >/dev/null; then
            echo "[repoground] Opening browser..."
            xdg-open "${URL}" || true
        fi
        exit 0
    fi
    sleep "$RETRY_INTERVAL"
done

echo "[repoground] ERROR: Verified health check failed after ${MAX_RETRIES} attempts." >&2
echo "--- Unit Status ---" >&2
systemctl --user status "$UNIT" --no-pager >&2 || true
echo "--- Unit Definition ---" >&2
systemctl --user cat "$UNIT" >&2 || true
echo "--- Recent Logs ---" >&2
journalctl --user -u "$UNIT" -n 50 --no-pager >&2 || true
exit 1
