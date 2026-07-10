import pytest

from merger.lenskit.core.redactor import Redactor


@pytest.mark.parametrize(
    "label",
    [
        "PRIVATE KEY",
        "RSA PRIVATE KEY",
        "EC PRIVATE KEY",
        "DSA PRIVATE KEY",
        "OPENSSH PRIVATE KEY",
        "PGP PRIVATE KEY BLOCK",
    ],
)
def test_redactor_removes_documented_private_key_blocks(label):
    payload = f"-----BEGIN {label}-----\nsynthetic-test-material\n-----END {label}-----"

    redacted, modified = Redactor().redact(payload)

    assert modified is True
    assert "synthetic-test-material" not in redacted
    assert redacted == "[PRIVATE_KEY_BLOCK_REDACTED]"


def test_redactor_does_not_consume_mismatched_private_key_boundaries():
    payload = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "synthetic-test-material\n"
        "-----END EC PRIVATE KEY-----"
    )

    redacted, modified = Redactor().redact(payload)

    assert modified is False
    assert redacted == payload
