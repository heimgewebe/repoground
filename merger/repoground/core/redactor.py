import re
from typing import Tuple


class Redactor:
    """Heuristic-based secret redaction."""

    PATTERNS = [
        (
            r"(?i)(api[_-]?key|access[_-]?token|secret[_-]?key)([\s:=]+)([\"\']?)([\w-]{20,})",
            r"\1\2\3[REDACTED]",
        ),
        (
            r"(?i)(password|passwd|pwd)([\s:=]+)([\"\']?)([\w-]{6,})",
            r"\1\2\3[REDACTED]",
        ),
        (r"(AKIA[0-9A-Z]{16})", "[AWS_KEY_REDACTED]"),
        (
            r"-----BEGIN ((?:(?:RSA|EC|DSA|OPENSSH) )?PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----"
            r"[\s\S]*?"
            r"-----END \1-----",
            "[PRIVATE_KEY_BLOCK_REDACTED]",
        ),
    ]

    def redact(self, content: str) -> Tuple[str, bool]:
        """Return redacted content and whether any replacement occurred."""
        modified = False
        redacted = content

        for pattern, replacement in self.PATTERNS:
            new_content = re.sub(pattern, replacement, redacted)
            if new_content != redacted:
                modified = True
                redacted = new_content

        return redacted, modified
