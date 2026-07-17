from merger.repoground.tests._test_constants import make_generator_info

import re
import sys
import os
from pathlib import Path
from typing import Dict

# Add parent directory to path to allow importing lenskit
# Matches existing test pattern: merger/repoground/tests -> ../.. -> merger/
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

try:
    import yaml
except ImportError:
    yaml = None

from merger.repoground.core import merge
from merger.repoground.core.merge import FileInfo, ExtrasConfig

class ReportParser:
    """
    A robust, stack-based parser to verify machine-readability of repoLens reports.
    Supports nested zones and strict start/end matching.
    """
    def __init__(self, content: str):
        self.content = content
        self.zones = []
        self.artifacts = []
        self.file_markers = []
        self.meta = {}
        self._parse()

    def _parse(self):
        # Combined regex for finding tags in order
        # Group 1: begin quoted type
        # Group 2: begin unquoted type
        # Group 3: begin attrs
        # Group 4: end quoted type
        # Group 5: end unquoted type
        # Group 6: end attrs (optional, e.g. id=...)
        # Note: We match <!-- zone:begin ... --> OR <!-- zone:end ... -->
        # Dual-read: support both quoted and unquoted type for migration testing
        token_pattern = re.compile(
            r'<!-- zone:begin type=(?:"([^"]+)"|([a-zA-Z0-9_-]+))(.*?) -->|<!-- zone:end\s+type=(?:"([^"]+)"|([a-zA-Z0-9_-]+))(.*?) -->',
            re.DOTALL
        )

        stack = [] # List of dicts: {type, start_content, attrs}

        for match in token_pattern.finditer(self.content):
            # 1, 2 = begin (quoted, unquoted); 4, 5 = end (quoted, unquoted)
            is_begin = match.group(1) is not None or match.group(2) is not None

            if is_begin:
                z_type = match.group(1) or match.group(2)
                z_attrs_str = match.group(3)
                attrs = self._parse_attrs(z_attrs_str)
                stack.append({
                    "type": z_type,
                    "attrs": attrs,
                    "start_content": match.end(),
                    "start_tag": match.start()
                })
            else:
                # is end
                end_type = match.group(4) or match.group(5)

                if not stack:
                    raise ValueError(f"Orphaned end tag at {match.start()}")

                # Pop the last open zone
                open_zone = stack.pop()

                # Verify type matching
                if end_type != open_zone['type']:
                    raise ValueError(f"Zone mismatch: Expected closing {open_zone['type']}, got {end_type} at {match.start()}")

                # Record the zone
                self.zones.append({
                    "type": open_zone['type'],
                    "attrs": open_zone['attrs'],
                    "content": self.content[open_zone['start_content']:match.start()],
                    "start": open_zone['start_tag'],
                    "end": match.end()
                })

        if stack:
            raise ValueError(f"Unclosed zones: {[z['type'] for z in stack]}")

    def _parse_attrs(self, attr_str: str) -> Dict[str, str]:
        # Robust attribute parser: key=value or key="value with spaces"
        attrs = {}
        # Regex matches key="value" or key=value
        # Allow alphanumeric, underscore, and hyphens in keys (future-proofing)
        pattern = re.compile(r'([a-zA-Z0-9_-]+)=(?:"([^"]*)"|(\S+))')
        for match in pattern.finditer(attr_str):
            key = match.group(1)
            val = match.group(2) if match.group(2) is not None else match.group(3)
            attrs[key] = val
        return attrs

    def extract_artifacts(self):
        # <!-- artifact:type basename="name" -->
        pattern = re.compile(r'<!-- artifact:(\w+)\s+basename="(.*?)" -->')
        for match in pattern.finditer(self.content):
            self.artifacts.append({
                "type": match.group(1),
                "basename": match.group(2)
            })
        return self.artifacts

    def extract_file_markers(self):
        # <!-- file:id=... path=... -->
        # Now supporting quoted paths: path="foo bar" and quoted id: id="FILE:..."
        # Updated regex to handle both quoted and unquoted IDs for robustness
        pattern = re.compile(r'<!-- file:id=(?:"([^"]+)"|([^\s]+))\s+path=(?:"([^"]+)"|(\S+)) -->')
        for match in pattern.finditer(self.content):
            fid = match.group(1) if match.group(1) else match.group(2)
            path = match.group(3) if match.group(3) else match.group(4)
            self.file_markers.append({
                "id": fid,
                "path": path
            })
        return self.file_markers

    def parse_meta(self):
        # Find meta zone
        for z in self.zones:
            if z['type'] == 'meta':
                # Extract yaml block
                match = re.search(r'```yaml\n(.*?)\n```', z['content'], re.DOTALL)
                if match and yaml:
                    self.meta = yaml.safe_load(match.group(1))
                elif not yaml:
                    self.meta = {"error": "PyYAML missing"}
                break
        return self.meta

    def get_manifest_header(self):
        for z in self.zones:
            if z['type'] == 'manifest':
                # Look for table header
                lines = z['content'].strip().splitlines()
                for line in lines:
                    if line.startswith("|") and "Path" in line and "Category" in line:
                        return line
        return None

def test_generated_report_is_parsable(tmp_path):
    # Setup
    root = tmp_path / "repo"
    root.mkdir()
    (root / "src").mkdir()
    f1 = root / "src/main.py"
    f1.write_text("print('hello')", encoding="utf-8")

    fi = FileInfo(
        root_label="repo",
        abs_path=f1,
        rel_path=Path("src/main.py"),
        size=100,
        is_text=True,
        md5="abc",
        category="source",
        tags=[],
        ext=".py",
        content=None,
        inclusion_reason="normal"
    )
    # Explicitly set roles to trigger role_semantics deterministically
    fi.roles = ["explicit_role"]

    files = [fi]

    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()

    extras = ExtrasConfig(json_sidecar=True, augment_sidecar=True) # augment won't be found but logic runs

    # Generate
    artifacts = merge.write_reports_v2(generator_info=make_generator_info(),
        merges_dir=merges_dir,
        hub=tmp_path,
        repo_summaries=[{"name": "repo", "files": files, "root": root}],
        detail="dev",
        mode="single",
        max_bytes=1000,
        plan_only=False,
        extras=extras
    )

    md_content = artifacts.canonical_md.read_text(encoding="utf-8")

    # Parse
    parser = ReportParser(md_content)

    # 1. Verify Zones
    zone_types = [z['type'] for z in parser.zones]
    assert "meta" in zone_types
    assert "manifest" in zone_types
    assert "code" in zone_types

    # Verify code zone has id attribute
    for z in parser.zones:
        if z['type'] == 'code':
            assert 'id' in z['attrs']
            assert z['attrs']['id'].startswith('FILE:')
            break

    # Verify meta/manifest/structure have ids (same as type)
    for ztype in ['meta', 'manifest', 'structure']:
        # Structure is optional (skipped for machine-lean), but we use dev profile in test
        # Structure is present in dev profile unless machine-lean
        found = False
        for z in parser.zones:
            if z['type'] == ztype:
                found = True
                assert 'id' in z['attrs'], f"Zone {ztype} missing id"
                assert z['attrs']['id'] == ztype
                break
        # manifest is mandatory unless code_only? dev has manifest.
        # structure has id=structure
        if ztype == 'structure' and 'structure' not in zone_types:
             pass # might be skipped if logic changes, but dev has it
        elif ztype == 'manifest':
             assert found, "Manifest zone not found"

    # 2. Verify Meta
    meta = parser.parse_meta()
    if yaml:
        assert meta["merge"]["role_semantics"] == "heuristic"
        assert meta["merge"]["depends_semantics"] == "placeholder"

    # 3. Verify Artifacts
    parser.extract_artifacts()
    art_types = [a['type'] for a in parser.artifacts]
    assert "index_json" in art_types
    # augment_sidecar won't be here because file didn't exist

    # 4. Verify File Markers
    parser.extract_file_markers()
    assert len(parser.file_markers) == 1
    assert parser.file_markers[0]['id'].startswith("FILE:")
    assert str(parser.file_markers[0]['path']) == "src/main.py"

    # 5. Verify Manifest Header
    header = parser.get_manifest_header()
    assert header is not None
    assert "Role?" in header
    assert "Depends?" in header

def test_quoting_paths_with_spaces(tmp_path):
    # Setup
    root = tmp_path / "repo"
    root.mkdir()
    (root / "my folder").mkdir()
    f1 = root / "my folder/my file.py"
    f1.write_text("print('hello')", encoding="utf-8")

    fi = FileInfo(
        root_label="repo",
        abs_path=f1,
        rel_path=Path("my folder/my file.py"),
        size=100,
        is_text=True,
        md5="abc",
        category="source",
        tags=[],
        ext=".py",
        content=None,
        inclusion_reason="normal"
    )

    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()

    # Generate
    artifacts = merge.write_reports_v2(generator_info=make_generator_info(),
        merges_dir=merges_dir,
        hub=tmp_path,
        repo_summaries=[{"name": "repo", "files": [fi], "root": root}],
        detail="dev",
        mode="single",
        max_bytes=1000,
        plan_only=False,
        extras=ExtrasConfig.none()
    )

    md_content = artifacts.canonical_md.read_text(encoding="utf-8")
    parser = ReportParser(md_content)
    parser.extract_file_markers()

    assert len(parser.file_markers) == 1
    # Check that we correctly parsed the path "my folder/my file.py" despite spaces
    # This implies the regex correctly handled quotes
    assert parser.file_markers[0]['path'] == "my folder/my file.py"

def test_no_roles_semantics(tmp_path):
    # Setup file without roles
    root = tmp_path / "repo"
    root.mkdir()
    f1 = root / "util.py"
    f1.write_text("pass", encoding="utf-8")

    fi = FileInfo(
        root_label="repo",
        abs_path=f1,
        rel_path=Path("util.py"),
        size=10,
        is_text=True,
        md5="def",
        category="source",
        tags=[],
        ext=".py",
        content=None,
        inclusion_reason="normal"
    )

    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()
    extras = ExtrasConfig.none()

    artifacts = merge.write_reports_v2(generator_info=make_generator_info(),
        merges_dir=merges_dir,
        hub=tmp_path,
        repo_summaries=[{"name": "repo", "files": [fi], "root": root}],
        detail="dev",
        mode="single",
        max_bytes=1000,
        plan_only=False,
        extras=extras
    )

    md_content = artifacts.canonical_md.read_text(encoding="utf-8")
    parser = ReportParser(md_content)
    meta = parser.parse_meta()

    if yaml:
        assert "role_semantics" not in meta["merge"]
        assert meta["merge"]["depends_semantics"] == "placeholder"

def test_json_marker_matches_markdown_marker(tmp_path):
    """
    Contract verification: JSON sidecar 'content_ref.marker' string must exist
    EXACTLY in the Markdown report (including quotes).
    """
    import json

    # Setup
    root = tmp_path / "repo"
    root.mkdir()
    f1 = root / "script.py"
    f1.write_text("print('hello')", encoding="utf-8")

    fi = FileInfo(
        root_label="repo",
        abs_path=f1,
        rel_path=Path("script.py"),
        size=100,
        is_text=True,
        md5="abc",
        category="source",
        tags=[],
        ext=".py",
        content=None,
        inclusion_reason="normal"
    )

    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()

    # Enable JSON sidecar
    extras = ExtrasConfig(json_sidecar=True)

    # Generate
    artifacts = merge.write_reports_v2(generator_info=make_generator_info(),
        merges_dir=merges_dir,
        hub=tmp_path,
        repo_summaries=[{"name": "repo", "files": [fi], "root": root}],
        detail="dev",
        mode="single",
        max_bytes=1000,
        plan_only=False,
        extras=extras
    )

    # Read artifacts
    assert artifacts.index_json and artifacts.index_json.exists()
    assert artifacts.canonical_md and artifacts.canonical_md.exists()

    md_content = artifacts.canonical_md.read_text(encoding="utf-8")
    json_content = json.loads(artifacts.index_json.read_text(encoding="utf-8"))

    # Get marker from JSON
    # Assumption: files[0] corresponds to our file (it's the only one)
    json_file_obj = json_content["files"][0]
    json_marker = json_file_obj["content_ref"]["marker"]

    # Verify string exact match in Markdown
    # The JSON marker should be something like 'file:id="FILE:..."'
    # It must appear inside the MD as <!-- file:id="FILE:..." ... -->
    # so we search for the exact string.
    assert json_marker in md_content, \
        f"JSON marker '{json_marker}' not found in Markdown content."

    # Harden: Ensure marker is unique (exactly once)
    assert md_content.count(json_marker) == 1, \
        f"JSON marker '{json_marker}' found {md_content.count(json_marker)} times, expected exactly 1."

    # Also verify it has quotes (anti-regression)
    assert 'file:id="' in json_marker or "file:id='" in json_marker, \
        f"JSON marker '{json_marker}' missing quotes around ID."

    # Verify HTML Anchor existence
    # json_file_obj["md_ref"]["anchor"] must be present as <a id="..."></a>
    anchor = json_file_obj["md_ref"]["anchor"]
    expected_anchor_tag = f'<a id="{anchor}"></a>'
    assert expected_anchor_tag in md_content, \
        f"HTML anchor tag '{expected_anchor_tag}' not found in Markdown."

    # Verify Fragment (sanity check)
    fragment = json_file_obj["md_ref"]["fragment"]
    assert fragment == "#" + anchor

    # Validate against Schema (Contract Hardness)
    # Ensure generated JSON complies with the strict schema
    import jsonschema

    # Contract v2
    schema_path = Path(__file__).parent.parent / "contracts/repolens-agent.v2.schema.json"
    assert schema_path.exists(), "Schema v2 file not found"

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=json_content, schema=schema)

def test_zone_end_parsing_with_attributes():
    """
    Verify that the parser correctly handles zone:end tags with attributes (e.g. id).
    """
    content = """
<!-- zone:begin type=code id=test1 -->
some code
<!-- zone:end type=code id=test1 -->
"""
    parser = ReportParser(content)
    assert len(parser.zones) == 1
    zone = parser.zones[0]
    assert zone['type'] == 'code'
    assert zone['attrs'].get('id') == 'test1'
    assert 'some code' in zone['content']
