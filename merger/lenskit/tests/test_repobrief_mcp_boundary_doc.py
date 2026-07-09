from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MCP_BOUNDARY_DOC = REPO_ROOT / "docs/architecture/repobrief-mcp-boundary.md"
REPOBRIEF_DOC = REPO_ROOT / "docs/architecture/repobrief.md"

MCP_RESOURCES = (
    "repobrief://snapshot/{stem}/manifest",
    "repobrief://snapshot/{stem}/canonical",
    "repobrief://snapshot/{stem}/reading-pack",
    "repobrief://snapshot/{stem}/health",
    "repobrief://snapshot/{stem}/availability",
    "repobrief://snapshot/{stem}/artifact/{role}",
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


def test_mcp_boundary_doc_exists() -> None:
    assert MCP_BOUNDARY_DOC.exists()


def test_mcp_boundary_doc_lists_planned_resources() -> None:
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
    assert "may write only Brief Bundle artifacts" in text
    assert "must not be reachable as a side effect" in text
    assert "merger.lenskit.core.repobrief_mcp_tools" in text
    assert "not an MCP protocol server" in text


def test_mcp_boundary_doc_lists_snapshot_create_guards() -> None:
    text = _read(MCP_BOUNDARY_DOC)

    for guard in (
        "explicit repository",
        "explicit snapshot profile",
        "controlled output root",
        "timeout guard",
        "size guard",
    ):
        assert guard in text


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
    assert "Reading a bundle must never trigger snapshot creation" in text
    assert "Read-only tools must not write files" in text
    assert "A stale, missing, degraded, or invalid snapshot must be reported" in text
    assert "silently regenerated" in text


def test_repobrief_doc_links_to_mcp_boundary_without_claiming_implementation() -> None:
    text = _read(REPOBRIEF_DOC)

    assert "[RepoBrief MCP Boundary](repobrief-mcp-boundary.md)" in text
    assert "code-level `snapshot_create` tool handler exists" in text
    assert "does not assert that an MCP server" in text
