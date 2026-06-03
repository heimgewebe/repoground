#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
keep="${LENSKIT_FORENSIC_CALIBRATION_KEEP:-0}"

# Determine workdir and track the directory that this harness owns (and may delete).
# When the caller supplies LENSKIT_FORENSIC_CALIBRATION_WORKDIR we create a scoped
# child directory inside it and never delete the caller-supplied parent.
_caller_supplied_workdir="${LENSKIT_FORENSIC_CALIBRATION_WORKDIR:-}"
_owned_workdir=""

if [[ -n "${_caller_supplied_workdir}" ]]; then
  mkdir -p "${_caller_supplied_workdir}"
  _base="$(cd "${_caller_supplied_workdir}" && pwd)"
  # Safety guard: refuse empty, filesystem root, or repo-root paths.
  if [[ -z "${_base}" || "${_base}" == "/" || "${_base}" == "${repo_root}" ]]; then
    echo "ERROR: LENSKIT_FORENSIC_CALIBRATION_WORKDIR '${_caller_supplied_workdir}' is a forbidden path (empty, /, or repo root)." >&2
    exit 1
  fi
  # Create a scoped child so cleanup never touches the caller-supplied parent.
  workdir="${_base}/lenskit-calibration-$$"
  mkdir -p "${workdir}"
  _owned_workdir="${workdir}"
else
  workdir="$(mktemp -d)"
  _owned_workdir="${workdir}"
fi

cleanup() {
  if [[ "${keep}" != "1" && -n "${_owned_workdir}" && -d "${_owned_workdir}" ]]; then
    rm -rf -- "${_owned_workdir}"
  fi
}
trap cleanup EXIT

cd "${repo_root}"

python3 - <<'PY' "${repo_root}" "${workdir}"
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from merger.lenskit.core.merge import ExtrasConfig, scan_repo, write_reports_v2
from merger.lenskit.core.post_emit_health import derive_post_health_path, write_post_emit_health

REQUIRED_ROLES = {
    "canonical_md",
    "chunk_index_jsonl",
    "citation_map_jsonl",
    "claim_evidence_map_json",
}

repo_root = Path(sys.argv[1]).resolve()
workdir = Path(sys.argv[2]).resolve()
fixture_repo = workdir / "fixture-repo"
results_dir = workdir / "results"


def _write_fixture_repo() -> None:
    fixture_repo.mkdir(parents=True, exist_ok=True)
    (fixture_repo / "README.md").write_text(
        "# Forensic Calibration Fixture\n\n"
        "This repository is generated locally by the forensic preflight calibration harness.\n",
        encoding="utf-8",
    )
    (fixture_repo / "src").mkdir(exist_ok=True)
    (fixture_repo / "src" / "app.py").write_text(
        "def answer() -> int:\n"
        "    return 42\n",
        encoding="utf-8",
    )
    (fixture_repo / "docs").mkdir(exist_ok=True)
    (fixture_repo / "docs" / "usage.md").write_text(
        "# Usage\n\nCall `answer()` when the fixture needs deterministic source content.\n",
        encoding="utf-8",
    )
    # The single-repo claim_evidence_map is derived from the *scanned* repo's own
    # docs/doc-freshness-registry.yml (core/merge.py). Ship a minimal,
    # schema-valid registry so the positive case actually produces
    # claim_evidence_map_json; without it the map is correctly absent and the
    # positive bundle could never satisfy the forensic_strict prerequisites.
    (fixture_repo / "docs" / "doc-freshness-registry.yml").write_text(
        "kind: lenskit.doc_freshness_registry\n"
        'version: "1.0"\n'
        "authority: diagnostic_signal\n"
        "risk_class: diagnostic\n"
        "does_not_prove:\n"
        '  - "a green verify does not prove docs are complete or correct, only'
        ' that no tracked claim contradicts its declared evidence"\n'
        "entries:\n"
        "  - id: calibration-fixture-app-answer\n"
        "    doc: docs/usage.md\n"
        "    locator: \"section 'Usage'\"\n"
        '    claim: "answer() returns a deterministic result"\n'
        "    status: done\n"
        "    normative: false\n"
        "    owner: forensic-calibration\n"
        '    last_verified: "2026-06-01"\n'
        "    evidence:\n"
        "      - kind: symbol\n"
        '        target: "src/app.py::answer"\n'
        "      - kind: file\n"
        '        target: "docs/usage.md"\n',
        encoding="utf-8",
    )


def _make_real_bundle(label: str) -> Path:
    case_root = workdir / label
    case_repo = case_root / fixture_repo.name
    case_merges = case_root / "merges"
    if case_root.exists():
        shutil.rmtree(case_root)
    case_root.mkdir(parents=True)
    shutil.copytree(fixture_repo, case_repo)
    case_merges.mkdir()

    summary = scan_repo(case_repo, max_bytes=100_000, include_hidden=True)
    artifacts = write_reports_v2(
        case_merges,
        case_root,
        [summary],
        "forensic-calibration",
        "gesamt",
        100_000,
        False,
        split_size=0,
        extras=ExtrasConfig(augment_sidecar=True, json_sidecar=True),
        output_mode="dual",
        redact_secrets=False,
        generator_info={
            "name": "lenskit-forensic-calibration",
            "version": "proof-harness",
            "config_sha256": "7" * 64,
        },
    )
    if artifacts.bundle_manifest is None:
        raise AssertionError("real bundle generation did not return a bundle manifest")
    manifest = artifacts.bundle_manifest.resolve()
    write_post_emit_health(str(manifest))
    return manifest


def _load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _artifact_path(manifest: Path, role: str) -> Path:
    doc = _load_manifest(manifest)
    artifacts = doc.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise AssertionError("manifest artifacts must be a list")
    for artifact in artifacts:
        if isinstance(artifact, dict) and artifact.get("role") == role:
            raw_path = artifact.get("path")
            if not isinstance(raw_path, str) or not raw_path:
                raise AssertionError(f"{role} artifact path missing from manifest")
            return (manifest.parent / raw_path).resolve()
    raise AssertionError(f"{role} missing from manifest")


def _copy_case(source_manifest: Path, label: str) -> Path:
    source_case = source_manifest.parent.parent
    target_case = workdir / label
    if target_case.exists():
        shutil.rmtree(target_case)
    shutil.copytree(source_case, target_case)
    candidates = sorted((target_case / "merges").glob("*.bundle.manifest.json"))
    if len(candidates) != 1:
        raise AssertionError(f"expected one copied manifest for {label}, found {len(candidates)}")
    return candidates[0].resolve()


def _run_preflight(case: str, manifest: Path, *, post_health: Path | None = None) -> dict:
    output_path = results_dir / f"{case}.forensic-preflight.json"
    cmd = [
        sys.executable,
        "-m",
        "merger.lenskit.cli.main",
        "governance",
        "forensic-preflight",
        "--manifest",
        str(manifest),
        "--json",
    ]
    if post_health is not None:
        cmd.extend(["--post-health", str(post_health)])
    proc = subprocess.run(
        cmd,
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.stdout.strip():
        output_path.write_text(proc.stdout, encoding="utf-8")
    if proc.stderr.strip():
        (results_dir / f"{case}.stderr.txt").write_text(proc.stderr, encoding="utf-8")
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{case}: preflight did not emit JSON: {exc}; stderr={proc.stderr!r}") from exc
    report["_cli_exit_code"] = proc.returncode
    return report


def _checks(report: dict) -> dict[str, str]:
    return {item["name"]: item["status"] for item in report.get("checks", [])}


def _post_health_path(manifest: Path) -> Path:
    return derive_post_health_path(manifest)


def main() -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    _write_fixture_repo()

    positive_manifest = _make_real_bundle("positive")
    positive_doc = _load_manifest(positive_manifest)
    positive_roles = {a.get("role") for a in positive_doc.get("artifacts", []) if isinstance(a, dict)}
    missing_roles = sorted(REQUIRED_ROLES - positive_roles)
    if missing_roles:
        raise AssertionError(f"positive real bundle missing required roles: {missing_roles}")
    positive_post_doc = json.loads(_post_health_path(positive_manifest).read_text(encoding="utf-8"))
    if Path(positive_post_doc.get("bundle_manifest_path", "")).resolve() != positive_manifest:
        raise AssertionError("positive post_emit_health is not bound to the generated manifest path")
    if positive_post_doc.get("bundle_run_id") != positive_doc.get("run_id"):
        raise AssertionError("positive post_emit_health is not bound to the generated manifest run_id")

    results: dict[str, dict] = {}
    results["positive"] = _run_preflight("positive", positive_manifest)
    if results["positive"]["status"] not in {"pass", "blocked"}:
        raise AssertionError(f"positive expected pass or environment-blocked, got {results['positive']['status']}")

    missing_claim_manifest = _copy_case(positive_manifest, "missing-claim-map")
    missing_doc = _load_manifest(missing_claim_manifest)
    missing_doc["artifacts"] = [
        a for a in missing_doc.get("artifacts", []) if isinstance(a, dict) and a.get("role") != "claim_evidence_map_json"
    ]
    _write_manifest(missing_claim_manifest, missing_doc)
    write_post_emit_health(str(missing_claim_manifest))
    results["missing_claim_map"] = _run_preflight("missing-claim-map", missing_claim_manifest)
    if results["missing_claim_map"]["status"] != "blocked":
        raise AssertionError("missing claim-map case must be blocked")
    if _checks(results["missing_claim_map"]).get("claim_evidence_map_present") != "blocked":
        raise AssertionError("missing claim-map case did not block claim_evidence_map_present")

    stale_manifest = _copy_case(positive_manifest, "stale-post-health")
    stale_post = _post_health_path(stale_manifest)
    stale_doc = json.loads(stale_post.read_text(encoding="utf-8"))
    stale_doc["bundle_manifest_path"] = str(stale_manifest.parent / "other.bundle.manifest.json")
    stale_doc["bundle_run_id"] = "other-run-id"
    stale_post.write_text(json.dumps(stale_doc, indent=2) + "\n", encoding="utf-8")
    results["stale_post_emit_health"] = _run_preflight("stale-post-health", stale_manifest)
    if results["stale_post_emit_health"]["status"] == "pass":
        raise AssertionError("stale post_emit_health case must never pass")
    if _checks(results["stale_post_emit_health"]).get("post_emit_health_bound_to_manifest") not in {"fail", "blocked"}:
        raise AssertionError("stale post_emit_health case did not flag the binding check")

    drift_manifest = _copy_case(positive_manifest, "hash-drift")
    # Recompute before tampering so this case isolates claim-map hash drift rather than
    # reusing the copied positive case's stale post_emit_health binding.
    write_post_emit_health(str(drift_manifest))
    claim_path = _artifact_path(drift_manifest, "claim_evidence_map_json")
    claim_path.write_text('{"tampered": true}\n', encoding="utf-8")
    results["hash_drift"] = _run_preflight("hash-drift", drift_manifest)
    drift_checks = _checks(results["hash_drift"])
    if results["hash_drift"]["status"] == "pass":
        raise AssertionError("hash drift case must not pass")
    if drift_checks.get("claim_evidence_map_hash_ok") != "fail":
        raise AssertionError("hash drift case did not fail claim_evidence_map_hash_ok")
    if drift_checks.get("claim_evidence_map_schema_valid") not in {"skipped", "blocked"}:
        raise AssertionError("hash drift schema check must be skipped or blocked after hash failure")

    summary = {
        "workdir": str(workdir),
        "positive_manifest": str(positive_manifest),
        "positive_roles": sorted(positive_roles),
        "post_emit_health_bound": True,
        "cases": {
            name: {
                "status": report.get("status"),
                "cli_exit_code": report.get("_cli_exit_code"),
                "checks": _checks(report),
            }
            for name, report in results.items()
        },
    }
    (results_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
PY
