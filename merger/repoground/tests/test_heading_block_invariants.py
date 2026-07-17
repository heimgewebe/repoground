import unittest
import re
from merger.repoground.core import merge

class TestHeadingBlockInvariants(unittest.TestCase):
    """
    Tests for _heading_block invariants (Option A: Separate Anchor Line + Markdown Heading).
    Checks robustness of sanitization and anchor placement.
    """

    def test_heading_structure_invariant(self):
        """
        Invariant: Output must strictly follow the sequence at the end:
        -3. <a id="..."></a>
        -2. ## Title (or Token)
        -1. Blank line
        (We do not check strict length to allow future prepended markers like nav markers)
        """
        lines = merge._heading_block(2, "my-token", "My Title")
        # Ensure we have at least 3 lines to check the invariant
        self.assertGreaterEqual(len(lines), 3)
        self.assertRegex(lines[-3], r'^<a id="[^"]+"></a>$')
        self.assertRegex(lines[-2], r'^## My Title$')
        self.assertEqual(lines[-1], "")

    def test_sanitization_invariant_safe_token(self):
        """
        Invariant: Safe tokens (alphanumeric + . _ : -) are preserved as-is.
        We check the end of the list for robustness.
        """
        token = "safe-token.123_test"
        lines = merge._heading_block(2, token)
        self.assertGreaterEqual(len(lines), 3)
        # Anchor should use token exactly
        self.assertIn(f'<a id="{token}"></a>', lines[-3])
        # Heading should use token if no title provided
        self.assertIn(f"## {token}", lines[-2])

    def test_sanitization_invariant_unsafe_token(self):
        """
        Invariant: Unsafe characters in token are sanitized for the ID.
        We do NOT assert the exact sanitized string (implementation detail),
        but we assert that the resulting ID is safe (contains only allowed chars).
        """
        unsafe_token = "unsafe/token with spaces & symbols!"
        lines = merge._heading_block(2, unsafe_token)

        # Extract the ID used
        match = re.search(r'id="([^"]+)"', lines[-3])
        self.assertTrue(match, "Anchor tag with ID not found")
        generated_id = match.group(1)

        # Invariant: ID must be safe (alphanumeric + . _ : -)
        # We align this check with the safe_token definition in the code,
        # rather than strictly requiring slug logic (a-z0-9-), to allow future flexibility.
        self.assertRegex(generated_id, r'^[A-Za-z0-9._:-]+$')

        # Invariant: unsafe chars should be gone
        self.assertNotIn("/", generated_id)
        self.assertNotIn(" ", generated_id)
        self.assertNotIn("&", generated_id)
        self.assertNotIn("!", generated_id)

    def test_title_priority_invariant(self):
        """
        Invariant: If title is provided, it is used in the Markdown heading.
        The token is still used for the anchor.
        We check the end of the list for robustness.
        """
        token = "token-123"
        title = "Display Title"
        lines = merge._heading_block(2, token, title)

        self.assertGreaterEqual(len(lines), 3)
        self.assertIn(f'<a id="{token}"></a>', lines[-3])
        self.assertIn(f"## {title}", lines[-2])
        self.assertNotIn(f"## {token}", lines[-2]) # Token should not be in heading if title exists

    def test_no_inline_html_in_heading(self):
        """
        Invariant: The Markdown heading line MUST NOT contain the anchor tag.
        We check the heading line (lines[-2]) for robustness.
        """
        token = "token"
        title = "Title"
        lines = merge._heading_block(2, token, title)
        self.assertGreaterEqual(len(lines), 3)
        heading_line = lines[-2]

        self.assertNotIn("<a", heading_line)
        self.assertNotIn("</a>", heading_line)
        self.assertNotIn("id=", heading_line)

if __name__ == '__main__':
    unittest.main()
