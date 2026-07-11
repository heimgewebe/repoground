from pathlib import Path

from scripts.ci.check_reusable_workflow_contracts import scan


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_repository_reusable_workflow_callers_match_contracts() -> None:
    assert scan(_repo_root()) == []


def test_contract_rejects_lower_permission_and_secret_fanout(tmp_path: Path) -> None:
    contract_source = _repo_root() / ".github/reusable-workflow-contracts.json"
    contract_target = tmp_path / ".github/reusable-workflow-contracts.json"
    contract_target.parent.mkdir(parents=True)
    contract_target.write_bytes(contract_source.read_bytes())
    caller = tmp_path / ".github/workflows/pr-heimgewebe-commands.yml"
    caller.parent.mkdir(parents=True)
    caller.write_text(
        """\npermissions:\n  contents: read\njobs:\n  dispatch:\n    if: github.event.issue.pull_request != null\n    uses: heimgewebe/metarepo/.github/workflows/heimgewebe-command-dispatch.yml@10daa1c84469dce76e93cdc24c47c1dfc5e156d6\n    secrets:\n      inherit: true\n""",
        encoding="utf-8",
    )
    codes = {finding.code for finding in scan(tmp_path)}
    assert codes == {
        "insufficient_caller_permission",
        "caller_secret_contract_mismatch",
        "missing_caller_condition",
    }
