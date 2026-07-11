from pathlib import Path

import yaml

from scripts.ci.check_github_actions_pins import scan


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_repository_has_only_immutable_external_action_refs() -> None:
    root = Path(__file__).resolve().parents[3]
    assert scan(root) == []


def test_mutable_action_and_reusable_workflow_refs_are_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path,
        ".github/workflows/test.yml",
        """jobs:\n  test:\n    steps:\n      - uses: actions/checkout@v5\n      - uses: owner/repo/.github/workflows/test.yml@main\n""",
    )
    findings = scan(tmp_path)
    assert [item.code for item in findings] == [
        "mutable_action_ref",
        "mutable_action_ref",
    ]


def test_full_sha_local_action_and_digest_are_accepted(tmp_path: Path) -> None:
    _write(
        tmp_path,
        ".github/workflows/test.yml",
        """jobs:\n  test:\n    steps:\n      - uses: actions/checkout@0123456789abcdef0123456789abcdef01234567\n      - uses: ./.github/actions/local\n      - uses: docker://example.invalid/tool@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n""",
    )
    assert scan(tmp_path) == []


def test_mutable_docker_tag_is_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path,
        ".github/actions/test/action.yml",
        """runs:\n  using: docker\n  image: Dockerfile\nsteps:\n  - uses: docker://example.invalid/tool:latest\n""",
    )
    findings = scan(tmp_path)
    assert len(findings) == 1
    assert findings[0].code == "mutable_docker_reference"


def test_shell_block_text_that_mentions_uses_is_not_parsed(tmp_path: Path) -> None:
    _write(
        tmp_path,
        ".github/workflows/test.yml",
        """jobs:\n  test:\n    steps:\n      - run: |\n          echo 'uses: actions/checkout@v1'\n          if [[ \"$line\" == uses:* ]]; then exit 1; fi\n      - uses: actions/checkout@0123456789abcdef0123456789abcdef01234567\n""",
    )
    assert scan(tmp_path) == []


def test_sensitive_workflows_keep_minimum_permissions_and_explicit_secrets() -> None:
    root = Path(__file__).resolve().parents[3]

    metrics = yaml.safe_load(
        (root / ".github/workflows/metrics.yml").read_text(encoding="utf-8")
    )
    assert metrics["permissions"] == {"contents": "read"}

    command = yaml.safe_load(
        (root / ".github/workflows/pr-heimgewebe-commands.yml").read_text(
            encoding="utf-8"
        )
    )
    assert command["permissions"] == {"contents": "read"}
    assert set(command["jobs"]["dispatch"]["secrets"]) == {
        "HEIMGEWEBE_APP_ID",
        "HEIMGEWEBE_APP_PRIVATE_KEY",
    }

    claude = yaml.safe_load(
        (root / ".github/workflows/claude.yml").read_text(encoding="utf-8")
    )
    assert claude["jobs"]["claude"]["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
        "issues": "write",
        "id-token": "write",
    }
