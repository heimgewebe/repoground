import unittest
from unittest.mock import MagicMock, patch
import json
import urllib.request
import urllib.error

"""
NOTE:
These are mock-based client logic tests.
They do NOT start a real server and are not end-to-end integration tests.
"""

class TestServiceSecurity(unittest.TestCase):

    @patch('urllib.request.urlopen')
    def test_path_traversal_hub(self, mock_urlopen):
        # Mocking a 403 Forbidden response which raises HTTPError in urllib
        error = urllib.error.HTTPError(
            url="http://mock/api/jobs",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=MagicMock()
        )
        error.read = MagicMock(return_value=b'{"detail": "Access denied"}')
        mock_urlopen.side_effect = error

        payload = {"hub": "/etc", "repos": None}

        # Logic to test
        try:
            req = urllib.request.Request("http://mock/api/jobs", method="POST")
            req.add_header("Content-Type", "application/json")
            req.data = json.dumps(payload).encode("utf-8")
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 403)
            return

        self.fail("Should have raised HTTPError 403")

    @patch('urllib.request.urlopen')
    def test_path_traversal_repo(self, mock_urlopen):
        # Mocking a 400 Bad Request
        error = urllib.error.HTTPError(
            url="http://mock/api/jobs",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=MagicMock()
        )
        error.read = MagicMock(return_value=b'{"detail": "Invalid repo name"}')
        mock_urlopen.side_effect = error

        payload = {"repos": ["../etc"], "level": "max"}

        try:
            req = urllib.request.Request("http://mock/api/jobs", method="POST")
            req.add_header("Content-Type", "application/json")
            req.data = json.dumps(payload).encode("utf-8")
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
            return

        self.fail("Should have raised HTTPError 400")

if __name__ == "__main__":
    unittest.main()
