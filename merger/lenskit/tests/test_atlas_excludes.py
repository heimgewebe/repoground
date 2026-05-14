from pathlib import Path

from merger.lenskit.adapters.atlas import AtlasScanner


def test_atlas_excludes_match_top_level_and_nested(tmp_path: Path) -> None:
    # Pure path semantics; no filesystem touch required.
    scanner = AtlasScanner(
        tmp_path,
        "dummy_snap",
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


def test_atlas_excludes_claude_worktrees(tmp_path: Path) -> None:
    # Verify .claude/worktrees is excluded by default (agent runtime artefacts, not repo content).
    scanner = AtlasScanner(tmp_path, "dummy_snap", no_default_excludes=True, exclude_globs=["**/.claude/worktrees/**"])

    # Worktree paths must be excluded
    assert scanner._is_excluded(".claude/worktrees/citation-map-producer/.ai-context.yml") is True
    assert scanner._is_excluded(".claude/worktrees/ipad-dump-proof/merger/lenskit/core/merge.py") is True
    assert scanner._is_excluded(".claude/worktrees/citation-map-producer/.github/workflows/test.yml") is True
    assert scanner._is_excluded(".claude/worktrees") is True
    assert scanner._is_excluded(".claude/worktrees/citation-map-producer") is True

    # Legitimate .claude files must NOT be excluded
    assert scanner._is_excluded(".claude/settings.local.json") is False
    assert scanner._is_excluded(".claude/settings.json") is False

    # Normal repo files must NOT be excluded
    assert scanner._is_excluded("merger/lenskit/core/citation_map.py") is False
    assert scanner._is_excluded("merger/lenskit/adapters/atlas.py") is False
    assert scanner._is_excluded("docs/proofs/citation-map-producer-proof.md") is False


def test_atlas_default_non_strict_excludes_claude_worktrees(tmp_path: Path) -> None:
    # Non-strict default scanner must exclude .claude/worktrees without explicit config;
    # legitimate .claude config files must remain visible.
    scanner = AtlasScanner(tmp_path, "dummy_snap")  # non-strict defaults

    assert scanner._is_excluded(".claude/worktrees/some-branch/file.py") is True
    assert scanner._is_excluded(".claude/settings.json") is False
