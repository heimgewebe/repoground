import re

from merger.repoground.tests._test_constants import make_generator_info
from merger.repoground.core.merge import write_reports_v2, scan_repo, ExtrasConfig

def test_zone_markers_symmetry_integration(tmp_path):
    """
    Verifies that every <!-- zone:begin ... --> tag has a corresponding
    <!-- zone:end ... --> tag with identical type and id attributes,
    using a real repository scan and report generation.
    """
    # 1. Setup minimal repo structure
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    (repo_root / "src").mkdir()
    (repo_root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (repo_root / "README.md").write_text("# Readme\n", encoding="utf-8")
    (repo_root / "docs").mkdir()
    (repo_root / "docs" / "info.txt").write_text("Info", encoding="utf-8")

    # 2. Scan Repo
    summary = scan_repo(repo_root, calculate_md5=False, include_hidden=True)

    # 3. Generate Report
    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()
    hub_dir = tmp_path / "hub"
    hub_dir.mkdir()

    artifacts = write_reports_v2(generator_info=make_generator_info(),
        merges_dir=merges_dir,
        hub=hub_dir,
        repo_summaries=[summary],
        detail="max",
        mode="gesamt",
        max_bytes=0,
        plan_only=False,
        output_mode="archive", # No chunks needed for this test
        extras=ExtrasConfig(json_sidecar=False) # Keep it simple
    )

    assert artifacts.canonical_md is not None
    assert artifacts.canonical_md.exists()

    report_content = artifacts.canonical_md.read_text(encoding="utf-8")

    # 4. Parse and Validate Zones
    # Regex to find zone markers: captures 1=begin|end, 2=attributes
    zone_pattern = re.compile(r"<!-- zone:(begin|end)\s+(.+?)\s*-->")

    zones = []

    for match in zone_pattern.finditer(report_content):
        kind = match.group(1) # begin or end
        attrs_str = match.group(2)

        # Parse attributes (key=value)
        # Using a simple regex that handles quoted and unquoted values
        attr_pattern = re.compile(r'([a-zA-Z0-9_]+)=(?:"(.*?)"|(\S+))')
        attrs = {}
        for am in attr_pattern.finditer(attrs_str):
            key = am.group(1)
            # Value is group 2 (quoted content) or group 3 (unquoted)
            val = am.group(2) if am.group(2) is not None else am.group(3)
            attrs[key] = val

        zones.append({"kind": kind, "attrs": attrs, "raw": match.group(0)})

    # Stack for validating nesting and symmetry
    stack = []

    # We expect at least these zones: meta, structure, index, manifest
    # Note: 'code' zone is optional depending on content presence, so we don't strictly enforce it here to avoid flakiness
    expected_types = {"meta", "structure", "index", "manifest"}
    found_types = set()

    for z in zones:
        if z["kind"] == "begin":
            stack.append(z)
            found_types.add(z["attrs"].get("type"))
        elif z["kind"] == "end":
            assert len(stack) > 0, f"Found zone:end without zone:begin: {z['raw']}"
            start_zone = stack.pop()

            # Check Symmetry
            # 1. Type must match
            assert start_zone["attrs"].get("type") == z["attrs"].get("type"), \
                f"Zone type mismatch: {start_zone['raw']} vs {z['raw']}"

            # 2. ID must match
            # Note: id is required for strict symmetry
            start_id = start_zone["attrs"].get("id")
            end_id = z["attrs"].get("id")

            assert start_id is not None, f"zone:begin missing id: {start_zone['raw']}"
            assert end_id is not None, f"zone:end missing id: {z['raw']}"
            assert start_id == end_id, f"Zone ID mismatch: {start_zone['raw']} vs {z['raw']}"

    assert len(stack) == 0, f"Unclosed zones remaining: {[z['raw'] for z in stack]}"

    # Ensure we actually tested the relevant zones
    for t in expected_types:
        assert t in found_types, f"Expected zone type '{t}' not found in report"

if __name__ == "__main__":
    # Manually run if executed as script
    # pytest will handle the tmp_path fixture automatically
    pass
