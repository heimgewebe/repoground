"""Semantic negative tests for T009 report-contract-hardening.

These tests verify fail-closed behavior, boundary conditions, and
adversarial inputs for the hardened report contract components.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

from merger.repoground.core.redactor import Redactor
from merger.repoground.core.merge import (
    _html_attr_escape,
    _normalize_ext_filter,
    _stable_file_id,
)


# ---------------------------------------------------------------------------
# Redactor: horizontal whitespace boundary
# ---------------------------------------------------------------------------

class TestRedactorWhitespaceBoundary:
    """The redactor must only match horizontal whitespace ([ \\t]) around
    patterns, NOT vertical/newline whitespace."""

    def test_tab_adjacent_to_key_redacts(self):
        redactor = Redactor()
        text = "-----BEGIN RSA PRIVATE KEY-----\tsynthetic\t-----END RSA PRIVATE KEY-----"
        redacted, modified = redactor.redact(text)
        assert modified is True
        assert "synthetic" not in redacted

    def test_horizontal_whitespace_api_key_redacts(self):
        redactor = Redactor()
        text = 'api_key = "ABCDEFGHIJKLMNOPQRST1234"'
        redacted, modified = redactor.redact(text)
        assert modified is True
        assert "ABCDEFGHIJKLMNOPQRST1234" not in redacted

    def test_newline_does_not_act_as_api_key_separator(self):
        redactor = Redactor()
        # api_key followed by newline then value should NOT be matched
        text = "api_key\nABCDEFGHIJKLMNOPQRST1234"
        redacted, modified = redactor.redact(text)
        assert modified is False


# ---------------------------------------------------------------------------
# Redactor: JWT token pattern
# ---------------------------------------------------------------------------

class TestRedactorJWT:
    def test_ey_prefix_jwt_is_redacted(self):
        redactor = Redactor()
        token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123signature"
        redacted, modified = redactor.redact(token)
        assert modified is True
        assert token not in redacted

    def test_short_b64_not_redacted_as_jwt(self):
        redactor = Redactor()
        # Only 2 parts (no third dot-separated segment)
        text = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        redacted, modified = redactor.redact(text)
        assert modified is False


# ---------------------------------------------------------------------------
# Redactor: Base64url blob pattern
# ---------------------------------------------------------------------------

class TestRedactorBase64Blob:
    def test_long_base64url_blob_not_false_positive(self):
        """Standalone Base64url blobs must NOT be redacted (no false positives).
        Only structured patterns (key=, password=) and JWT tokens are redacted."""
        redactor = Redactor()
        blob = "QUFBQkJCQ0NEREVGRkdHSEhJSktMTU1OT1PPUFRSVFVWV1hZWV9fX19fX19fXw"
        redacted, modified = redactor.redact(blob)
        assert modified is False
        assert redacted == blob

    def test_long_base64url_in_secret_key_assignment_redacted(self):
        """Base64url value after secret_key= IS redacted via structured pattern."""
        redactor = Redactor()
        text = "secret_key = QUFBQkJCQ0NEREVGRkdHSEhJSktMTU1OT1PPUFRSVFVWV1hZWV9fX19fX19fXw"
        redacted, modified = redactor.redact(text)
        assert modified is True
        assert "QUFBQkJCQ0NEREVGRkdHSEhJSktMTU1OT1PPUFRSVFVWV1hZWV9fX19fX19fXw" not in redacted


# ---------------------------------------------------------------------------
# _html_attr_escape: injection resistance
# ---------------------------------------------------------------------------

class TestHtmlAttrEscape:
    def test_double_quote_escaped(self):
        assert '&quot;' in _html_attr_escape('a"b')

    def test_angle_bracket_escaped(self):
        escaped = _html_attr_escape('a<b>c')
        assert '<' not in escaped
        assert '>' not in escaped

    def test_dash_injection_prevented(self):
        escaped = _html_attr_escape('-->injected')
        assert '-->' not in escaped

    def test_ampersand_escaped(self):
        assert '&amp;' in _html_attr_escape('a&b')

    def test_single_quote_escaped(self):
        assert '&#39;' in _html_attr_escape("a'b")

    def test_not_idempotent_by_design(self):
        # HTML escaping is not idempotent: double-escaping produces &amp;amp;
        text = 'a&b"c'
        first = _html_attr_escape(text)
        second = _html_attr_escape(first)
        assert first != second
        assert "&amp;amp;" in second


# ---------------------------------------------------------------------------
# _normalize_ext_filter
# ---------------------------------------------------------------------------

class TestNormalizeExtFilter:
    def test_empty_returns_none(self):
        assert _normalize_ext_filter(None) is None
        assert _normalize_ext_filter([]) is None

    def test_deduplication(self):
        result = _normalize_ext_filter(["py", "py", "PY"])
        assert result == [".py"]

    def test_dot_prefix_added(self):
        result = _normalize_ext_filter(["py", "js"])
        assert result == [".js", ".py"]

    def test_sorted_output(self):
        result = _normalize_ext_filter(["md", "a", "z"])
        assert result == [".a", ".md", ".z"]


# ---------------------------------------------------------------------------
# _stable_file_id: SHA-256 path anchors
# ---------------------------------------------------------------------------

def _make_file_info(path: str, root: str = "test-repo") -> MagicMock:
    fi = MagicMock()
    fi.rel_path = Path(path)
    fi.root_label = root
    return fi


class TestStableFileId:
    def test_deterministic(self):
        a = _stable_file_id(_make_file_info("src/foo.py"))
        b = _stable_file_id(_make_file_info("src/foo.py"))
        assert a == b

    def test_different_paths_different_ids(self):
        a = _stable_file_id(_make_file_info("src/foo.py"))
        b = _stable_file_id(_make_file_info("src/bar.py"))
        assert a != b

    def test_prefix_format(self):
        fid = _stable_file_id(_make_file_info("test"))
        assert fid.startswith("FILE:f_")
        assert len(fid) == len("FILE:f_") + 24

    def test_uses_sha256_with_nul_separator(self):
        fi = _make_file_info("test")
        repo = fi.root_label
        path = str(fi.rel_path)
        expected_suffix = hashlib.sha256(f"{repo}\x00{path}".encode()).hexdigest()[:24]
        assert _stable_file_id(fi) == f"FILE:f_{expected_suffix}"

    def test_different_repos_different_ids(self):
        a = _stable_file_id(_make_file_info("src/foo.py", root="repo-a"))
        b = _stable_file_id(_make_file_info("src/foo.py", root="repo-b"))
        assert a != b
