import re
import pytest

from merger.lenskit.core.citation_id import make_citation_id

SHA_A = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
SHA_B = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
SHA_C = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

CIT_RE = re.compile(r"^cit_[a-f0-9]{16}$")


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------

def test_format_matches_pattern():
    result = make_citation_id(SHA_A, 0, 100, SHA_B)
    assert CIT_RE.match(result), f"Unexpected format: {result!r}"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_deterministic_same_inputs():
    a = make_citation_id(SHA_A, 0, 100, SHA_B)
    b = make_citation_id(SHA_A, 0, 100, SHA_B)
    assert a == b


# ---------------------------------------------------------------------------
# Sensitivity
# ---------------------------------------------------------------------------

def test_sensitive_to_canonical_md_sha256():
    a = make_citation_id(SHA_A, 0, 100, SHA_B)
    b = make_citation_id(SHA_C, 0, 100, SHA_B)
    assert a != b


def test_sensitive_to_start_byte():
    a = make_citation_id(SHA_A, 0, 100, SHA_B)
    b = make_citation_id(SHA_A, 1, 100, SHA_B)
    assert a != b


def test_sensitive_to_end_byte():
    a = make_citation_id(SHA_A, 0, 100, SHA_B)
    b = make_citation_id(SHA_A, 0, 101, SHA_B)
    assert a != b


def test_sensitive_to_content_sha256():
    a = make_citation_id(SHA_A, 0, 100, SHA_B)
    b = make_citation_id(SHA_A, 0, 100, SHA_C)
    assert a != b


# ---------------------------------------------------------------------------
# Invalid SHA values
# ---------------------------------------------------------------------------

def test_invalid_canonical_md_sha256_too_short():
    with pytest.raises(ValueError, match="canonical_md_sha256"):
        make_citation_id("abc", 0, 100, SHA_B)


def test_invalid_canonical_md_sha256_uppercase():
    bad = SHA_A.upper()
    with pytest.raises(ValueError, match="canonical_md_sha256"):
        make_citation_id(bad, 0, 100, SHA_B)


def test_invalid_canonical_md_sha256_not_hex():
    bad = "z" * 64
    with pytest.raises(ValueError, match="canonical_md_sha256"):
        make_citation_id(bad, 0, 100, SHA_B)


def test_invalid_content_sha256_too_short():
    with pytest.raises(ValueError, match="content_sha256"):
        make_citation_id(SHA_A, 0, 100, "abc")


def test_invalid_content_sha256_uppercase():
    bad = SHA_B.upper()
    with pytest.raises(ValueError, match="content_sha256"):
        make_citation_id(SHA_A, 0, 100, bad)


def test_invalid_content_sha256_not_hex():
    bad = "g" * 64
    with pytest.raises(ValueError, match="content_sha256"):
        make_citation_id(SHA_A, 0, 100, bad)


# ---------------------------------------------------------------------------
# Invalid start_byte / end_byte types
# ---------------------------------------------------------------------------

def test_start_byte_bool_rejected():
    with pytest.raises(TypeError, match="start_byte"):
        make_citation_id(SHA_A, True, 100, SHA_B)


def test_end_byte_bool_rejected():
    with pytest.raises(TypeError, match="end_byte"):
        make_citation_id(SHA_A, 0, True, SHA_B)


def test_start_byte_float_rejected():
    with pytest.raises(TypeError, match="start_byte"):
        make_citation_id(SHA_A, 0.0, 100, SHA_B)  # type: ignore[arg-type]


def test_end_byte_float_rejected():
    with pytest.raises(TypeError, match="end_byte"):
        make_citation_id(SHA_A, 0, 100.0, SHA_B)  # type: ignore[arg-type]


def test_start_byte_string_rejected():
    with pytest.raises(TypeError, match="start_byte"):
        make_citation_id(SHA_A, "0", 100, SHA_B)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Invalid start_byte / end_byte values
# ---------------------------------------------------------------------------

def test_start_byte_negative_rejected():
    with pytest.raises(ValueError, match="start_byte"):
        make_citation_id(SHA_A, -1, 100, SHA_B)


def test_end_byte_equal_start_rejected():
    with pytest.raises(ValueError, match="end_byte"):
        make_citation_id(SHA_A, 50, 50, SHA_B)


def test_end_byte_less_than_start_rejected():
    with pytest.raises(ValueError, match="end_byte"):
        make_citation_id(SHA_A, 100, 50, SHA_B)


# ---------------------------------------------------------------------------
# Golden vector — freezes payload prefix, field order, and 16-hex truncation
# ---------------------------------------------------------------------------

def test_known_vector_freezes_payload_contract():
    assert make_citation_id(SHA_A, 0, 100, SHA_B) == "cit_e9bf24db57165d03"


# ---------------------------------------------------------------------------
# Edge cases that should succeed
# ---------------------------------------------------------------------------

def test_start_byte_zero_is_valid():
    result = make_citation_id(SHA_A, 0, 1, SHA_B)
    assert CIT_RE.match(result)


def test_large_byte_offsets_are_valid():
    result = make_citation_id(SHA_A, 0, 10_000_000, SHA_B)
    assert CIT_RE.match(result)
