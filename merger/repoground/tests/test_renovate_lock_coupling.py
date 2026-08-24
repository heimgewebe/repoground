from __future__ import annotations

from fnmatch import fnmatch
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RENOVATE_CONFIG = ROOT / "renovate.json"
EXPECTED_COMMAND = (
    "bash /home/alex/.local/share/renovate-fleet/current/automation/renovate/"
    "repoground-lock-coupling.sh"
)


def test_renovate_python_updates_are_bound_to_canonical_lock_coupling() -> None:
    config = json.loads(RENOVATE_CONFIG.read_text(encoding="utf-8"))

    assert config["automerge"] is False
    task = config["postUpgradeTasks"]
    assert task["commands"] == [EXPECTED_COMMAND]
    assert task["executionMode"] == "branch"
    assert task["fileFilters"] == ["requirements*.txt", "requirements/**"]

    # The regression from the Ruff 0.16.4 update changed this root input first;
    # the same Renovate proposal must now be allowed to carry the canonical lock output.
    assert any(fnmatch("requirements-dev.txt", pattern) for pattern in task["fileFilters"])
    assert any(
        fnmatch("requirements/repoground-dev.lock.txt", pattern)
        for pattern in task["fileFilters"]
    )


def test_repo_config_cannot_grant_global_command_or_merge_authority() -> None:
    config = json.loads(RENOVATE_CONFIG.read_text(encoding="utf-8"))

    assert "allowedCommands" not in config
    assert config.get("automerge") is False
    assert "platformAutomerge" not in config
