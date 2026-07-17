import unittest
from merger.repoground.frontends.pythonista.build_utils import normalize_path, normalize_repo_id
from merger.repoground.frontends.pythonista.build_helpers import resolve_pool_include_paths, deserialize_prescan_pool, _sanitize_list

class TestSanitizeListInternal(unittest.TestCase):
    def test_sanitize_list_mixed(self):
        # Mixed types
        self.assertEqual(_sanitize_list(["a", 1, None, "b"]), (["a", "b"], True))
        # Empty
        self.assertEqual(_sanitize_list([]), ([], False))
        # All valid
        self.assertEqual(_sanitize_list(["a", "b"]), (["a", "b"], False))
        # Unicode
        self.assertEqual(_sanitize_list(["ü"]), (["ü"], False))


class TestPrescanPool(unittest.TestCase):

    def test_normalization(self):
        self.assertEqual(normalize_path("./foo/bar/"), "foo/bar")
        self.assertEqual(normalize_path("/"), "/")
        self.assertEqual(normalize_path(""), ".")
        self.assertEqual(normalize_repo_id("./Hub/MyRepo/"), "myrepo")
        self.assertEqual(normalize_repo_id("MyRepo"), "myrepo")

    def test_resolve_pool_include_paths(self):
        # ALL
        self.assertIsNone(resolve_pool_include_paths(None))
        self.assertIsNone(resolve_pool_include_paths({}))
        self.assertIsNone(resolve_pool_include_paths({"compressed": None}))

        # BLOCK
        self.assertEqual(resolve_pool_include_paths({"compressed": []}), [])

        # PARTIAL
        self.assertEqual(resolve_pool_include_paths({"compressed": ["a", "b"]}), ["a", "b"])

        # LEGACY LIST
        self.assertEqual(resolve_pool_include_paths(["a", "b"]), ["a", "b"])
        self.assertEqual(resolve_pool_include_paths([]), [])

    def test_deserialize_sanitization(self):
        # Non-string filtering
        data = {
            "repo1": {
                "raw": ["a", 1, None, "b"],
                "compressed": ["a", "b"]
            }
        }
        res = deserialize_prescan_pool(data)
        self.assertEqual(res["repo1"]["raw"], ["a", "b"])

    def test_deserialize_fallback(self):
        # Case: Compressed corrupted (empty) but Raw has data and sanitization happened

        # 1. Fallback triggered
        data_bad = {
            "repo1": {
                "raw": ["a"],
                "compressed": [123] # Will be dropped -> empty list + dropped flag
            }
        }
        res = deserialize_prescan_pool(data_bad)
        # fallback to raw
        self.assertEqual(res["repo1"]["compressed"], ["a"])

        # 2. No Fallback if no drop (Explicit Block)
        data_block = {
            "repo1": {
                "raw": ["a"],
                "compressed": [] # Empty but valid
            }
        }
        res2 = deserialize_prescan_pool(data_block)
        # Remains Block
        self.assertEqual(res2["repo1"]["compressed"], [])

        # 3. No Fallback if raw empty
        data_empty = {
            "repo1": {
                "raw": [],
                "compressed": [123]
            }
        }
        res3 = deserialize_prescan_pool(data_empty)
        # Empty
        self.assertEqual(res3["repo1"]["compressed"], [])

    def test_structured_compressed_none_semantics(self):
        # Case: compressed explicitly None in structured input -> Should remain None (ALL)
        data = {
            "repo1": {
                "raw": ["a"],
                "compressed": None
            }
        }
        res = deserialize_prescan_pool(data)
        self.assertIsNone(res["repo1"]["compressed"])
        self.assertEqual(res["repo1"]["raw"], ["a"])

        # Case: compressed explicitly [] in structured input -> Should remain [] (BLOCK)
        data_block = {
            "repo2": {
                "raw": ["a"],
                "compressed": []
            }
        }
        res2 = deserialize_prescan_pool(data_block)
        self.assertEqual(res2["repo2"]["compressed"], [])

    def test_legacy_format(self):
        data = {
            "repo1": ["a", "b"]
        }
        res = deserialize_prescan_pool(data)
        self.assertEqual(res["repo1"]["raw"], ["a", "b"])
        self.assertEqual(res["repo1"]["compressed"], ["a", "b"])

    def test_legacy_none(self):
        data = {
            "repo1": None
        }
        res = deserialize_prescan_pool(data)
        self.assertIsNone(res["repo1"]["raw"])
        self.assertIsNone(res["repo1"]["compressed"])

    def test_key_normalization(self):
        data = {
            "Hub/MyRepo/": ["a"]
        }
        res = deserialize_prescan_pool(data)
        self.assertIn("myrepo", res)
        self.assertNotIn("Hub/MyRepo/", res)
        self.assertEqual(res["myrepo"]["raw"], ["a"])

    def test_empty_string_policy_legacy_list(self):
        """
        Policy (Legacy): Empty strings in prescan pool legacy lists are treated as the repository root ('.').
        """
        data_legacy = {
            "repo1": ["a", "", "b"]
        }
        res_legacy = deserialize_prescan_pool(data_legacy)
        self.assertEqual(res_legacy["repo1"]["raw"], ["a", ".", "b"])
        self.assertEqual(res_legacy["repo1"]["compressed"], ["a", ".", "b"])

    def test_empty_string_policy_structured_format(self):
        """
        Policy (Structured): Empty strings in prescan pool structured fields are treated as the repository root ('.').
        """
        data_structured = {
            "repo_structured": {
                "raw": ["a", "", "b"],
                "compressed": ["x", "", "y"]
            }
        }
        res_structured = deserialize_prescan_pool(data_structured)
        self.assertEqual(res_structured["repo_structured"]["raw"], ["a", ".", "b"])
        self.assertEqual(res_structured["repo_structured"]["compressed"], ["x", ".", "y"])

if __name__ == '__main__':
    unittest.main()
