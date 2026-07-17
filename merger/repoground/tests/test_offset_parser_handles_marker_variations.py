from pathlib import Path
from merger.repoground.core.merge import extract_file_offsets

def test_offset_parser_handles_marker_variations(tmp_path: Path):
    # Test 1: Quoted type + Quoted id (New Standard)
    p1 = tmp_path / "f1.md"
    p1.write_bytes(
        (
            "Some text\n"
            "<!-- zone:begin type=\"code\" lang=\"python\" id=\"FILE:test1\" -->\n"
            "\n"
            "```python\n"
            "def x(): pass\n"
            "```\n"
            "<!-- zone:end type=\"code\" id=\"FILE:test1\" -->\n"
        ).encode("utf-8")
    )

    # Test 2: Unquoted type + Quoted id (Legacy Mixed)
    p2 = tmp_path / "f2.md"
    p2.write_bytes(
        (
            "<!-- zone:begin type=code id=\"FILE:test2\" -->\n"
            "```\n"
            "x=1\n"
            "```\n"
        ).encode("utf-8")
    )

    # Test 3: CRLF newlines + Unquoted type + Unquoted id (Legacy CRLF)
    p3 = tmp_path / "f3.md"
    p3.write_bytes(
        b"<!-- zone:begin type=code id=FILE:test3 -->\r\n"
        b"\r\n"
        b"```python\r\n"
        b"x=1\r\n"
        b"```\r\n"
    )

    # Test 4: Quoted type + Unquoted ID
    p4 = tmp_path / "f4.md"
    p4.write_bytes(
        (
            "<!-- zone:begin type=\"code\" id=FILE:test4 -->\n"
            "```\n"
            "x=4\n"
            "```\n"
        ).encode("utf-8")
    )

    # Test 5: Quoted type + Mixed attributes (lang before ID)
    p5 = tmp_path / "f5.md"
    p5.write_bytes(
        (
            "<!-- zone:begin type=\"code\" lang=\"python\" id=\"FILE:test5\" -->\n"
            "```python\n"
            "x=5\n"
            "```\n"
        ).encode("utf-8")
    )

    # Test 6: Malformed zone marker (no code fence before end)
    p6 = tmp_path / "f6.md"
    p6.write_bytes(
        (
            "<!-- zone:begin type=\"code\" id=\"FILE:test6\" -->\n"
            "This is just text without code fences\n"
            "<!-- zone:end type=\"code\" id=\"FILE:test6\" -->\n"
            "<!-- zone:begin type=\"code\" id=\"FILE:test7\" -->\n"
            "```\n"
            "valid\n"
            "```\n"
        ).encode("utf-8")
    )

    offsets = extract_file_offsets([p1, p2, p3, p4, p5, p6], debug=False)

    # p1 check
    assert "FILE:test1" in offsets
    assert offsets["FILE:test1"][0] == "f1.md"
    # Offset points to end of ```python\n`
    with open(p1, "rb") as f:
        content = f.read()
        idx = content.find(b"```python\n")
        assert offsets["FILE:test1"][1] == idx + len(b"```python\n")

    # p2 check
    assert "FILE:test2" in offsets
    assert offsets["FILE:test2"][0] == "f2.md"

    # p3 check (CRLF)
    assert "FILE:test3" in offsets
    assert offsets["FILE:test3"][0] == "f3.md"
    with open(p3, "rb") as f:
        content = f.read()
        idx = content.find(b"```python\r\n")
        assert offsets["FILE:test3"][1] == idx + len(b"```python\r\n")

    # p4 check (Quoted type + Unquoted ID)
    assert "FILE:test4" in offsets
    assert offsets["FILE:test4"][0] == "f4.md"

    # p5 check (Mixed attributes)
    assert "FILE:test5" in offsets
    assert offsets["FILE:test5"][0] == "f5.md"

    # p6 check (Malformed marker correctly ignored for FILE:test6, works for FILE:test7)
    assert "FILE:test6" not in offsets
    assert "FILE:test7" in offsets
    assert offsets["FILE:test7"][0] == "f6.md"
