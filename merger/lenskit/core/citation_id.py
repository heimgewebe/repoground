import hashlib
import re

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def make_citation_id(
    canonical_md_sha256: str,
    start_byte: int,
    end_byte: int,
    content_sha256: str,
) -> str:
    """Derive a stable citation ID from a canonical range's identifying fields."""
    if not isinstance(canonical_md_sha256, str) or not _SHA256_RE.fullmatch(canonical_md_sha256):
        raise ValueError(
            "canonical_md_sha256 must be a 64-character lowercase hex string"
        )
    if not isinstance(content_sha256, str) or not _SHA256_RE.fullmatch(content_sha256):
        raise ValueError(
            "content_sha256 must be a 64-character lowercase hex string"
        )
    if isinstance(start_byte, bool) or not isinstance(start_byte, int):
        raise TypeError("start_byte must be an int, not bool or other type")
    if isinstance(end_byte, bool) or not isinstance(end_byte, int):
        raise TypeError("end_byte must be an int, not bool or other type")
    if start_byte < 0:
        raise ValueError("start_byte must be >= 0")
    if end_byte <= start_byte:
        raise ValueError("end_byte must be > start_byte")

    payload = (
        f"lenskit.citation-map.v1:"
        f"{canonical_md_sha256}:{start_byte}:{end_byte}:{content_sha256}"
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"cit_{digest}"
