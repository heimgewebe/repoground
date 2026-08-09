import json
from pathlib import Path

from scripts.ci.check_reusable_workflow_contracts import scan


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _write_fixture(tmp_path: Path, contract: dict | None = None) -> None:
    root = _repo_root()
    target = tmp_path / ".github/reusable-workflow-contracts.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if contract is None:
        target.write_bytes(
            (root / ".github/reusable-workflow-contracts.json").read_bytes()
        )
    else:
        target.write_text(json.dumps(contract), encoding="utf-8")
    for relative in (
        ".github/workflows/pr-heimgewebe-commands.yml",
        ".github/workflows/wgx-guard.yml",
    ):
        source = root / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())


def _contract() -> dict:
    return json.loads(
        (_repo_root() / ".github/reusable-workflow-contracts.json").read_text(
            encoding="utf-8"
        )
    )


def _contract_with_recursive_workflow() -> dict:
    contract = _contract()
    root = contract["contracts"][1]
    workflow_use = (
        "example/reusable/.github/workflows/check.yml@"
        "0123456789abcdef0123456789abcdef01234567"
    )
    root["transitive_uses"].append(workflow_use)
    root["transitive_workflows"] = [
        {
            "uses": workflow_use,
            "source_content_sha256": "0" * 64,
            "transitive_uses": [
                "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
                "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020",
            ],
            "transitive_workflows": [],
        }
    ]
    return contract


def test_repository_reusable_workflow_callers_match_contracts() -> None:
    assert scan(_repo_root()) == []


def test_contract_rejects_lower_permission_and_secret_fanout(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    caller = tmp_path / ".github/workflows/pr-heimgewebe-commands.yml"
    valid_use = _contract()["contracts"][0]["uses"]
    caller.write_text(
        f"""\npermissions:\n  contents: read\njobs:\n  dispatch:\n    if: github.event.issue.pull_request != null\n    uses: {valid_use}\n    secrets:\n      inherit: true\n""",
        encoding="utf-8",
    )
    codes = {finding.code for finding in scan(tmp_path)}
    assert codes == {
        "insufficient_caller_permission",
        "caller_secret_contract_mismatch",
        "missing_caller_condition",
    }


def test_contract_rejects_stale_wgx_guard_pin(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    wgx_caller = tmp_path / ".github/workflows/wgx-guard.yml"
    wgx_caller.write_text(
        """\npermissions:\n  contents: read\njobs:\n  guard:\n    uses: heimgewebe/wgx/.github/workflows/wgx-guard.yml@b3b358f5bb8d26f087fcdaf25d308d439b22f583\n""",
        encoding="utf-8",
    )
    findings = scan(tmp_path)
    assert [(finding.caller_path, finding.code) for finding in findings] == [
        (".github/workflows/wgx-guard.yml", "reusable_workflow_pin_mismatch")
    ]


def test_contract_reports_missing_caller_file(tmp_path: Path) -> None:
    target = tmp_path / ".github/reusable-workflow-contracts.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(_contract()), encoding="utf-8")
    findings = scan(tmp_path)
    assert {(finding.caller_path, finding.code) for finding in findings} == {
        (".github/workflows/pr-heimgewebe-commands.yml", "missing_caller_file"),
        (".github/workflows/wgx-guard.yml", "missing_caller_file"),
    }


def test_contract_rejects_mutable_direct_transitive_ref(tmp_path: Path) -> None:
    contract = _contract()
    contract["contracts"][0]["transitive_uses"][0] = (
        "actions/create-github-app-token@v3"
    )
    _write_fixture(tmp_path, contract)
    assert [finding.code for finding in scan(tmp_path)] == [
        "mutable_transitive_action_ref"
    ]


def test_contract_rejects_invalid_root_source_hash(tmp_path: Path) -> None:
    contract = _contract()
    contract["contracts"][1]["source_content_sha256"] = "not-a-sha256"
    _write_fixture(tmp_path, contract)
    assert [finding.code for finding in scan(tmp_path)] == [
        "invalid_source_content_sha256"
    ]


def test_contract_rejects_missing_recursive_workflow_closure(tmp_path: Path) -> None:
    contract = _contract_with_recursive_workflow()
    contract["contracts"][1]["transitive_workflows"] = []
    _write_fixture(tmp_path, contract)
    assert [finding.code for finding in scan(tmp_path)] == [
        "transitive_workflow_closure_mismatch"
    ]


def test_contract_rejects_detached_recursive_workflow_closure(tmp_path: Path) -> None:
    contract = _contract_with_recursive_workflow()
    closure = contract["contracts"][1]["transitive_workflows"][0]
    closure["uses"] = (
        "heimgewebe/metarepo/.github/workflows/other.yml@"
        "dda0d036b3b4db935d3acbaa4c1b0fc76637cea9"
    )
    _write_fixture(tmp_path, contract)
    assert [finding.code for finding in scan(tmp_path)] == [
        "transitive_workflow_closure_mismatch"
    ]


def test_contract_rejects_mutable_recursive_action_ref(tmp_path: Path) -> None:
    contract = _contract_with_recursive_workflow()
    closure = contract["contracts"][1]["transitive_workflows"][0]
    closure["transitive_uses"][1] = "actions/setup-node@v6"
    _write_fixture(tmp_path, contract)
    assert [finding.code for finding in scan(tmp_path)] == [
        "mutable_transitive_action_ref"
    ]


def test_contract_rejects_invalid_recursive_source_hash(tmp_path: Path) -> None:
    contract = _contract_with_recursive_workflow()
    closure = contract["contracts"][1]["transitive_workflows"][0]
    closure["source_content_sha256"] = "missing"
    _write_fixture(tmp_path, contract)
    assert [finding.code for finding in scan(tmp_path)] == [
        "invalid_source_content_sha256"
    ]


def test_contract_rejects_unrecorded_third_level_workflow(tmp_path: Path) -> None:
    contract = _contract_with_recursive_workflow()
    closure = contract["contracts"][1]["transitive_workflows"][0]
    closure["transitive_uses"].append(
        "example/inner/.github/workflows/check.yml@"
        "0123456789abcdef0123456789abcdef01234567"
    )
    _write_fixture(tmp_path, contract)
    assert [finding.code for finding in scan(tmp_path)] == [
        "transitive_workflow_closure_mismatch"
    ]
