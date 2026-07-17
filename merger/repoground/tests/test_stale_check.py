import json
import sqlite3
from merger.repoground.cli.stale_check import check_stale_index, _compute_file_sha256

def test_stale_check_warns_on_mismatch(tmp_path, capsys):
    # Setup paths
    base_name = "test_run"
    index_path = tmp_path / f"{base_name}.chunk_index.index.sqlite"
    dump_path = tmp_path / f"{base_name}.dump_index.json"
    derived_path = tmp_path / f"{base_name}.derived_index.json"

    # Create dummy files
    index_path.write_text("dummy index", encoding="utf-8")

    # Dump has content that will generate hash A
    dump_path.write_text("dummy dump version 2", encoding="utf-8")

    # Derived manifest records an OLD hash (simulating staleness)
    derived_data = {"canonical_dump_index_sha256": "old_hash_xyz"}
    derived_path.write_text(json.dumps(derived_data), encoding="utf-8")

    check_stale_index(index_path)

    captured = capsys.readouterr()
    assert "Warning: The index" in captured.err
    assert "stale" in captured.err

def test_stale_check_silent_on_match(tmp_path, capsys):
    base_name = "test_run"
    index_path = tmp_path / f"{base_name}.chunk_index.index.sqlite"
    dump_path = tmp_path / f"{base_name}.dump_index.json"
    derived_path = tmp_path / f"{base_name}.derived_index.json"

    index_path.write_text("dummy index", encoding="utf-8")

    # Dump has content
    dump_path.write_text("dummy dump version 1", encoding="utf-8")
    actual_hash = _compute_file_sha256(dump_path)

    # Derived manifest records the CORRECT hash
    derived_data = {"canonical_dump_index_sha256": actual_hash}
    derived_path.write_text(json.dumps(derived_data), encoding="utf-8")

    check_stale_index(index_path)

    captured = capsys.readouterr()
    assert captured.err == ""

def test_stale_check_fail_policy_missing_manifest(tmp_path, capsys):
    # Tests that when stale_policy="fail" and manifests are missing, it fails
    base_name = "test_run"
    index_path = tmp_path / f"{base_name}.chunk_index.index.sqlite"
    index_path.write_text("dummy index", encoding="utf-8")

    result = check_stale_index(index_path, stale_policy="fail")

    captured = capsys.readouterr()
    assert result is True
    assert "Cannot determine staleness/validity" in captured.err
    assert "(policy=fail)" in captured.err
    assert "dump manifest missing" in captured.err

def test_stale_check_fail_policy_ambiguous_manifest(tmp_path, capsys):
    index_path = tmp_path / "x.index.sqlite"
    index_path.write_text("dummy", encoding="utf-8")

    # Two derived indices and Two dump indices
    derived_path1 = tmp_path / "foo.derived_index.json"
    derived_path2 = tmp_path / "bar.derived_index.json"
    dump_path1 = tmp_path / "foo.dump_index.json"
    dump_path2 = tmp_path / "bar.dump_index.json"

    dump_path1.write_text("dummy1", encoding="utf-8")
    dump_path2.write_text("dummy2", encoding="utf-8")
    derived_data = {"canonical_dump_index_sha256": "old_hash_xyz"}
    derived_path1.write_text(json.dumps(derived_data), encoding="utf-8")
    derived_path2.write_text(json.dumps(derived_data), encoding="utf-8")

    result = check_stale_index(index_path, stale_policy="fail")

    captured = capsys.readouterr()
    assert result is True
    assert "Cannot determine staleness/validity" in captured.err
    assert "(policy=fail)" in captured.err
    assert "missing/ambiguous manifests or dump" in captured.err

def test_stale_check_ignore_policy_on_mismatch(tmp_path, capsys):
    base_name = "test_run"
    index_path = tmp_path / f"{base_name}.chunk_index.index.sqlite"
    dump_path = tmp_path / f"{base_name}.dump_index.json"
    derived_path = tmp_path / f"{base_name}.derived_index.json"

    index_path.write_text("dummy index", encoding="utf-8")
    dump_path.write_text("dummy dump version 2", encoding="utf-8")

    derived_data = {"canonical_dump_index_sha256": "old_hash_xyz"}
    derived_path.write_text(json.dumps(derived_data), encoding="utf-8")

    result = check_stale_index(index_path, stale_policy="ignore")

    captured = capsys.readouterr()
    assert result is False
    assert captured.err == ""

def test_stale_check_fail_policy_on_mismatch(tmp_path, capsys):
    base_name = "test_run"
    index_path = tmp_path / f"{base_name}.chunk_index.index.sqlite"
    dump_path = tmp_path / f"{base_name}.dump_index.json"
    derived_path = tmp_path / f"{base_name}.derived_index.json"

    index_path.write_text("dummy index", encoding="utf-8")
    dump_path.write_text("dummy dump version 2", encoding="utf-8")

    derived_data = {"canonical_dump_index_sha256": "old_hash_xyz"}
    derived_path.write_text(json.dumps(derived_data), encoding="utf-8")

    result = check_stale_index(index_path, stale_policy="fail")

    captured = capsys.readouterr()
    assert result is True
    assert "is stale" in captured.err
    assert "Failing as per stale-policy" in captured.err

def test_stale_check_fallback_db(tmp_path, capsys):
    base_name = "test_run"
    index_path = tmp_path / f"{base_name}.chunk_index.index.sqlite"
    dump_path = tmp_path / f"{base_name}.dump_index.json"

    dump_path.write_text("dummy dump db content", encoding="utf-8")
    actual_hash = _compute_file_sha256(dump_path)

    # Missing derived_index.json
    # Create DB with index_meta
    with sqlite3.connect(str(index_path)) as conn:
        c = conn.cursor()
        c.execute("CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("INSERT INTO index_meta (key, value) VALUES ('canonical_dump_index_sha256', ?)", (actual_hash,))
        conn.commit()

    # Match -> silent pass
    result = check_stale_index(index_path, stale_policy="fail")
    assert result is False
    captured = capsys.readouterr()
    assert captured.err == ""

    # Mismatch -> fail
    with sqlite3.connect(str(index_path)) as conn:
        c = conn.cursor()
        c.execute("UPDATE index_meta SET value='bad_hash_from_db' WHERE key='canonical_dump_index_sha256'")
        conn.commit()

    result = check_stale_index(index_path, stale_policy="fail")
    assert result is True
    captured = capsys.readouterr()
    assert "Failing as per stale-policy" in captured.err

def test_stale_check_fallback_db_missing_dump(tmp_path, capsys):
    base_name = "test_run"
    index_path = tmp_path / f"{base_name}.chunk_index.index.sqlite"

    with sqlite3.connect(str(index_path)) as conn:
        c = conn.cursor()
        c.execute("CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("INSERT INTO index_meta (key, value) VALUES ('canonical_dump_index_sha256', 'some_hash')")
        conn.commit()

    # Missing dump -> cannot determine -> fail closed
    result = check_stale_index(index_path, stale_policy="fail")
    assert result is True
    captured = capsys.readouterr()
    assert "Cannot determine staleness/validity" in captured.err
    assert "(policy=fail)" in captured.err
    assert "dump manifest missing" in captured.err

def test_stale_check_fail_policy_wrong_extension(tmp_path, capsys):
    # Not an index.sqlite file
    wrong_path = tmp_path / "something_else.txt"
    wrong_path.write_text("txt", encoding="utf-8")

    result = check_stale_index(wrong_path, stale_policy="fail")

    captured = capsys.readouterr()
    assert result is True
    assert "Cannot determine staleness/validity" in captured.err
    assert "(policy=fail)" in captured.err
    assert "not an .index.sqlite file" in captured.err

def test_stale_check_fallback_discovery(tmp_path, capsys):
    # Create an index with an unrelated name
    index_path = tmp_path / "x.index.sqlite"
    index_path.write_text("dummy", encoding="utf-8")

    # Create EXACTLY one derived and one dump index
    derived_path = tmp_path / "foo.derived_index.json"
    dump_path = tmp_path / "foo.dump_index.json"

    dump_path.write_text("dummy dump version 2", encoding="utf-8")

    # Derived manifest records an OLD hash (simulating staleness)
    derived_data = {"canonical_dump_index_sha256": "old_hash_xyz"}
    derived_path.write_text(json.dumps(derived_data), encoding="utf-8")

    check_stale_index(index_path)

    captured = capsys.readouterr()
    assert "Warning: The index" in captured.err
    assert "stale" in captured.err

def test_stale_check_fallback_multiple_aborts(tmp_path, capsys):
    # Create an index with an unrelated name
    index_path = tmp_path / "x.index.sqlite"
    index_path.write_text("dummy", encoding="utf-8")

    # Create TWO derived indices and TWO dump indices, making fallback ambiguous
    derived_path1 = tmp_path / "foo.derived_index.json"
    derived_path2 = tmp_path / "bar.derived_index.json"
    dump_path1 = tmp_path / "foo.dump_index.json"
    dump_path2 = tmp_path / "bar.dump_index.json"

    dump_path1.write_text("dummy1", encoding="utf-8")
    dump_path2.write_text("dummy2", encoding="utf-8")
    derived_data = {"canonical_dump_index_sha256": "old_hash_xyz"}
    derived_path1.write_text(json.dumps(derived_data), encoding="utf-8")
    derived_path2.write_text(json.dumps(derived_data), encoding="utf-8")

    # default is warn, meaning fail-open -> silent abort
    check_stale_index(index_path)

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""

def test_stale_check_silent_on_missing_files(tmp_path, capsys):
    base_name = "test_run"
    index_path = tmp_path / f"{base_name}.chunk_index.index.sqlite"

    # Derived and Dump manifests are missing!
    index_path.write_text("dummy index", encoding="utf-8")

    check_stale_index(index_path)

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""

def test_stale_check_silent_on_wrong_extension(tmp_path, capsys):
    # Not an index.sqlite file
    wrong_path = tmp_path / "something_else.txt"
    wrong_path.write_text("txt", encoding="utf-8")

    check_stale_index(wrong_path)

    captured = capsys.readouterr()
    assert captured.err == ""
