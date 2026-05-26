import unittest
import sys
from pathlib import Path

PYTHONISTA_FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontends" / "pythonista"
if str(PYTHONISTA_FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHONISTA_FRONTEND_DIR))

from merger.lenskit.frontends.pythonista.repolens_utils import normalize_path, normalize_repo_id
from merger.lenskit.frontends.pythonista.repolens_helpers import resolve_pool_include_paths, deserialize_prescan_pool, _sanitize_list
from merger.lenskit.frontends.pythonista import repolens

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


class TestRepoLensResetAfterSuccess(unittest.TestCase):
    def test_reset_merge_form_to_defaults_after_success(self):
        class DummyField:
            def __init__(self, text=""):
                self.text = text

        class DummySwitch:
            def __init__(self, value=False):
                self.value = value

        class DummySegment:
            def __init__(self, segments, selected_index):
                self.segments = segments
                self.selected_index = selected_index

        class DummyTable:
            def __init__(self):
                self.selected_rows = [(0, 0), (0, 1)]
                self.reloaded = False

            def reload_data(self):
                self.reloaded = True

        class DummyUI:
            def __init__(self):
                self.saved_prescan_selections = {
                    "repoa": {"raw": ["a.py"], "compressed": ["a.py"]}
                }
                self.ignored_repos = {"keep-me"}

                self.ext_field = DummyField(".py")
                self.path_field = DummyField("src/")
                self.max_field = DummyField("1234")
                self.split_field = DummyField("7")

                self.seg_detail = DummySegment(["overview", "summary", "dev", "max"], 0)
                self.seg_mode = DummySegment(["combined", "per repo"], 1)
                self.seg_meta = DummySegment(["auto", "min", "standard", "full"], 3)

                self.plan_only_switch = DummySwitch(True)
                self.code_only_switch = DummySwitch(True)
                self.tv = DummyTable()

                extras_cfg, _ = repolens.ExtrasConfig.from_csv("health,heatmap")
                self.extras_config = extras_cfg

                self.saved_state = None
                self.repo_info_updated = False
                self.profile_hint = DummyField("stale")

            def on_profile_changed(self, _sender):
                idx = self.seg_detail.selected_index
                seg = self.seg_detail.segments[idx]
                self.profile_hint.text = repolens.PROFILE_DESCRIPTIONS.get(seg, "")

            def _update_repo_info(self):
                self.repo_info_updated = True

            def save_last_state(self):
                selected_repos = []
                for section, row in (self.tv.selected_rows or []):
                    if section == 0:
                        selected_repos.append(f"repo-{row}")
                self.saved_state = {
                    "prescan_pool": self.saved_prescan_selections,
                    "selected_repos": selected_repos,
                    "ignored_repos": sorted(self.ignored_repos),
                }

        dummy = DummyUI()
        repolens.MergerUI.reset_merge_form_to_defaults_after_success(dummy)

        self.assertEqual(dummy.saved_prescan_selections, {})
        self.assertEqual(dummy.tv.selected_rows, [])
        self.assertTrue(dummy.tv.reloaded)

        self.assertEqual(dummy.ext_field.text, "")
        self.assertEqual(dummy.path_field.text, "")
        self.assertEqual(dummy.max_field.text, "")
        self.assertEqual(dummy.split_field.text, "25")

        self.assertEqual(dummy.seg_detail.selected_index, 3)  # max
        self.assertEqual(dummy.seg_mode.selected_index, 0)  # gesamt/combined
        self.assertEqual(dummy.seg_meta.selected_index, 0)  # auto
        self.assertFalse(dummy.plan_only_switch.value)
        self.assertFalse(dummy.code_only_switch.value)
        self.assertEqual(
            dummy.profile_hint.text,
            repolens.PROFILE_DESCRIPTIONS["max"],
        )

        self.assertTrue(dummy.extras_config.augment_sidecar)
        self.assertTrue(dummy.extras_config.json_sidecar)
        self.assertFalse(dummy.extras_config.health)
        self.assertFalse(dummy.extras_config.heatmap)

        self.assertTrue(dummy.repo_info_updated)
        self.assertEqual(dummy.saved_state["prescan_pool"], {})
        self.assertEqual(dummy.saved_state["selected_repos"], [])
        self.assertEqual(dummy.saved_state["ignored_repos"], ["keep-me"])

if __name__ == '__main__':
    unittest.main()
