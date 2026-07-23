import copy
import json
from pathlib import Path

import jsonschema

from scripts.docmeta.check_status_truth import scan

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "merger/repoground/contracts/repobrief-status-truth.v1.schema.json"
STATUS = ROOT / "docs/status/repobrief-status-truth.v1.json"
DONE_MARKER = (
    "`done` – der deklarierte Task-Scope ist abgeschlossen und belegt; "
    "separate Folgetasks oder Grenzen dürfen offen bleiben"
)
ROADMAP_MARKERS = [
    "Kanonische Taskstatus: `docs/tasks/index.json`",
    "Häkchen gelten nur für den jeweiligen Arbeitspunkt",
    "Ein grüner Health- oder CI-Status beweist keine Produkt- oder Release-Reife",
]
RELEASE_IDENTITY = {
    "license_expression": "Apache-2.0",
    "license_file": "LICENSE",
    "product_name": "RepoGround",
    "public_distribution_status": "permitted_under_project_license",
    "python_namespace": "merger.repoground",
    "release_version": "3.0.0",
    "repository_target": "heimgewebe/repoground",
}


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_release_identity_sources(root: Path) -> None:
    _write(
        root,
        "LICENSE",
        "Apache License\n                           Version 2.0, January 2004\n",
    )
    _write(root, "RELEASE_VERSION", "3.0.0\n")
    _write(
        root,
        "docs/architecture/repoground-3-migration-inventory.v1.json",
        json.dumps(
            {
                "kind": "repoground.migration_inventory",
                "canonical": {
                    "product": "RepoGround",
                    "repository_target": "heimgewebe/repoground",
                    "python_namespace": "merger.repoground",
                    "command": "repoground",
                },
            }
        ),
    )
    _write(
        root,
        "docs/decisions/repoground-public-license-decision.v1.json",
        json.dumps(
            {
                "current_license_expression": "Apache-2.0",
                "distribution_status": "permitted_under_project_license",
            }
        ),
    )


def _fixture(root: Path) -> None:
    _write_release_identity_sources(root)
    task = {
        "id": "TASK-X-001",
        "title": "Synthetic task",
        "status": "open",
        "description": "Synthetic bounded task.",
        "evidence": ["docs/proof.md"],
        "missing_evidence": ["Implementation remains open."],
    }
    _write(root, "docs/tasks/index.json", json.dumps({"tasks": [task]}))
    board = (
        "# Task Board\n\n## Status-Legende\n"
        f"- {DONE_MARKER}\n\n## Aktive Tasks\n\n"
        "| ID | Titel | Status | Evidence | Offene Punkte |\n"
        "|---|---|---|---|---|\n"
        "| TASK-X-001 | Synthetic task | open | `docs/proof.md` | Open. |\n"
    )
    _write(root, "docs/tasks/board.md", board)
    for path in (
        "docs/repoground-upgrade-blaupause.md",
        "docs/roadmap/repoground-master-roadmap.md",
        "docs/roadmap/lenskit-agent-operationalization-roadmap.md",
    ):
        _write(root, path, "\n".join(ROADMAP_MARKERS) + "\n")
    _write(
        root,
        "docs/doc-freshness-registry.yml",
        "authority: diagnostic_signal\n"
        "risk_class: diagnostic\n"
        "does_not_prove:\n"
        "  - A green verify does not prove documentation completeness\n"
        "entries:\n"
        "  - id: claim-one\n",
    )
    truth = copy.deepcopy(json.loads(STATUS.read_text(encoding="utf-8")))
    truth["task_summary"] = {
        "total": 1,
        "by_status": {"open": 1, "in_progress": 0, "partial": 0, "done": 0},
    }
    truth["roadmap_surfaces"] = [
        {
            "path": path,
            "role": role,
            "checkbox_semantics": "item_local",
            "canonical_task_status": False,
            "phase_gate_independent": True,
            "required_markers": ROADMAP_MARKERS,
        }
        for path, role in (
            ("docs/repoground-upgrade-blaupause.md", "target_architecture"),
            ("docs/roadmap/repoground-master-roadmap.md", "ordered_roadmap"),
            (
                "docs/roadmap/lenskit-agent-operationalization-roadmap.md",
                "operationalization_plan",
            ),
        )
    ]
    truth["claim_freshness"]["tracked_claim_count"] = 1
    truth["audit_packages"] = [
        {
            "task_id": "TASK-X-001",
            "status": "open",
            "scope": "synthetic task",
            "verification": "not_started",
            "promotion": "blocked",
            "limitations": ["Not implemented."],
        }
    ]
    truth["open_followups"] = ["TASK-X-001"]
    truth["release_identity"] = dict(RELEASE_IDENTITY)
    _write(root, "docs/status/repobrief-status-truth.v1.json", json.dumps(truth))


def _codes(root: Path) -> set[str]:
    return {item["code"] for item in scan(root)["findings"]}


def test_repository_status_truth_is_consistent() -> None:
    report = scan(ROOT)
    assert report["status"] == "pass", report["findings"]


def test_repository_projection_validates_against_schema() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    instance = json.loads(STATUS.read_text(encoding="utf-8"))
    jsonschema.Draft7Validator(schema).validate(instance)


def test_missing_board_task_is_rejected(tmp_path: Path) -> None:
    _fixture(tmp_path)
    path = tmp_path / "docs/tasks/board.md"
    path.write_text(
        path.read_text().replace(
            "| TASK-X-001 | Synthetic task | open | `docs/proof.md` | Open. |\n",
            "",
        )
    )
    assert "TASK_MISSING_ON_BOARD" in _codes(tmp_path)


def test_task_status_mismatch_is_rejected(tmp_path: Path) -> None:
    _fixture(tmp_path)
    path = tmp_path / "docs/tasks/board.md"
    path.write_text(
        path.read_text().replace(
            "| TASK-X-001 | Synthetic task | open |",
            "| TASK-X-001 | Synthetic task | done |",
        )
    )
    assert "TASK_STATUS_MISMATCH" in _codes(tmp_path)


def test_missing_roadmap_marker_is_rejected(tmp_path: Path) -> None:
    _fixture(tmp_path)
    path = tmp_path / "docs/repoground-upgrade-blaupause.md"
    path.write_text(path.read_text().replace(ROADMAP_MARKERS[1], ""))
    assert "STATUS_TRUTH_ROADMAP_MARKER" in _codes(tmp_path)


def test_claim_count_mismatch_is_rejected(tmp_path: Path) -> None:
    _fixture(tmp_path)
    path = tmp_path / "docs/status/repobrief-status-truth.v1.json"
    truth = json.loads(path.read_text())
    truth["claim_freshness"]["tracked_claim_count"] = 2
    path.write_text(json.dumps(truth))
    assert "STATUS_TRUTH_CLAIM_COUNT" in _codes(tmp_path)


def test_release_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    _fixture(tmp_path)
    path = tmp_path / "docs/status/repobrief-status-truth.v1.json"
    truth = json.loads(path.read_text())
    truth["release_identity"]["release_version"] = "2.9.0"
    path.write_text(json.dumps(truth))
    assert "STATUS_TRUTH_RELEASE_IDENTITY_MISMATCH" in _codes(tmp_path)


def test_missing_release_identity_is_rejected(tmp_path: Path) -> None:
    _fixture(tmp_path)
    path = tmp_path / "docs/status/repobrief-status-truth.v1.json"
    truth = json.loads(path.read_text())
    del truth["release_identity"]
    path.write_text(json.dumps(truth))
    assert "STATUS_TRUTH_RELEASE_IDENTITY_MISMATCH" in _codes(tmp_path)


def test_stale_license_reference_is_rejected(tmp_path: Path) -> None:
    _fixture(tmp_path)
    path = tmp_path / "docs/status/repobrief-status-truth.v1.json"
    truth = json.loads(path.read_text())
    truth["audit_packages"][0]["limitations"].append(
        "Public distribution remains blocked by LicenseRef-RepoBrief-All-Rights-Reserved."
    )
    path.write_text(json.dumps(truth))
    assert "STATUS_TRUTH_STALE_LICENSE_REFERENCE" in _codes(tmp_path)


def test_historical_license_reference_is_allowed(tmp_path: Path) -> None:
    _fixture(tmp_path)
    path = tmp_path / "docs/status/repobrief-status-truth.v1.json"
    truth = json.loads(path.read_text())
    truth["audit_packages"][0]["limitations"].append(
        "Historical evidence: the project previously used LicenseRef-RepoBrief-All-Rights-Reserved before the 2026-07-18 Apache-2.0 decision."
    )
    path.write_text(json.dumps(truth))
    assert "STATUS_TRUTH_STALE_LICENSE_REFERENCE" not in _codes(tmp_path)


def test_stale_release_version_is_rejected_when_file_bumps(tmp_path: Path) -> None:
    _fixture(tmp_path)
    (tmp_path / "RELEASE_VERSION").write_text("3.1.0\n", encoding="utf-8")
    assert "STATUS_TRUTH_RELEASE_IDENTITY_MISMATCH" in _codes(tmp_path)


def test_unrecognized_license_text_blocks_the_check(tmp_path: Path) -> None:
    _fixture(tmp_path)
    (tmp_path / "LICENSE").write_text(
        "LicenseRef-Some-Other-Terms\n", encoding="utf-8"
    )
    assert "RELEASE_IDENTITY_LICENSE_UNRECOGNIZED" in _codes(tmp_path)


def test_repository_release_identity_matches_ground_truth() -> None:
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    release_version = (ROOT / "RELEASE_VERSION").read_text(encoding="utf-8").strip()
    identity = status["release_identity"]
    assert identity["license_expression"] == "Apache-2.0"
    assert "Apache License" in license_text
    assert "Version 2.0" in license_text
    assert identity["release_version"] == release_version
    assert identity["product_name"] == "RepoGround"
    assert identity["repository_target"] == "heimgewebe/repoground"


def test_invalid_task_entry_is_reported_without_crashing(tmp_path: Path) -> None:
    _fixture(tmp_path)
    path = tmp_path / "docs/tasks/index.json"
    data = json.loads(path.read_text())
    data["tasks"].append("invalid")
    path.write_text(json.dumps(data))
    assert "TASK_INDEX_INVALID_ENTRY" in _codes(tmp_path)


def test_selected_audit_coverage_is_required(tmp_path: Path) -> None:
    _fixture(tmp_path)
    path = tmp_path / "docs/status/repobrief-status-truth.v1.json"
    truth = json.loads(path.read_text())
    truth["audit_package_coverage"] = "all_audits"
    path.write_text(json.dumps(truth))
    assert "STATUS_TRUTH_AUDIT_COVERAGE" in _codes(tmp_path)


def test_readiness_overclaim_is_rejected(tmp_path: Path) -> None:
    _fixture(tmp_path)
    path = tmp_path / "docs/status/repobrief-status-truth.v1.json"
    truth = json.loads(path.read_text())
    truth["system_maturity"]["release_readiness"] = "established"
    path.write_text(json.dumps(truth))
    assert "STATUS_TRUTH_READINESS_OVERCLAIM" in _codes(tmp_path)


def test_product_readiness_without_declared_basis_is_rejected(tmp_path: Path) -> None:
    _fixture(tmp_path)
    path = tmp_path / "docs/status/repobrief-status-truth.v1.json"
    truth = json.loads(path.read_text())
    truth["system_maturity"]["product_readiness"] = "established"
    path.write_text(json.dumps(truth))
    assert "STATUS_TRUTH_PRODUCT_READINESS_UNSUPPORTED" in _codes(tmp_path)


def test_release_readiness_can_progress_after_release_task_done(
    tmp_path: Path,
) -> None:
    _fixture(tmp_path)
    index_path = tmp_path / "docs/tasks/index.json"
    index = json.loads(index_path.read_text())
    release_task = {
        "id": "TASK-LENSKIT-AUDIT-RELEASE-PACKAGING-001",
        "title": "Release packaging",
        "status": "done",
        "description": "Synthetic completed release task.",
        "evidence": ["docs/release-proof.md"],
        "missing_evidence": ["No product-readiness claim."],
    }
    index["tasks"].append(release_task)
    index_path.write_text(json.dumps(index))

    board_path = tmp_path / "docs/tasks/board.md"
    board_path.write_text(
        board_path.read_text()
        + "| TASK-LENSKIT-AUDIT-RELEASE-PACKAGING-001 | Release packaging | done | `docs/release-proof.md` | Product readiness remains separate. |\n"
    )

    status_path = tmp_path / "docs/status/repobrief-status-truth.v1.json"
    truth = json.loads(status_path.read_text())
    truth["task_summary"] = {
        "total": 2,
        "by_status": {"open": 1, "in_progress": 0, "partial": 0, "done": 1},
    }
    truth["audit_packages"].append(
        {
            "task_id": "TASK-LENSKIT-AUDIT-RELEASE-PACKAGING-001",
            "status": "done",
            "scope": "synthetic release evidence",
            "verification": "main_verified",
            "promotion": "allowed",
            "limitations": ["Product readiness remains separate."],
        }
    )
    truth["system_maturity"]["release_readiness"] = "established"
    status_path.write_text(json.dumps(truth))
    report = scan(tmp_path)
    assert report["status"] == "pass", report["findings"]


def test_task_workflow_runs_status_truth_check() -> None:
    workflow = (ROOT / ".github/workflows/task-index.yml").read_text(
        encoding="utf-8"
    )
    assert "python3 scripts/docmeta/check_status_truth.py --format json" in workflow
    assert "status-truth-report.json" in workflow
