from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MCP_BOUNDARY_DOC = REPO_ROOT / "docs/architecture/repoground-mcp-boundary.md"
REPOGROUND_DOC = REPO_ROOT / "docs/architecture/repoground.md"
MCP_USAGE_DOC = REPO_ROOT / "docs/usage/repoground-mcp-stdio.md"
MCP_LAUNCHER = REPO_ROOT / "scripts/repoground-mcp-stdio.py"

MCP_RESOURCES = (
    "repoground://snapshot/{stem}/manifest",
    "repoground://snapshot/{stem}/canonical",
    "repoground://snapshot/{stem}/reading-pack",
    "repoground://snapshot/{stem}/health",
    "repoground://snapshot/{stem}/availability",
    "repoground://snapshot/{stem}/artifact/{role}",
)

READ_ONLY_TOOLS = (
    "snapshot_list",
    "snapshot_status",
    "artifact_get",
    "required_reading_resolve",
    "range_get",
    "query_existing_index",
    "ask_context",
    "grounding_verify",
    "live_freshness",
)

FORBIDDEN_OPERATIONS = (
    "git_push",
    "git_pull",
    "git_fetch",
    "create_pr",
    "apply_patch",
    "run_shell",
    "auto_review",
    "auto_fix",
    "auto_merge",
    "secret_read",
    "snapshot_create_side_effect",
)

NEGATIVE_SEMANTICS = (
    "truth",
    "correctness",
    "completeness",
    "runtime_behavior",
    "test_sufficiency",
    "regression_absence",
    "repo_understood",
    "claims_true",
    "forensic_ready",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mcp_boundary_surfaces_exist() -> None:
    assert MCP_BOUNDARY_DOC.exists()
    assert MCP_USAGE_DOC.exists()
    assert MCP_LAUNCHER.exists()


def test_mcp_boundary_doc_lists_resources() -> None:
    text = _read(MCP_BOUNDARY_DOC)

    for resource in MCP_RESOURCES:
        assert f"`{resource}`" in text

    assert "Resources-first surface" in text
    assert "read-only views over files that already exist" in text


def test_mcp_boundary_doc_lists_read_only_tools_and_create_boundary() -> None:
    text = _read(MCP_BOUNDARY_DOC)

    for tool in READ_ONLY_TOOLS:
        assert f"`{tool}`" in text

    assert "Read-only tools must not write files" in text
    assert "refresh bundles" in text
    assert "create snapshots" in text
    assert "`snapshot_create`" in text
    assert "may write only Brief Bundle" in text
    assert "must not be reachable as a side effect" in text
    assert "merger.repoground.core.mcp_tools" in text
    assert "does not list or accept `snapshot_create` by default" in text


def test_mcp_boundary_doc_names_local_stdio_server_and_launcher() -> None:
    text = _read(MCP_BOUNDARY_DOC)

    assert "Local stdio protocol server" in text
    assert "merger.repoground.cli.mcp_stdio" in text
    assert "scripts/repoground-mcp-stdio.py" in text
    assert "tools/list" in text
    assert "resources/read" in text
    assert "newline-delimited" in text
    assert "not a networked MCP protocol server" in text
    assert "no TCP/HTTP listener" in text


def test_mcp_boundary_doc_binds_snapshot_create_to_startup_paths() -> None:
    text = _read(MCP_BOUNDARY_DOC)

    assert "both `--enable-snapshot-create` and an explicit `--repo-root`" in text
    assert "source repository is fixed to the startup `--repo-root`" in text
    assert "output root is fixed to the startup `--bundle-root`" in text
    assert "cannot supply replacement `repo` or `output_root`" in text
    assert "explicit snapshot profile" in text
    assert "timeout, size, output-path" in text


def test_mcp_boundary_doc_lists_forbidden_operations() -> None:
    text = _read(MCP_BOUNDARY_DOC)

    for operation in FORBIDDEN_OPERATIONS:
        assert f"`{operation}`" in text


def test_mcp_boundary_doc_preserves_negative_semantics() -> None:
    text = _read(MCP_BOUNDARY_DOC)

    for semantic in NEGATIVE_SEMANTICS:
        assert f"`{semantic}`" in text

    assert "does not establish" in text


def test_mcp_boundary_doc_says_reads_do_not_refresh_or_write() -> None:
    text = _read(MCP_BOUNDARY_DOC)

    assert "reads existing Brief Bundles" in text
    assert "Reading a bundle must never trigger snapshot" in text
    assert "Read-only tools must not write files" in text
    assert "A stale, missing, degraded, or invalid snapshot must be reported" in text
    assert "silently regenerated" in text


def test_mcp_boundary_doc_bounds_live_git_probe() -> None:
    text = _read(MCP_BOUNDARY_DOC)

    assert "Bounded local Git probe" in text
    assert "operator-provided `--repo-root`" in text
    assert "manifest-recorded local path remains evidence only" in text
    assert "disables optional locks" in text
    assert "ignores global and system Git configuration" in text
    assert "Missing cleanliness evidence" in text
    assert "never invokes `git_fetch`, `git_pull`, or `git_push`" in text
    assert "No Git subprocess runs when `--repo-root` is absent" in text


def test_repoground_doc_links_to_implemented_mcp_surface() -> None:
    text = _read(REPOGROUND_DOC)
    compact = " ".join(text.split())

    assert "[RepoGround MCP Boundary](repoground-mcp-boundary.md)" in compact
    assert "local MCP stdio server" in compact
    assert "binds the existing read-only resource and tool handlers" in compact
    assert "it is not a network service" in compact
    assert "explicit `snapshot_create` handler remains hidden" in compact
    assert "[RepoGround MCP stdio](../usage/repoground-mcp-stdio.md)" in compact


def test_mcp_boundary_doc_names_concrete_readonly_resource_adapter() -> None:
    text = _read(MCP_BOUNDARY_DOC)

    assert "merger.repoground.core.mcp_resources" in text
    assert "`manifest`, `canonical`, `reading-pack`, `health`, `availability`" in text
    assert "health, freshness, and availability context" in text


def test_mcp_usage_doc_has_stable_start_and_client_configuration() -> None:
    text = _read(MCP_USAGE_DOC)

    assert "python3 /absolute/path/to/repoground/scripts/repoground-mcp-stdio.py" in text
    assert "python3 -m merger.repoground.cli.mcp_stdio" in text
    assert '"mcpServers"' in text
    assert '"repoground": {' in text
    assert '"/absolute/path/to/repoground/scripts/repoground-mcp-stdio.py"' in text
    assert "--bundle-root" in text
    assert "--repo-root" in text
    assert "--enable-snapshot-create" in text
    assert "cannot choose another source repository or output root" in text
    assert "repo_root_not_configured" not in text
