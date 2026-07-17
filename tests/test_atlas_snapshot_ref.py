import pytest
from merger.repoground.cli.cmd_atlas import parse_snapshot_ref, SnapshotRefKind

def test_parse_snapshot_ref_id():
    parsed = parse_snapshot_ref("my-snapshot-123")
    assert parsed.kind == SnapshotRefKind.SNAPSHOT_ID
    assert parsed.value == "my-snapshot-123"

def test_parse_snapshot_ref_machine_path():
    parsed = parse_snapshot_ref("heim-pc:/C/My Documents/ ")
    assert parsed.kind == SnapshotRefKind.MACHINE_PATH
    assert parsed.machine_id == "heim-pc"
    # value is NOT trimmed intentionally
    assert parsed.value == "/C/My Documents/ "

def test_parse_snapshot_ref_machine_label():
    parsed = parse_snapshot_ref("heim-pc : label : documents ")
    assert parsed.kind == SnapshotRefKind.MACHINE_LABEL
    # machine_id is trimmed
    assert parsed.machine_id == "heim-pc"
    # value is trimmed
    assert parsed.value == "documents"

def test_parse_snapshot_ref_machine_label_with_colons():
    # label itself might contain colons, since it's just the 3rd part of split(":", 2)
    parsed = parse_snapshot_ref("heim-pc:label:my:complex:label")
    assert parsed.kind == SnapshotRefKind.MACHINE_LABEL
    assert parsed.machine_id == "heim-pc"
    assert parsed.value == "my:complex:label"

def test_parse_snapshot_ref_empty_fails():
    with pytest.raises(ValueError, match="cannot be empty"):
        parse_snapshot_ref("   ")

def test_parse_snapshot_ref_machine_label_empty_machine():
    with pytest.raises(ValueError, match="non-empty machine_id"):
        parse_snapshot_ref(" :label:docs")

def test_parse_snapshot_ref_machine_label_missing_label():
    with pytest.raises(ValueError, match="non-empty root_label"):
        parse_snapshot_ref("heim-pc:label")

def test_parse_snapshot_ref_machine_label_empty_label():
    with pytest.raises(ValueError, match="non-empty root_label"):
        parse_snapshot_ref("heim-pc:label:  ")

def test_parse_snapshot_ref_machine_path_empty_machine():
    with pytest.raises(ValueError, match="non-empty machine_id"):
        parse_snapshot_ref(" : /home/user")

def test_parse_snapshot_ref_machine_path_empty_path():
    with pytest.raises(ValueError, match="non-empty path"):
        parse_snapshot_ref("heim-pc:")
