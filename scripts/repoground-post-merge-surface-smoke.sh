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
#   - known scratch-noise paths from TASK-NOISE-001 do not leak as
#     structured file/chunk/index paths
#   - output_health and post_emit_health expose noise-hygiene diagnostics
#
# Usage:  bash scripts/repoground-post-merge-surface-smoke.sh [MERGES_DIR]
# Default MERGES_DIR: $HOME/repoground-out (override with REPOGROUND_MERGES).
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

MANIFEST="$(python3 - "$MERGES_DIR" <<'PY'
import sys
from pathlib import Path

from merger.repoground.core.bundle_generation import (
    BundleGenerationError,
    resolve_bundle_manifest_path,
)

root = Path(sys.argv[1])
current_root = root / ".repobrief-generations"
current = []
pointer_seen = False
if current_root.is_dir():
    for lane in sorted(current_root.iterdir()):
        if not lane.is_dir() or not lane.name.endswith("_merge"):
            continue
        current_link = lane / "current"
        current_json = lane / "current.json"
        if current_link.is_symlink():
            pointer_seen = True
            current.extend(
                path
                for path in current_link.glob("*_merge.bundle.manifest.json")
                if path.is_file()
            )
            continue
        if current_link.exists():
            raise SystemExit(f"FAILED: unexpected current pointer type: {current_link}")
        if current_json.exists() or current_json.is_symlink():
            pointer_seen = True
            try:
                resolved = resolve_bundle_manifest_path(current_json)
            except (BundleGenerationError, OSError, ValueError) as exc:
                raise SystemExit(f"FAILED: invalid current.json pointer: {current_json}: {exc}") from exc
            if resolved.name.endswith("_merge.bundle.manifest.json") and resolved.is_file():
                current.append(resolved)
if pointer_seen and not current:
    raise SystemExit("FAILED: generation pointer exists but no valid current merge manifest resolved")
legacy = [path for path in root.glob("*_merge.bundle.manifest.json") if path.is_file()]
candidates = current or legacy
if candidates:
    print(max(candidates, key=lambda item: item.stat().st_mtime_ns))
PY
)"
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

python3 - "$MANIFEST" <<'PY'
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, List, Tuple

manifest_path = Path(sys.argv[1])
data = json.loads(manifest_path.read_text(encoding="utf-8"))
base = manifest_path.parent
needle = ".tmp/forensic-preflight-ci-canary"

structured_roles = {
    "canonical_md",
    "index_sidecar_json",
    "chunk_index_jsonl",
    "agent_reading_pack",
    "dump_index_json",
}
json_roles = {"index_sidecar_json", "dump_index_json"}
path_keys = {
    "path",
    "file_path",
    "rel_path",
    "source_path",
    "source_file",
    "canonical_path",
    "canonical_file_path",
}

by_role = {artifact.get("role"): artifact for artifact in data.get("artifacts", [])}


def _artifact_path(role: str) -> Path | None:
    artifact = by_role.get(role)
    if not artifact:
        return None
    rel = artifact.get("path")
    if not isinstance(rel, str):
        raise SystemExit(f"FAILED: {role} artifact has no string path")
    path = base / rel if not Path(rel).is_absolute() else Path(rel)
    if not path.is_file():
        raise SystemExit(f"FAILED: {role} artifact missing on disk: {path}")
    return path


def _is_noise_path(value: str) -> bool:
    cleaned = value.replace("\\", "/").strip().strip("`'\"")
    cleaned = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", cleaned)
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    for idx, part in enumerate(parts[:-1]):
        if part == ".tmp" and parts[idx + 1] == "forensic-preflight-ci-canary":
            return True
    return False


def _path_values_from_json(value: Any, context: str = "") -> Iterable[Tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_context = f"{context}.{key}" if context else str(key)
            key_l = str(key).lower()
            if isinstance(child, str) and (key_l in path_keys or key_l.endswith("_path")):
                yield child_context, child
            elif isinstance(child, list) and key_l in {"files", "file_index", "md_parts", "artifacts", "chunks"}:
                for idx, item in enumerate(child):
                    yield from _path_values_from_json(item, f"{child_context}[{idx}]")
            else:
                yield from _path_values_from_json(child, child_context)
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            yield from _path_values_from_json(item, f"{context}[{idx}]")


def _check_json_artifact(role: str, path: Path, failures: List[str]) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    for context, candidate in _path_values_from_json(doc):
        if _is_noise_path(candidate):
            failures.append(f"{role}:{context}={candidate}")


def _check_jsonl_artifact(role: str, path: Path, failures: List[str]) -> None:
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"FAILED: {role} has invalid JSONL at {path}:{line_no}: {exc}") from exc
        for context, candidate in _path_values_from_json(doc):
            if _is_noise_path(candidate):
                failures.append(f"{role}:line {line_no}:{context}={candidate}")


def _extract_backtick_value(line: str) -> str | None:
    match = re.search(r"`([^`]+)`", line)
    return match.group(1) if match else None


def _check_canonical_markers(role: str, path: Path, failures: List[str]) -> None:
    in_fence = False
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        candidates: List[str] = []
        if "<!-- FILE_START" in line or "<!-- file:id=" in line or "<!-- FILE_END" in line:
            candidates.extend(re.findall(r'\bpath="([^"]+)"', line))
        elif stripped.startswith("| [`"):
            value = _extract_backtick_value(line)
            if value is not None:
                candidates.append(value)
        elif stripped.startswith("**Path:**"):
            value = _extract_backtick_value(line)
            if value is not None:
                candidates.append(value)

        for candidate in candidates:
            if _is_noise_path(candidate):
                failures.append(f"{role}:line {line_no}={candidate}")


def _check_agent_pack_path_tables(role: str, path: Path, failures: List[str]) -> None:
    in_top_chunk_spans = False
    in_table = False
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("## "):
            in_top_chunk_spans = stripped.startswith("## TOP_CHUNK_SPANS")
            in_table = False
            continue
        if not in_top_chunk_spans:
            continue
        if stripped.startswith("| file |"):
            in_table = True
            continue
        if in_table and stripped.startswith("| ---"):
            continue
        if in_table and stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if cells:
                candidate = cells[0].strip("`")
                if _is_noise_path(candidate):
                    failures.append(f"{role}:line {line_no}={candidate}")
            continue
        if in_table and stripped == "":
            in_table = False


path_failures: List[str] = []
for role in sorted(structured_roles):
    path = _artifact_path(role)
    if path is None:
        continue
    if role in json_roles:
        _check_json_artifact(role, path, path_failures)
    elif role == "chunk_index_jsonl":
        _check_jsonl_artifact(role, path, path_failures)
    elif role == "canonical_md":
        _check_canonical_markers(role, path, path_failures)
    elif role == "agent_reading_pack":
        _check_agent_pack_path_tables(role, path, path_failures)

if path_failures:
    raise SystemExit("FAILED: scratch noise leaked as structured path(s): " + "; ".join(path_failures[:20]))

oh_entry = by_role.get("output_health")
if not oh_entry:
    raise SystemExit("FAILED: output_health missing")
oh_rel = oh_entry.get("path")
if not isinstance(oh_rel, str):
    raise SystemExit("FAILED: output_health artifact has no string path")
oh_path = base / oh_rel if not Path(oh_rel).is_absolute() else Path(oh_rel)
oh = json.loads(oh_path.read_text(encoding="utf-8"))
checks = oh.get("checks") if isinstance(oh.get("checks"), dict) else {}
excluded = checks.get("excluded_noise")
noise = checks.get("noise_hygiene")
if not isinstance(excluded, dict):
    raise SystemExit("FAILED: output_health checks.excluded_noise missing")
if not isinstance(noise, dict):
    raise SystemExit("FAILED: output_health checks.noise_hygiene missing")

if "count" not in excluded:
    raise SystemExit("FAILED: output_health checks.excluded_noise.count missing")
excluded_count = excluded["count"]
if type(excluded_count) is not int:
    raise SystemExit("FAILED: output_health checks.excluded_noise.count is not an integer")
if noise.get("available") is not True:
    raise SystemExit("FAILED: output_health noise_hygiene.available is not true")
noise_count = noise.get("excluded_noise_count")
if type(noise_count) is not int:
    raise SystemExit("FAILED: output_health noise_hygiene.excluded_noise_count is not an integer")
if noise_count != excluded_count:
    raise SystemExit("FAILED: output_health noise_hygiene.excluded_noise_count does not match excluded_noise.count")

post_rel = data.get("links", {}).get("post_emit_health_path")
if not post_rel:
    raise SystemExit("FAILED: post_emit_health_path missing")
post_path = base / post_rel if not Path(post_rel).is_absolute() else Path(post_rel)
post = json.loads(post_path.read_text(encoding="utf-8"))
post_noise = post.get("noise_hygiene")
if not isinstance(post_noise, dict):
    raise SystemExit("FAILED: post_emit_health.noise_hygiene missing")
if post_noise.get("available") is not True:
    raise SystemExit("FAILED: post_emit_health.noise_hygiene.available is not true")
post_count = post_noise.get("excluded_noise_count")
if type(post_count) is not int:
    raise SystemExit("FAILED: post_emit_health.noise_hygiene.excluded_noise_count is not an integer")
if post_count != excluded_count:
    raise SystemExit("FAILED: post_emit_health.noise_hygiene.excluded_noise_count does not match output_health excluded_noise.count")

print(json.dumps({
    "noise_surface_check": "pass",
    "structured_path_absent": needle,
    "checked_roles": sorted(role for role in structured_roles if role in by_role),
    "excluded_noise_count": excluded_count,
    "output_health_noise_available": noise.get("available"),
    "post_emit_health_noise_available": post_noise.get("available"),
}, indent=2))
PY

echo "OK: latest dump carries runtime + surface fields, no legacy claim-map placeholder, and noise hygiene diagnostics."
