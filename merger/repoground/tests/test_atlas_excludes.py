from pathlib import Path

from merger.repoground.adapters.atlas import AtlasScanner


def test_atlas_excludes_match_top_level_and_nested(tmp_path: Path) -> None:
    # Pure path semantics; no filesystem touch required.
    scanner = AtlasScanner(
        tmp_path,
        snapshot_id="dummy_snap",
        exclude_globs=[
            "**/.git/**",
            "**/node_modules/**",
            "**/.venv/**",
            "**/__pycache__/**",
            "**/.cache/**",
        ],
    )

    assert scanner._is_excluded(tmp_path / ".git") is True
    assert scanner._is_excluded(tmp_path / ".git" / "config") is True
    assert scanner._is_excluded(tmp_path / "repo" / ".git" / "config") is True

    assert scanner._is_excluded(tmp_path / "node_modules" / "pkg" / "index.js") is True
    assert scanner._is_excluded(tmp_path / "nested" / "node_modules" / "pkg" / "index.js") is True

    assert scanner._is_excluded(tmp_path / ".venv" / "pyvenv.cfg") is True
    assert scanner._is_excluded(tmp_path / "nested" / ".venv" / "pyvenv.cfg") is True

    assert scanner._is_excluded(tmp_path / "__pycache__" / "mod.cpython-312.pyc") is True
    assert scanner._is_excluded(tmp_path / "pkg" / "__pycache__" / "mod.cpython-312.pyc") is True

    assert scanner._is_excluded(tmp_path / ".cache" / "pip" / "selfcheck.json") is True
    assert scanner._is_excluded(tmp_path / "nested" / ".cache" / "pip" / "selfcheck.json") is True

    assert scanner._is_excluded(tmp_path / "git" / "config") is False
    assert scanner._is_excluded(tmp_path / "repo" / "git" / "config") is False


def test_atlas_excludes_claude_worktrees_explicit(tmp_path: Path) -> None:
    # Test explicit exclude_globs for .claude/worktrees (not the default config).
    scanner = AtlasScanner(tmp_path, snapshot_id="dummy_snap", no_default_excludes=True, exclude_globs=["**/.claude/worktrees/**"])

    # Worktree paths must be excluded
    assert scanner._is_excluded(".claude/worktrees/citation-map-producer/.ai-context.yml") is True
    assert scanner._is_excluded(".claude/worktrees/ipad-dump-proof/merger/repoground/core/merge.py") is True
    assert scanner._is_excluded(".claude/worktrees/citation-map-producer/.github/workflows/test.yml") is True
    assert scanner._is_excluded(".claude/worktrees") is True
    assert scanner._is_excluded(".claude/worktrees/citation-map-producer") is True

    # Legitimate .claude files must NOT be excluded
    assert scanner._is_excluded(".claude/settings.local.json") is False
    assert scanner._is_excluded(".claude/settings.json") is False

    # Normal repo files must NOT be excluded
    assert scanner._is_excluded("merger/repoground/core/citation_map.py") is False
    assert scanner._is_excluded("merger/repoground/adapters/atlas.py") is False
    assert scanner._is_excluded("docs/proofs/citation-map-producer-proof.md") is False


def test_atlas_default_non_strict_excludes_claude_worktrees(tmp_path: Path) -> None:
    # Non-strict default scanner must exclude .claude/worktrees without explicit config;
    # legitimate .claude config files must remain visible.
    scanner = AtlasScanner(tmp_path, snapshot_id="dummy_snap")  # non-strict defaults

    assert scanner._is_excluded(".claude/worktrees/some-branch/file.py") is True
    assert scanner._is_excluded(".claude/settings.json") is False

    # node_modules is excluded in non-strict mode
    assert scanner._is_excluded("node_modules/pkg/index.js") is True


def test_atlas_default_strict_excludes_claude_worktrees(tmp_path: Path) -> None:
    # Strict default scanner must also exclude .claude/worktrees: they are agent runtime
    # checkouts, not canonical repository content, regardless of inventory mode.
    scanner = AtlasScanner(tmp_path, snapshot_id="dummy_snap", inventory_strict=True)

    assert scanner._is_excluded(".claude/worktrees/some-branch/file.py") is True
    assert scanner._is_excluded(".claude/worktrees") is True
    assert scanner._is_excluded(".claude/settings.json") is False

    # In strict mode, node_modules is NOT in the default excludes
    # (strict = minimal excludes; callers control what's excluded beyond git/venv/worktrees)
    assert scanner._is_excluded("node_modules/pkg/index.js") is False


def test_atlas_default_excludes_core_dumps_at_any_depth(tmp_path: Path) -> None:
    scanner = AtlasScanner(tmp_path, snapshot_id="dummy_snap")

    for path in (
        "core",
        "core.61224",
        "process.core",
        "nested/core",
        "nested/core.2",
        "nested/process.core",
    ):
        assert scanner._is_excluded(path) is True

    assert scanner._is_excluded("core.py") is False
    assert scanner._is_excluded("nested/score.txt") is False


def test_atlas_can_explicitly_disable_default_core_excludes(tmp_path: Path) -> None:
    scanner = AtlasScanner(
        tmp_path,
        snapshot_id="dummy_snap",
        no_default_excludes=True,
        exclude_globs=[],
    )

    assert scanner._is_excluded("core.123") is False
