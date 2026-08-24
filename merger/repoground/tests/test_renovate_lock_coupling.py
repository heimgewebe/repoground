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
EXCLUDED_MULTI_LOCK_INPUTS = [
    "merger/repoground/requirements.txt",
    "merger/repoground/requirements-semantic.txt",
    "requirements/repoground-semantic-*",
]


def test_renovate_standard_python_updates_are_bound_to_canonical_lock_coupling() -> None:
    config = json.loads(RENOVATE_CONFIG.read_text(encoding="utf-8"))

    assert config["automerge"] is False
    task = config["postUpgradeTasks"]
    assert task["commands"] == [EXPECTED_COMMAND]
    assert task["executionMode"] == "branch"
    assert task["fileFilters"] == ["requirements*.txt", "requirements/**"]

    # The Ruff 0.16.4 regression changed this root input first. Standard
    # Renovate proposals must be allowed to carry their regenerated hash locks.
    assert any(fnmatch("requirements-dev.txt", pattern) for pattern in task["fileFilters"])
    assert any(
        fnmatch("requirements/repoground-dev.lock.txt", pattern)
        for pattern in task["fileFilters"]
    )


def test_multi_lock_requirements_are_excluded_from_generic_renovate_updates() -> None:
    config = json.loads(RENOVATE_CONFIG.read_text(encoding="utf-8"))

    assert config["packageRules"] == [
        {
            "description": (
                "Shared and semantic requirements require coordinated multi-lock regeneration"
            ),
            "matchFileNames": EXCLUDED_MULTI_LOCK_INPUTS,
            "enabled": False,
        }
    ]

    # The shared core input feeds both standard and semantic locks. Semantic
    # inputs additionally bind target-specific constraints and contract hashes.
    for path in (
        "merger/repoground/requirements.txt",
        "merger/repoground/requirements-semantic.txt",
        "requirements/repoground-semantic-linux-x86_64-py312.in",
        "requirements/repoground-semantic-linux-x86_64-py312.lock.txt",
    ):
        assert any(fnmatch(path, pattern) for pattern in EXCLUDED_MULTI_LOCK_INPUTS)


def test_repo_config_cannot_grant_global_command_or_merge_authority() -> None:
    config = json.loads(RENOVATE_CONFIG.read_text(encoding="utf-8"))

    assert "allowedCommands" not in config
    assert config.get("automerge") is False
    assert "platformAutomerge" not in config
