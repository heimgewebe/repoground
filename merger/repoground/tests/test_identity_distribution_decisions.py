import json
from pathlib import Path

from scripts.release.check_identity_distribution_decisions import check

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATHS = (
    "docs/decisions/repoground-3-naming-and-migration.v1.json",
    "docs/decisions/repoground-public-license-decision.v1.json",
    "docs/release/third-party-license-review.v1.json",
    "docs/release/third-party-source-distribution-review.v1.json",
    "docs/architecture/naming.md",
    "docs/release/release-policy.md",
    "LICENSE",
    "TRADEMARK_POLICY.md",
)


def test_repository_identity_distribution_decisions_pass() -> None:
    assert check(ROOT) == []


def _copy_fixture(tmp_path: Path) -> None:
    for relative in FIXTURE_PATHS:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())


def test_checker_rejects_open_source_policy_drift(tmp_path: Path) -> None:
    _copy_fixture(tmp_path)
    policy = tmp_path / "docs/release/release-policy.md"
    policy.write_text(
        "Source candidates are private and may not be distributed.\n",
        encoding="utf-8",
    )
    assert "release policy open-source boundary drift" in check(tmp_path)


def test_checker_rejects_license_drift(tmp_path: Path) -> None:
    _copy_fixture(tmp_path)
    (tmp_path / "LICENSE").write_text("MIT\n", encoding="utf-8")
    assert "LICENSE does not match decision" in check(tmp_path)


def test_checker_rejects_trademark_software_freedom_drift(tmp_path: Path) -> None:
    _copy_fixture(tmp_path)
    (tmp_path / "TRADEMARK_POLICY.md").write_text(
        "All code and name uses require prior permission.\n",
        encoding="utf-8",
    )
    assert "trademark policy software-freedom boundary drift" in check(tmp_path)


def test_checker_rejects_third_party_count_drift(tmp_path: Path) -> None:
    _copy_fixture(tmp_path)
    review_path = tmp_path / "docs/release/third-party-license-review.v1.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["summary"]["package_count"] += 1
    review_path.write_text(json.dumps(review), encoding="utf-8")
    assert "third-party inventory count mismatch" in check(tmp_path)


def test_checker_rejects_source_distribution_evidence_drift(tmp_path: Path) -> None:
    _copy_fixture(tmp_path)
    review_path = (
        tmp_path / "docs/release/third-party-source-distribution-review.v1.json"
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["evidence"]["inventory_package_count"] += 1
    review_path.write_text(json.dumps(review), encoding="utf-8")
    assert "source distribution evidence mismatch" in check(tmp_path)
