#!/usr/bin/env bash
# rlens post-merge surface smoke (TASK-SERVICE-001)
#
# Reads the most recent `*_merge.bundle.manifest.json` under $MERGES_DIR and asserts
# the surface fields a freshly-restarted rlens service MUST emit:
#   - generator.runtime
#   - links.post_emit_health_path
#   - links.bundle_surface_validation_path
#   - links.bundle_surface_validation_status
#   - claim_evidence_map_json role OR claim_evidence_map_absence_reason
#   - both linked sidecars exist on disk
#   - sidecar status matches the manifest link
#   - agent reading pack does NOT contain the legacy
#     "claim_evidence_map is not yet produced" placeholder
#
# Usage:  bash scripts/rlens-post-merge-surface-smoke.sh [MERGES_DIR]
# Default MERGES_DIR: $HOME/lenskit-out  (matches RLENS_MERGES in docs/systemd/rlens.service)
#
# Exits non-zero on the first failed check. Prints a JSON snapshot of the inspected
# manifest so the result is greppable in CI logs and easy to copy into a proof.
set -euo pipefail

MERGES_DIR="${1:-$HOME/lenskit-out}"
# Default-Verhalten: ein frisch-restarteter rlens-Dump muss surface_status="pass" haben.
# Auf "warn" setzen ist nur für forensic_strict-Szenarien sinnvoll, in denen ein
# warn-Verdikt explizit als "nicht OK" markiert werden soll.
REQUIRE_SURFACE_STATUS="${REQUIRE_SURFACE_STATUS:-pass}"

if [[ ! -d "$MERGES_DIR" ]]; then
  echo "FAILED: merges directory not found: $MERGES_DIR" >&2
  exit 2
fi

# shellcheck disable=SC2012
MANIFEST="$(ls -1t "$MERGES_DIR"/*_merge.bundle.manifest.json 2>/dev/null | head -1 || true)"
if [[ -z "$MANIFEST" || ! -f "$MANIFEST" ]]; then
  echo "FAILED: no *_merge.bundle.manifest.json found under $MERGES_DIR" >&2
  echo "       (erst nach 'systemctl --user restart rlens' und einem neuen Dump suchen)" >&2
  exit 2
fi
echo "MANIFEST=$MANIFEST"
stat -c 'manifest_mtime=%y' "$MANIFEST"

python3 - "$MANIFEST" <<'PY'
import json
import os
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
data = json.loads(manifest_path.read_text(encoding="utf-8"))

roles = {a.get("role") for a in data.get("artifacts", [])}
links = data.get("links", {})
generator = data.get("generator", {})

require_status = os.environ.get("REQUIRE_SURFACE_STATUS", "pass")
status = links.get("bundle_surface_validation_status")

checks = {
    "generator.runtime": "runtime" in generator,
    "links.post_emit_health_path": bool(links.get("post_emit_health_path")),
    "links.bundle_surface_validation_path": bool(links.get("bundle_surface_validation_path")),
    f"links.bundle_surface_validation_status=={require_status}": status == require_status,
    "claim_evidence_map_or_absence_reason": (
        "claim_evidence_map_json" in roles
        or bool(links.get("claim_evidence_map_absence_reason"))
    ),
}

print(json.dumps({
    "manifest": str(manifest_path),
    "require_surface_status": require_status,
    "generator_keys": sorted(generator.keys()),
    "runtime": generator.get("runtime"),
    "links": links,
    "claim_map_present": "claim_evidence_map_json" in roles,
    "surface_status": status,
    "checks": checks,
}, indent=2))

failed = [k for k, v in checks.items() if not v]
if failed:
    raise SystemExit("FAILED surface checks: " + ", ".join(failed))
PY

python3 - "$MANIFEST" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
data = json.loads(manifest_path.read_text(encoding="utf-8"))
base = manifest_path.parent
links = data.get("links", {})

for key in ("post_emit_health_path", "bundle_surface_validation_path"):
    rel = links.get(key)
    if not rel:
        raise SystemExit(f"missing {key}")
    p = base / rel
    print(f"{key}: exists={p.exists()} path={p}")
    if not p.exists():
        raise SystemExit(f"linked sidecar missing: {p}")

surface = base / links["bundle_surface_validation_path"]
report = json.loads(surface.read_text(encoding="utf-8"))
if report.get("status") != links.get("bundle_surface_validation_status"):
    raise SystemExit("surface status mismatch between manifest and sidecar")

# Agent Reading Pack-Pfad aus der Manifest-Rolle ableiten (kein
# Dateinamen-Pattern, sondern der echte Contract).
pack_paths = [
    a.get("path")
    for a in data.get("artifacts", [])
    if a.get("role") == "agent_reading_pack"
]
if not pack_paths:
    raise SystemExit("FAILED: manifest has no agent_reading_pack artifact (rolle fehlt im artifacts-Array)")

pack_rel = pack_paths[0]
pack_path = base / pack_rel if not Path(pack_rel).is_absolute() else Path(pack_rel)
print(f"agent_reading_pack: role_lookup=true rel={pack_rel} exists={pack_path.exists()}")
if not pack_path.is_file():
    raise SystemExit(f"FAILED: Agent Reading Pack missing on disk: {pack_path}")

legacy = "claim_evidence_map is not yet produced"
if legacy in pack_path.read_text(encoding="utf-8"):
    raise SystemExit(f"FAILED: Agent Pack enthält noch Legacy-Leerstelle: {legacy!r}")

print(f"pack_check: legacy_placeholder_absent=true path={pack_path}")
PY

echo "OK: latest dump carries runtime + surface fields and no legacy claim-map placeholder."
