#!/usr/bin/env python3
"""Fail when a production module has no recorded reachability evidence.

The check answers "is there evidence that this module is used?", not "is this
module dead?". A module without evidence is reported as ``unproven`` and blocks
the build so the gap is reviewed; it never licenses deletion.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from merger.repoground.architecture.module_reachability import (  # noqa: E402
    evaluate_reachability_policy,
    measure_module_reachability,
)

DEFAULT_POLICY = Path("config/repoground-module-reachability.v1.json")


POLICY_KIND = "repoground.module_reachability_policy"
POLICY_VERSION = "1.0"


def validate_policy(policy: Any) -> list[dict[str, Any]]:
    """Reject a policy that cannot be trusted to describe what is measured.

    Fail-closed: a policy without an identity or without package roots would
    otherwise fall back to defaults and report a pass over the wrong tree.
    """

    if not isinstance(policy, dict):
        return [{"code": "module_reachability_policy_invalid", "detail": "not an object"}]
    findings: list[dict[str, Any]] = []
    if (
        policy.get("kind") != POLICY_KIND
        or policy.get("version") != POLICY_VERSION
    ):
        findings.append({"code": "module_reachability_policy_identity_invalid"})
    roots = policy.get("package_roots")
    if not isinstance(roots, list) or not roots or not all(
        isinstance(root, str) and root for root in roots
    ):
        findings.append(
            {"code": "module_reachability_policy_invalid", "detail": "package_roots"}
        )
    return findings


def check(repo_root: Path, policy_path: Path) -> dict[str, Any]:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy_findings = validate_policy(policy)
    measurement = measure_module_reachability(
        repo_root, policy.get("package_roots") or ("merger",)
    )
    findings = policy_findings + evaluate_reachability_policy(measurement, policy)
    return {
        "kind": "repoground.module_reachability_check",
        "version": "1.0",
        "status": "pass" if not findings else "fail",
        "measurement": measurement,
        "findings": findings,
        "does_not_establish": measurement["does_not_establish"],
    }


def _summary(report: dict[str, Any]) -> str:
    measurement = report["measurement"]
    return (
        f"Module reachability: {measurement['module_count']} production modules, "
        f"{len(measurement['unproven'])} unproven, "
        f"{len(measurement['documentation_only'])} documentation-only, "
        f"{len(measurement['test_only'])} test-only"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    policy = args.policy if args.policy.is_absolute() else root / args.policy
    report = check(root, policy)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["findings"]:
        for finding in report["findings"]:
            print(json.dumps(finding, sort_keys=True))
    else:
        print(_summary(report))
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
