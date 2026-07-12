#!/usr/bin/env python3
"""Validate local callers against recursive, hash-bound workflow contracts."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

PERMISSION_RANK = {"none": 0, "read": 1, "write": 2}
DEFAULT_CONTRACT = Path(".github/reusable-workflow-contracts.json")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Finding:
    caller_path: str
    code: str
    detail: str


def _load_mapping(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected mapping")
    return raw


def _permission_findings(
    caller_path: str,
    observed: dict[str, Any],
    required: dict[str, str],
) -> list[Finding]:
    findings: list[Finding] = []
    for scope, minimum in sorted(required.items()):
        actual = str(observed.get(scope, "none"))
        if actual not in PERMISSION_RANK or minimum not in PERMISSION_RANK:
            findings.append(
                Finding(caller_path, "invalid_permission_level", f"{scope}: {actual}/{minimum}")
            )
        elif PERMISSION_RANK[actual] < PERMISSION_RANK[minimum]:
            findings.append(
                Finding(
                    caller_path,
                    "insufficient_caller_permission",
                    f"{scope}: caller={actual}, required={minimum}",
                )
            )
    return findings


def _revision(value: str) -> str:
    return value.rsplit("@", 1)[-1] if "@" in value else ""


def _is_reusable_workflow(value: str) -> bool:
    target = value.rsplit("@", 1)[0]
    return "/.github/workflows/" in target


def _inventory_findings(
    caller_path: str,
    node: dict[str, Any],
    location: str,
) -> list[Finding]:
    findings: list[Finding] = []
    source_hash = str(node.get("source_content_sha256", ""))
    if not SHA256_RE.fullmatch(source_hash):
        findings.append(
            Finding(
                caller_path,
                "invalid_source_content_sha256",
                f"{location}: {source_hash}",
            )
        )

    raw_uses = node.get("transitive_uses")
    if not isinstance(raw_uses, list):
        findings.append(
            Finding(
                caller_path,
                "missing_transitive_uses_inventory",
                f"{location}: {raw_uses!r}",
            )
        )
        transitive_uses: list[str] = []
    else:
        transitive_uses = [str(value) for value in raw_uses]
        for value in transitive_uses:
            if not SHA40_RE.fullmatch(_revision(value)):
                findings.append(
                    Finding(
                        caller_path,
                        "mutable_transitive_action_ref",
                        f"{location}: {value}",
                    )
                )

    raw_workflows = node.get("transitive_workflows")
    if not isinstance(raw_workflows, list):
        findings.append(
            Finding(
                caller_path,
                "missing_transitive_workflow_inventory",
                f"{location}: {raw_workflows!r}",
            )
        )
        workflows: list[dict[str, Any]] = []
    else:
        workflows = []
        for index, value in enumerate(raw_workflows):
            if not isinstance(value, dict):
                findings.append(
                    Finding(
                        caller_path,
                        "invalid_transitive_workflow_entry",
                        f"{location}[{index}]: {value!r}",
                    )
                )
                continue
            workflows.append(value)

    required_closures = Counter(
        value for value in transitive_uses if _is_reusable_workflow(value)
    )
    recorded_closures = Counter(str(value.get("uses", "")) for value in workflows)
    if recorded_closures != required_closures:
        findings.append(
            Finding(
                caller_path,
                "transitive_workflow_closure_mismatch",
                (
                    f"{location}: required={dict(required_closures)}, "
                    f"recorded={dict(recorded_closures)}"
                ),
            )
        )

    for workflow in workflows:
        workflow_use = str(workflow.get("uses", ""))
        if not SHA40_RE.fullmatch(_revision(workflow_use)):
            findings.append(
                Finding(
                    caller_path,
                    "mutable_transitive_workflow_ref",
                    f"{location}: {workflow_use}",
                )
            )
        findings.extend(
            _inventory_findings(
                caller_path,
                workflow,
                f"{location} -> {workflow_use or '<missing uses>'}",
            )
        )
    return findings


def scan(root: Path, contract_path: Path = DEFAULT_CONTRACT) -> list[Finding]:
    root = root.resolve()
    contract_file = contract_path if contract_path.is_absolute() else root / contract_path
    data = json.loads(contract_file.read_text(encoding="utf-8"))
    findings: list[Finding] = []
    for contract in data.get("contracts", []):
        relative = str(contract["caller_path"])
        caller_path = root / relative
        if not caller_path.is_file():
            findings.append(Finding(relative, "missing_caller_file", str(caller_path)))
            continue
        caller = _load_mapping(caller_path)
        job_name = str(contract["job"])
        jobs = caller.get("jobs") or {}
        job = jobs.get(job_name)
        if not isinstance(job, dict):
            findings.append(Finding(relative, "missing_caller_job", job_name))
            continue

        expected_use = str(contract["uses"])
        if job.get("uses") != expected_use:
            findings.append(
                Finding(
                    relative,
                    "reusable_workflow_pin_mismatch",
                    f"observed={job.get('uses')!r}, expected={expected_use!r}",
                )
            )

        findings.extend(_inventory_findings(relative, contract, expected_use))

        permissions = caller.get("permissions") or {}
        if not isinstance(permissions, dict):
            permissions = {}
        findings.extend(
            _permission_findings(
                relative,
                permissions,
                dict(contract.get("required_permissions") or {}),
            )
        )

        observed_secrets = set((job.get("secrets") or {}).keys())
        required_secrets = set(contract.get("required_secrets") or [])
        if observed_secrets != required_secrets:
            findings.append(
                Finding(
                    relative,
                    "caller_secret_contract_mismatch",
                    f"observed={sorted(observed_secrets)}, required={sorted(required_secrets)}",
                )
            )

        condition = str(job.get("if", ""))
        for fragment in contract.get("required_if_fragments") or []:
            if str(fragment) not in condition:
                findings.append(
                    Finding(relative, "missing_caller_condition", str(fragment))
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    findings = scan(args.root, args.contract)
    report = {
        "kind": "lenskit.reusable_workflow_caller_contract_check",
        "version": "1.1",
        "status": "pass" if not findings else "fail",
        "finding_count": len(findings),
        "findings": [asdict(item) for item in findings],
        "does_not_establish": [
            "runtime success of called workflows",
            "valid secret contents or GitHub App installation state",
            "identity of remote bytes unless every recorded hash is independently rechecked",
            "absence of malicious or vulnerable code in pinned dependencies",
        ],
    }
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif findings:
        for finding in findings:
            print(f"{finding.caller_path}: {finding.code}: {finding.detail}")
    else:
        print("Reusable workflow caller contract check: pass")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
