import re
from typing import Tuple


# JWT pattern: three dot-separated Base64url segments (header.payload.signature)
_JWT_PATTERN = re.compile(
    r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
)

# Quoted API key assignments: handles values with ., /, +, = inside quotes
_API_KEY_QUOTED_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|secret[_-]?key)"
    r"([ \t:=]+)"
    r"(['\"])"
    r"([^'\"]{20,})"
    r"\3"
)

# Unquoted API key assignments: broad value class includes . / + =
_API_KEY_UNQUOTED_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|secret[_-]?key)"
    r"([ \t:=]+)"
    r"(['\"]?)"
    r"([\w./+=-]{20,})"
)

# Quoted password assignments
_PASSWORD_QUOTED_PATTERN = re.compile(
    r"(?i)(password|passwd|pwd)"
    r"([ \t:=]+)"
    r"(['\"])"
    r"([^'\"]{6,})"
    r"\3"
)

# Unquoted password assignments
_PASSWORD_UNQUOTED_PATTERN = re.compile(
    r"(?i)(password|passwd|pwd)"
    r"([ \t:=]+)"
    r"(['\"]?)"
    r"([\w./+=-]{6,})"
)

_AWS_KEY_PATTERN = re.compile(r"(AKIA[0-9A-Z]{16})")

_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN ((?:(?:RSA|EC|DSA|OPENSSH) )?PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----"
    r"[\s\S]*?"
    r"-----END \1-----"
)


class Redactor:
    """Heuristic-based secret redaction.

    Patterns are precompiled for performance.  Quoted patterns preserve the
    closing quote to avoid breaking syntax.  Unquoted patterns use a broad
    value class that includes '.', '/', '+', '=' which are common in secrets.
    JWTs are detected and replaced completely to prevent partial redaction
    leaking a recognizable prefix or suffix.

    NOTE: The broad generic Base64url pattern (>=40 chars) has been removed
    because it produced false positives on normal identifiers, UUIDs, hashes,
    and other non-secret content.  Only structured patterns (key/password
    assignments, AWS keys, PEM blocks) and JWT tokens are redacted.
    """

    PATTERNS: list[Tuple[re.Pattern[str], str]] = [
        (_API_KEY_QUOTED_PATTERN, r"\1\2\3[REDACTED]\3"),
        (_API_KEY_UNQUOTED_PATTERN, r"\1\2\3[REDACTED]"),
        (_PASSWORD_QUOTED_PATTERN, r"\1\2\3[REDACTED]\3"),
        (_PASSWORD_UNQUOTED_PATTERN, r"\1\2\3[REDACTED]"),
        (_AWS_KEY_PATTERN, "[AWS_KEY_REDACTED]"),
        (_PRIVATE_KEY_PATTERN, "[PRIVATE_KEY_BLOCK_REDACTED]"),
    ]

    def redact(self, content: str) -> Tuple[str, bool]:
        """Return redacted content and whether any replacement occurred."""
        modified = False
        redacted = content

        # Pass 1: structured key/password/PEM patterns
        for pattern, replacement in self.PATTERNS:
            new_content = pattern.sub(replacement, redacted)
            if new_content != redacted:
                modified = True
                redacted = new_content

        # Pass 2: JWT tokens (structural ey...ey... signature)
        new_content = _JWT_PATTERN.sub("[REDACTED]", redacted)
        if new_content != redacted:
            modified = True
            redacted = new_content

        return redacted, modified
