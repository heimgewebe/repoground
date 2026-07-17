#!/usr/bin/env python3
"""Fail-closed checks for RepoGround identity and distribution decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IDENTITY = Path("docs/decisions/repoground-3-naming-and-migration.v1.json")
LICENSE_DECISION = Path("docs/decisions/repoground-public-license-decision.v1.json")
THIRD_PARTY = Path("docs/release/third-party-license-review.v1.json")
ALLOWED_METADATA_STATUSES = {
    "identified",
    "metadata_ambiguous",
    "metadata_unresolved",
}


def check(root: Path) -> list[str]:
    """Return decision drift findings for a repository root."""

    findings: list[str] = []
    identity = json.loads((root / IDENTITY).read_text(encoding="utf-8"))
    license_decision = json.loads(
        (root / LICENSE_DECISION).read_text(encoding="utf-8")
    )
    third_party = json.loads((root / THIRD_PARTY).read_text(encoding="utf-8"))
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    naming_text = (root / "docs/architecture/naming.md").read_text(encoding="utf-8")
    release_policy = (root / "docs/release/release-policy.md").read_text(
        encoding="utf-8"
    )

    if identity.get("decision") != "adopt_repoground_for_3_x":
        findings.append("RepoGround identity decision changed")
    if (
        identity.get("repository_target_name") != "repoground"
        or identity.get("python_namespace") != "merger.repoground"
        or identity.get("product_name") != "RepoGround"
        or identity.get("primary_cli_name") != "repoground"
    ):
        findings.append("RepoGround identity mismatch")
    compatibility = identity.get("compatibility") or {}
    if (
        compatibility.get("legacy_python_namespace") != "merger.lenskit"
        or compatibility.get("persisted_2_x_identifiers_reinterpreted") is not False
    ):
        findings.append("compatibility boundary drift")
    if "RepoGround" not in naming_text or "merger.repoground" not in naming_text:
        findings.append("naming document drift")

    expression = license_decision.get("current_license_expression")
    if expression != "LicenseRef-RepoGround-All-Rights-Reserved":
        findings.append("license expression changed")
    if expression not in license_text:
        findings.append("LICENSE does not match decision")
    if (
        license_decision.get("distribution_status")
        != "blocked_without_separate_written_permission"
    ):
        findings.append("public distribution unexpectedly enabled")

    normalized_policy = release_policy.casefold()
    if (
        "does not grant distribution permission" not in normalized_policy
        or "not upload or publish" not in normalized_policy
    ):
        findings.append("release policy distribution must remain blocked")

    summary = third_party.get("summary") or {}
    packages = third_party.get("packages") or []
    if summary.get("package_count") != len(packages) or not packages:
        findings.append("third-party inventory count mismatch")
    for item in packages:
        if not item.get("name") or not item.get("version"):
            findings.append("third-party package identity incomplete")
        if item.get("metadata_status") not in ALLOWED_METADATA_STATUSES:
            findings.append(f"invalid metadata status: {item.get('name')}")
    if (
        third_party.get("distribution_boundary", {}).get(
            "public_distribution_allowed"
        )
        is not False
    ):
        findings.append("third-party review must not authorize publication")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    findings = check(args.root.resolve())
    report = {
        "kind": "repoground.identity_distribution_decision_check",
        "version": "1.0",
        "status": "pass" if not findings else "fail",
        "findings": findings,
    }
    if args.format == "json":
        print(json.dumps(report, indent=2))
    elif findings:
        print("\n".join(findings))
    else:
        print("Identity/distribution decisions: pass")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
