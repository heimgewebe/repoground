#!/usr/bin/env python3
"""Check bounded parity across Lenskit task, roadmap and claim-status surfaces."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.release.build_release_candidate import (
    DISTRIBUTION_STATUS,
    LICENSE_EXPRESSION,
    VERSION_RE,
)

KIND = "lenskit.status_truth_check"
VERSION = "1.0"
ALLOWED_STATUSES = {"open", "in_progress", "partial", "done"}
DEFAULT_STATUS_PATH = Path("docs/status/repobrief-status-truth.v1.json")
TASK_INDEX_PATH = Path("docs/tasks/index.json")
TASK_BOARD_PATH = Path("docs/tasks/board.md")
DOC_FRESHNESS_PATH = Path("docs/doc-freshness-registry.yml")
LICENSE_PATH = Path("LICENSE")
RELEASE_VERSION_PATH = Path("RELEASE_VERSION")
MIGRATION_INVENTORY_PATH = Path("docs/architecture/repoground-3-migration-inventory.v1.json")
PUBLIC_LICENSE_DECISION_PATH = Path("docs/decisions/repoground-public-license-decision.v1.json")
STALE_CURRENT_DISTRIBUTION_RE = re.compile(
    r"public distribution\s+(?:remains\s+|is\s+)?blocked[^.]*LicenseRef-[A-Za-z0-9_.-]+",
    re.IGNORECASE,
)
BOARD_DONE_MARKER = (
    "`done` – der deklarierte Task-Scope ist abgeschlossen und belegt; "
    "separate Folgetasks oder Grenzen dürfen offen bleiben"
)


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    detail: str


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_tasks(root: Path) -> tuple[list[dict[str, Any]], list[Finding]]:
    path = root / TASK_INDEX_PATH
    try:
        raw = _load_json(path)
    except Exception as exc:  # noqa: BLE001 - control-file boundary
        return [], [Finding("TASK_INDEX_INVALID", TASK_INDEX_PATH.as_posix(), str(exc))]
    tasks = raw if isinstance(raw, list) else raw.get("tasks") if isinstance(raw, dict) else None
    if not isinstance(tasks, list):
        return [], [Finding("TASK_INDEX_INVALID", TASK_INDEX_PATH.as_posix(), "expected task list")]
    findings: list[Finding] = []
    seen: set[str] = set()
    for item in tasks:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            findings.append(Finding("TASK_INDEX_INVALID_ENTRY", TASK_INDEX_PATH.as_posix(), repr(item)))
            continue
        task_id = item["id"]
        if task_id in seen:
            findings.append(Finding("TASK_INDEX_DUPLICATE_ID", TASK_INDEX_PATH.as_posix(), task_id))
        seen.add(task_id)
        status = item.get("status")
        if status not in ALLOWED_STATUSES:
            findings.append(Finding("TASK_INDEX_INVALID_STATUS", TASK_INDEX_PATH.as_posix(), f"{task_id}: {status!r}"))
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            findings.append(Finding("TASK_INDEX_MISSING_EVIDENCE", TASK_INDEX_PATH.as_posix(), task_id))
    return tasks, findings


def _load_board(root: Path) -> tuple[dict[str, dict[str, str]], str, list[Finding]]:
    path = root / TASK_BOARD_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {}, "", [Finding("TASK_BOARD_INVALID", TASK_BOARD_PATH.as_posix(), str(exc))]
    rows: dict[str, dict[str, str]] = {}
    findings: list[Finding] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.startswith("| TASK-"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            findings.append(Finding("TASK_BOARD_INVALID_ROW", TASK_BOARD_PATH.as_posix(), f"line {line_no}"))
            continue
        task_id, title, status, evidence, notes = cells[:5]
        if task_id in rows:
            findings.append(Finding("TASK_BOARD_DUPLICATE_ID", TASK_BOARD_PATH.as_posix(), task_id))
        rows[task_id] = {
            "title": title,
            "status": status,
            "evidence": evidence,
            "notes": notes,
        }
    return rows, text, findings


def _registry_summary(root: Path) -> tuple[dict[str, Any], list[Finding]]:
    path = root / DOC_FRESHNESS_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {}, [Finding("CLAIM_REGISTRY_INVALID", DOC_FRESHNESS_PATH.as_posix(), str(exc))]
    authority = re.search(r"^authority:\s*([^\s#]+)", text, re.MULTILINE)
    risk = re.search(r"^risk_class:\s*([^\s#]+)", text, re.MULTILINE)
    ids = re.findall(r"^\s{2}- id:\s*([^\s#]+)", text, re.MULTILINE)
    does_not_prove = "does_not_prove:" in text and "does not prove" in text.lower()
    findings: list[Finding] = []
    if authority is None or authority.group(1) != "diagnostic_signal":
        findings.append(Finding("CLAIM_REGISTRY_AUTHORITY", DOC_FRESHNESS_PATH.as_posix(), "authority must be diagnostic_signal"))
    if risk is None or risk.group(1) != "diagnostic":
        findings.append(Finding("CLAIM_REGISTRY_RISK", DOC_FRESHNESS_PATH.as_posix(), "risk_class must be diagnostic"))
    if len(ids) != len(set(ids)):
        findings.append(Finding("CLAIM_REGISTRY_DUPLICATE_ID", DOC_FRESHNESS_PATH.as_posix(), "duplicate entry id"))
    if not does_not_prove:
        findings.append(Finding("CLAIM_REGISTRY_BOUNDARY", DOC_FRESHNESS_PATH.as_posix(), "missing explicit completeness boundary"))
    return {
        "authority": authority.group(1) if authority else None,
        "risk_class": risk.group(1) if risk else None,
        "entry_ids": ids,
    }, findings


def _release_identity_facts(root: Path) -> tuple[dict[str, Any] | None, list[Finding]]:
    """Derive stable release-identity facts directly from repository files.

    Deliberately local and network-free: every fact comes from a file already
    tracked in the repository (LICENSE, RELEASE_VERSION, the migration
    inventory and the public license decision record).
    """

    try:
        license_text = (root / LICENSE_PATH).read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - control-file boundary
        return None, [Finding("RELEASE_IDENTITY_LICENSE_UNREADABLE", LICENSE_PATH.as_posix(), str(exc))]
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        return None, [
            Finding(
                "RELEASE_IDENTITY_LICENSE_UNRECOGNIZED",
                LICENSE_PATH.as_posix(),
                f"LICENSE text no longer matches the declared {LICENSE_EXPRESSION} expression",
            )
        ]

    try:
        release_version = (root / RELEASE_VERSION_PATH).read_text(encoding="utf-8").strip()
    except Exception as exc:  # noqa: BLE001 - control-file boundary
        return None, [Finding("RELEASE_IDENTITY_VERSION_UNREADABLE", RELEASE_VERSION_PATH.as_posix(), str(exc))]
    if not VERSION_RE.fullmatch(release_version):
        return None, [Finding("RELEASE_IDENTITY_VERSION_INVALID", RELEASE_VERSION_PATH.as_posix(), release_version)]

    try:
        inventory = _load_json(root / MIGRATION_INVENTORY_PATH)
    except Exception as exc:  # noqa: BLE001 - control-file boundary
        return None, [Finding("RELEASE_IDENTITY_NAMING_UNREADABLE", MIGRATION_INVENTORY_PATH.as_posix(), str(exc))]
    canonical = inventory.get("canonical") if isinstance(inventory, dict) else None
    required_naming = {"product", "repository_target", "python_namespace", "command"}
    if not isinstance(canonical, dict) or not required_naming.issubset(canonical):
        return None, [
            Finding(
                "RELEASE_IDENTITY_NAMING_INVALID",
                MIGRATION_INVENTORY_PATH.as_posix(),
                "missing or incomplete canonical naming block",
            )
        ]

    try:
        decision = _load_json(root / PUBLIC_LICENSE_DECISION_PATH)
    except Exception as exc:  # noqa: BLE001 - control-file boundary
        return None, [Finding("RELEASE_IDENTITY_DECISION_UNREADABLE", PUBLIC_LICENSE_DECISION_PATH.as_posix(), str(exc))]
    if (
        not isinstance(decision, dict)
        or decision.get("current_license_expression") != LICENSE_EXPRESSION
        or decision.get("distribution_status") != DISTRIBUTION_STATUS
    ):
        return None, [
            Finding(
                "RELEASE_IDENTITY_DECISION_DRIFT",
                PUBLIC_LICENSE_DECISION_PATH.as_posix(),
                "recorded public license decision no longer matches the current license/distribution facts",
            )
        ]

    facts = {
        "product_name": canonical["product"],
        "repository_target": canonical["repository_target"],
        "python_namespace": canonical["python_namespace"],
        "license_expression": LICENSE_EXPRESSION,
        "license_file": LICENSE_PATH.as_posix(),
        "release_version": release_version,
        "public_distribution_status": DISTRIBUTION_STATUS,
    }
    return facts, []


def _validate_release_truth(
    root: Path, truth: dict[str, Any], status_path: Path
) -> list[Finding]:
    findings: list[Finding] = []
    release_facts, release_identity_findings = _release_identity_facts(root)
    findings.extend(release_identity_findings)
    if release_facts is None:
        return findings

    declared = truth.get("release_identity")
    declared_identity = declared if isinstance(declared, dict) else None
    if declared_identity != release_facts:
        findings.append(
            Finding(
                "STATUS_TRUTH_RELEASE_IDENTITY_MISMATCH",
                status_path.as_posix(),
                f"expected {release_facts!r}, found {declared_identity!r}",
            )
        )

    # Historical/versioned evidence may legitimately name a superseded LicenseRef.
    # Reject only prose that presents the old restrictive license as the current
    # public-distribution state.
    serialized_truth = json.dumps(truth, sort_keys=True)
    if STALE_CURRENT_DISTRIBUTION_RE.findall(serialized_truth):
        findings.append(
            Finding(
                "STATUS_TRUTH_STALE_LICENSE_REFERENCE",
                status_path.as_posix(),
                "current public-distribution prose still claims a superseded restrictive LicenseRef",
            )
        )
    return findings


def scan(root: Path, status_path: Path = DEFAULT_STATUS_PATH) -> dict[str, Any]:
    root = root.resolve()
    findings: list[Finding] = []
    tasks, task_findings = _load_tasks(root)
    findings.extend(task_findings)
    board, board_text, board_findings = _load_board(root)
    findings.extend(board_findings)
    task_by_id = {item["id"]: item for item in tasks if isinstance(item, dict) and isinstance(item.get("id"), str)}

    missing_board = sorted(set(task_by_id) - set(board))
    missing_index = sorted(set(board) - set(task_by_id))
    for task_id in missing_board:
        findings.append(Finding("TASK_MISSING_ON_BOARD", TASK_BOARD_PATH.as_posix(), task_id))
    for task_id in missing_index:
        findings.append(Finding("BOARD_TASK_MISSING_IN_INDEX", TASK_INDEX_PATH.as_posix(), task_id))
    for task_id in sorted(set(task_by_id) & set(board)):
        task = task_by_id[task_id]
        row = board[task_id]
        if task.get("status") != row["status"]:
            findings.append(Finding("TASK_STATUS_MISMATCH", TASK_BOARD_PATH.as_posix(), f"{task_id}: index={task.get('status')}, board={row['status']}"))
        if task.get("title") != row["title"]:
            findings.append(Finding("TASK_TITLE_MISMATCH", TASK_BOARD_PATH.as_posix(), task_id))
        if not row["evidence"] or not row["notes"]:
            findings.append(Finding("TASK_BOARD_INCOMPLETE_ROW", TASK_BOARD_PATH.as_posix(), task_id))
    if BOARD_DONE_MARKER not in board_text:
        findings.append(Finding("TASK_BOARD_DONE_SEMANTICS", TASK_BOARD_PATH.as_posix(), "done must be explicitly task-scope local"))

    resolved_status_path = status_path if status_path.is_absolute() else root / status_path
    try:
        truth = _load_json(resolved_status_path)
    except Exception as exc:  # noqa: BLE001
        truth = {}
        findings.append(Finding("STATUS_TRUTH_INVALID", status_path.as_posix(), str(exc)))

    if truth.get("kind") != "lenskit.repobrief_status_truth" or truth.get("version") != "1.0":
        findings.append(Finding("STATUS_TRUTH_KIND", status_path.as_posix(), "unexpected kind/version"))
    if truth.get("authority") != "governance_projection":
        findings.append(Finding("STATUS_TRUTH_AUTHORITY", status_path.as_posix(), "must remain a projection"))

    findings.extend(_validate_release_truth(root, truth, status_path))

    counts = Counter(
        item.get("status") for item in tasks if isinstance(item, dict)
    )
    expected_summary = {
        "total": len(tasks),
        "by_status": {status: counts.get(status, 0) for status in ("open", "in_progress", "partial", "done")},
    }
    if truth.get("task_summary") != expected_summary:
        findings.append(Finding("STATUS_TRUTH_TASK_SUMMARY", status_path.as_posix(), f"expected {expected_summary!r}"))

    semantics = truth.get("status_semantics") if isinstance(truth.get("status_semantics"), dict) else {}
    non_implied = set(semantics.get("done_does_not_imply") or [])
    required_non_implied = {"phase_complete", "system_complete", "product_ready", "release_ready", "all_followups_closed"}
    if not required_non_implied.issubset(non_implied):
        findings.append(Finding("STATUS_TRUTH_DONE_BOUNDARY", status_path.as_posix(), "done boundary incomplete"))

    maturity = (
        truth.get("system_maturity")
        if isinstance(truth.get("system_maturity"), dict)
        else {}
    )
    release_task = task_by_id.get("TASK-LENSKIT-AUDIT-RELEASE-PACKAGING-001")
    if (
        maturity.get("release_readiness") == "established"
        and (release_task is None or release_task.get("status") != "done")
    ):
        findings.append(
            Finding(
                "STATUS_TRUTH_READINESS_OVERCLAIM",
                status_path.as_posix(),
                "release readiness requires a present and completed release-packaging task",
            )
        )
    if maturity.get("product_readiness") == "established":
        findings.append(
            Finding(
                "STATUS_TRUTH_PRODUCT_READINESS_UNSUPPORTED",
                status_path.as_posix(),
                "v1 has no declared product-readiness evidence package",
            )
        )

    roadmap_records = truth.get("roadmap_surfaces") if isinstance(truth.get("roadmap_surfaces"), list) else []
    for record in roadmap_records:
        if not isinstance(record, dict):
            findings.append(Finding("STATUS_TRUTH_ROADMAP_RECORD", status_path.as_posix(), repr(record)))
            continue
        rel = record.get("path")
        if not isinstance(rel, str):
            findings.append(Finding("STATUS_TRUTH_ROADMAP_RECORD", status_path.as_posix(), "missing path"))
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            findings.append(Finding("STATUS_TRUTH_ROADMAP_MISSING", rel, str(exc)))
            continue
        if record.get("canonical_task_status") is not False:
            findings.append(Finding("STATUS_TRUTH_ROADMAP_AUTHORITY", rel, "roadmap must not be canonical task authority"))
        for marker in record.get("required_markers") or []:
            if marker not in text:
                findings.append(Finding("STATUS_TRUTH_ROADMAP_MARKER", rel, str(marker)))

    registry, registry_findings = _registry_summary(root)
    findings.extend(registry_findings)
    claim_truth = truth.get("claim_freshness") if isinstance(truth.get("claim_freshness"), dict) else {}
    if claim_truth.get("authority") != "diagnostic_signal" or claim_truth.get("coverage") != "selected_declared_claims_only":
        findings.append(Finding("STATUS_TRUTH_CLAIM_BOUNDARY", status_path.as_posix(), "claim freshness authority/coverage overclaimed"))
    if claim_truth.get("tracked_claim_count") != len(registry.get("entry_ids", [])):
        findings.append(Finding("STATUS_TRUTH_CLAIM_COUNT", status_path.as_posix(), f"expected {len(registry.get('entry_ids', []))}"))

    if truth.get("audit_package_coverage") != "selected_remediation_packages":
        findings.append(
            Finding(
                "STATUS_TRUTH_AUDIT_COVERAGE",
                status_path.as_posix(),
                "audit packages must remain explicitly selected, not exhaustive",
            )
        )

    packages = (
        truth.get("audit_packages")
        if isinstance(truth.get("audit_packages"), list)
        else []
    )
    package_ids: set[str] = set()
    for package in packages:
        if not isinstance(package, dict) or not isinstance(package.get("task_id"), str):
            findings.append(Finding("STATUS_TRUTH_AUDIT_PACKAGE", status_path.as_posix(), repr(package)))
            continue
        task_id = package["task_id"]
        package_ids.add(task_id)
        task = task_by_id.get(task_id)
        if task is None:
            findings.append(Finding("STATUS_TRUTH_UNKNOWN_TASK", status_path.as_posix(), task_id))
            continue
        if package.get("status") != task.get("status"):
            findings.append(Finding("STATUS_TRUTH_PACKAGE_STATUS", status_path.as_posix(), f"{task_id}: task={task.get('status')}, projection={package.get('status')}"))
        if not package.get("limitations"):
            findings.append(Finding("STATUS_TRUTH_PACKAGE_LIMITS", status_path.as_posix(), task_id))
    if len(package_ids) != len(packages):
        findings.append(Finding("STATUS_TRUTH_DUPLICATE_PACKAGE", status_path.as_posix(), "duplicate task_id"))

    followups = truth.get("open_followups") if isinstance(truth.get("open_followups"), list) else []
    for task_id in followups:
        task = task_by_id.get(task_id)
        if task is None:
            findings.append(Finding("STATUS_TRUTH_UNKNOWN_FOLLOWUP", status_path.as_posix(), str(task_id)))
        elif task.get("status") == "done":
            findings.append(Finding("STATUS_TRUTH_CLOSED_FOLLOWUP", status_path.as_posix(), str(task_id)))

    health = truth.get("health_semantics") if isinstance(truth.get("health_semantics"), dict) else {}
    forbidden = set(health.get("forbidden_inferences") or [])
    if not {"product_ready", "release_ready", "review_complete", "test_complete", "semantic_truth", "runtime_correct"}.issubset(forbidden):
        findings.append(Finding("STATUS_TRUTH_HEALTH_BOUNDARY", status_path.as_posix(), "forbidden inference set incomplete"))

    return {
        "kind": KIND,
        "version": VERSION,
        "status": "pass" if not findings else "fail",
        "summary": {
            "task_count": len(tasks),
            "board_count": len(board),
            "claim_count": len(registry.get("entry_ids", [])),
            "audit_package_count": len(packages),
            "finding_count": len(findings),
        },
        "findings": [asdict(item) for item in findings],
        "does_not_establish": [
            "documentation completeness or semantic correctness",
            "task evidence sufficiency beyond declared paths",
            "product or release readiness",
            "test or review completeness",
            "absence of regressions, vulnerabilities or runtime defects",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--status-path", type=Path, default=DEFAULT_STATUS_PATH)
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args(argv)
    report = scan(args.root, args.status_path)
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["findings"]:
        for finding in report["findings"]:
            print(f"{finding['path']}: {finding['code']}: {finding['detail']}")
    else:
        summary = report["summary"]
        print(
            "Status truth check: pass "
            f"({summary['task_count']} tasks, {summary['claim_count']} tracked claims)"
        )
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
