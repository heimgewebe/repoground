#!/usr/bin/env python3
"""Fail-closed checks for RepoBrief naming and distribution decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = Path("docs/decisions/repobrief-package-namespace-decision.v1.json")
LICENSE_DECISION = Path("docs/decisions/repobrief-public-license-decision.v1.json")
THIRD_PARTY = Path("docs/release/third-party-license-review.v1.json")
ALLOWED_METADATA_STATUSES = {
    "identified",
    "metadata_ambiguous",
    "metadata_unresolved",
}


def check(root: Path) -> list[str]:
    """Return decision drift findings for a repository root."""

    findings: list[str] = []
    namespace = json.loads((root / NAMESPACE).read_text(encoding="utf-8"))
    license_decision = json.loads(
        (root / LICENSE_DECISION).read_text(encoding="utf-8")
    )
    third_party = json.loads((root / THIRD_PARTY).read_text(encoding="utf-8"))
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    naming_text = (root / "docs/architecture/naming.md").read_text(encoding="utf-8")
    release_policy = (root / "docs/release/release-policy.md").read_text(
        encoding="utf-8"
    )

    if namespace.get("decision") != "keep_lenskit_namespace_for_2_x":
        findings.append("namespace decision changed")
    if (
        namespace.get("python_namespace") != "merger.lenskit"
        or namespace.get("product_name") != "RepoBrief"
    ):
        findings.append("namespace identity mismatch")
    inventory = namespace.get("consumer_inventory") or {}
    if int(inventory.get("local_merger_lenskit_occurrences", 0)) < 1:
        findings.append("consumer inventory missing")
    if "RepoBrief" not in naming_text or "merger.lenskit" not in naming_text:
        findings.append("naming document drift")

    expression = license_decision.get("current_license_expression")
    if expression != "LicenseRef-RepoBrief-All-Rights-Reserved":
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
        "kind": "repobrief.identity_distribution_decision_check",
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
