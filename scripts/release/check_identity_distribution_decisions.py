#!/usr/bin/env python3
"""Fail-closed checks for RepoGround identity and distribution decisions."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
IDENTITY = Path("docs/decisions/repoground-3-naming-and-migration.v1.json")
LICENSE_DECISION = Path("docs/decisions/repoground-public-license-decision.v1.json")
THIRD_PARTY = Path("docs/release/third-party-license-review.v1.json")
SOURCE_DISTRIBUTION = Path(
    "docs/release/third-party-source-distribution-review.v1.json"
)
ALLOWED_METADATA_STATUSES = {
    "identified",
    "metadata_ambiguous",
    "metadata_unresolved",
}


def _load_json(root: Path, relative: Path) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {relative}")
    return value


def _check_identity(identity: dict[str, Any], naming_text: str) -> list[str]:
    findings: list[str] = []
    if identity.get("decision") != "adopt_repoground_for_3_x":
        findings.append("RepoGround identity decision changed")

    expected_identity = {
        "repository_target_name": "repoground",
        "python_namespace": "merger.repoground",
        "product_name": "RepoGround",
        "primary_cli_name": "repoground",
    }
    observed_identity = {key: identity.get(key) for key in expected_identity}
    if observed_identity != expected_identity:
        findings.append("RepoGround identity mismatch")

    compatibility = identity.get("compatibility") or {}
    observed_compatibility = (
        compatibility.get("legacy_python_namespace"),
        compatibility.get("persisted_2_x_identifiers_reinterpreted"),
    )
    if observed_compatibility != ("merger.lenskit", False):
        findings.append("compatibility boundary drift")

    required_names = ("RepoGround", "merger.repoground")
    if not all(name in naming_text for name in required_names):
        findings.append("naming document drift")
    return findings


def _check_license_decision(
    decision: dict[str, Any],
    license_text: str,
    release_policy: str,
    trademark_text: str,
) -> list[str]:
    findings: list[str] = []
    if decision.get("current_license_expression") != "Apache-2.0":
        findings.append("license expression changed")

    required_license_markers = ("Apache License", "Version 2.0")
    if not all(marker in license_text for marker in required_license_markers):
        findings.append("LICENSE does not match decision")

    if decision.get("decision") != "grant_public_open_source_distribution":
        findings.append("open-source owner decision changed")
    if decision.get("distribution_status") != "permitted_under_project_license":
        findings.append("public source distribution unexpectedly blocked")

    normalized_policy = release_policy.casefold()
    required_policy_markers = (
        "distributable under apache-2.0",
        "does not upload or publish",
    )
    if not all(marker in normalized_policy for marker in required_policy_markers):
        findings.append("release policy open-source boundary drift")

    normalized_trademark = trademark_text.casefold()
    required_trademark_markers = (
        "does not restrict any right granted",
        "good-faith community use",
    )
    if not all(marker in normalized_trademark for marker in required_trademark_markers):
        findings.append("trademark policy software-freedom boundary drift")
    return findings


def _check_third_party_inventory(
    third_party: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    findings: list[str] = []
    summary = third_party.get("summary") or {}
    packages = third_party.get("packages") or []
    if not isinstance(packages, list) or not packages:
        return ["third-party inventory count mismatch"], summary

    status_counts: Counter[str] = Counter()
    for item in packages:
        if not isinstance(item, dict) or not item.get("name") or not item.get("version"):
            findings.append("third-party package identity incomplete")
            continue
        status = item.get("metadata_status")
        if status not in ALLOWED_METADATA_STATUSES:
            findings.append(f"invalid metadata status: {item.get('name')}")
            continue
        status_counts[str(status)] += 1

    expected_counts = {
        "package_count": len(packages),
        "identified_count": status_counts["identified"],
        "ambiguous_count": status_counts["metadata_ambiguous"],
        "unresolved_count": status_counts["metadata_unresolved"],
    }
    observed_counts = {key: summary.get(key) for key in expected_counts}
    if observed_counts != expected_counts:
        findings.append("third-party inventory count mismatch")
    return findings, summary


def _check_source_distribution(
    source_distribution: dict[str, Any],
    third_party: dict[str, Any],
    summary: dict[str, Any],
) -> list[str]:
    findings: list[str] = []
    source_decision = source_distribution.get("decision") or {}
    evidence = source_distribution.get("evidence") or {}
    prior_boundary = third_party.get("distribution_boundary") or {}

    if source_decision.get("source_distribution_allowed") is not True:
        findings.append("source distribution review does not permit source")
    if source_decision.get("project_license_expression") != "Apache-2.0":
        findings.append("source distribution license mismatch")
    if source_decision.get("bundled_dependency_distribution_allowed") is not False:
        findings.append("bundled dependency boundary unexpectedly enabled")

    expected_evidence = {
        "source_candidate_embeds_third_party_packages": False,
        "dependencies_are_referenced_not_vendored": True,
        "inventory_package_count": summary.get("package_count"),
        "inventory_identified_count": summary.get("identified_count"),
        "inventory_metadata_ambiguous_count": summary.get("ambiguous_count"),
        "inventory_unresolved_count": summary.get("unresolved_count"),
    }
    observed_evidence = {key: evidence.get(key) for key in expected_evidence}
    if observed_evidence != expected_evidence:
        findings.append("source distribution evidence mismatch")

    prior_source_boundary = (
        prior_boundary.get("source_candidate_embeds_third_party_packages"),
        prior_boundary.get("dependencies_are_referenced_not_vendored"),
    )
    if prior_source_boundary != (False, True):
        findings.append("source candidate embedding boundary drift")
    return findings


def check(root: Path) -> list[str]:
    """Return decision drift findings for a repository root."""

    identity = _load_json(root, IDENTITY)
    license_decision = _load_json(root, LICENSE_DECISION)
    third_party = _load_json(root, THIRD_PARTY)
    source_distribution = _load_json(root, SOURCE_DISTRIBUTION)

    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    trademark_text = (root / "TRADEMARK_POLICY.md").read_text(encoding="utf-8")
    naming_text = (root / "docs/architecture/naming.md").read_text(encoding="utf-8")
    release_policy = (root / "docs/release/release-policy.md").read_text(
        encoding="utf-8"
    )

    inventory_findings, summary = _check_third_party_inventory(third_party)
    return [
        *_check_identity(identity, naming_text),
        *_check_license_decision(
            license_decision,
            license_text,
            release_policy,
            trademark_text,
        ),
        *inventory_findings,
        *_check_source_distribution(source_distribution, third_party, summary),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    findings = check(args.root.resolve())
    report = {
        "kind": "repoground.identity_distribution_decision_check",
        "version": "1.1",
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
