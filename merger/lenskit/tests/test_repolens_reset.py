"""
Focused unit test for MergerUI.reset_merge_form_to_defaults_after_success.

Verifies that after a successful merge the UI resets to defaults while
preserving the ignore list. Uses duck-typing so no Pythonista runtime is
needed.
"""

import json
import tempfile
import unittest
from pathlib import Path

from merger.lenskit.frontends.pythonista.repolens import (
    MergerUI,
    DEFAULT_EXTRAS,
    DEFAULT_LEVEL,
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_META_DENSITY,
    DEFAULT_MODE,
    DEFAULT_SPLIT_SIZE,
    parse_human_size,
)
from merger.lenskit.core.merge import ExtrasConfig


# ---------------------------------------------------------------------------
# Minimal mock types
# ---------------------------------------------------------------------------

class _TV:
    def __init__(self):
        self.selected_rows = [(0, 0), (0, 1)]
        self.reload_called = False

    def reload_data(self):
        self.reload_called = True


class _Field:
    def __init__(self, text="", value=False):
        self.text = text
        self.value = value


class _Seg:
    def __init__(self, segments, selected_index=0):
        self.segments = list(segments)
        self.selected_index = selected_index


# ---------------------------------------------------------------------------
# DummyUI – duck-typed stand-in for MergerUI
# ---------------------------------------------------------------------------

class _DummyUI:
    """
    Provides all attributes and helper methods that
    reset_merge_form_to_defaults_after_success touches, plus the full
    save_last_state / _get_selected_repos / _serialize_prescan_pool
    implementations so that the saved JSON can be inspected.
    """

    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path
        self.repos = ["repo-a", "repo-b", "keep-me"]

        # Non-default merge state that the reset should clear
        self.saved_prescan_selections = {
            "repo-a": {"raw": ["a.py"], "compressed": ["a.py"]},
        }
        self.ignored_repos = {"keep-me"}

        self.tv = _TV()

        self.ext_field = _Field(text=".py,.rs")
        self.path_field = _Field(text="src/")
        self.max_field = _Field(text="999")
        self.split_field = _Field(text="42")

        segs_detail = ["overview", "summary", "dev", "max"]
        self.seg_detail = _Seg(segs_detail, segs_detail.index("dev"))  # dev != DEFAULT_LEVEL (max)

        self.seg_mode = _Seg(["combined", "per repo"], 1)  # per-repo != default combined
        self.seg_meta = _Seg(["auto", "min", "standard", "full"], 2)  # standard != default auto

        self.plan_only_switch = _Field(value=True)
        self.code_only_switch = _Field(value=True)

        # All extras on (non-default for most flags)
        self.extras_config, _ = ExtrasConfig.from_csv(
            "health,organism_index,fleet_panorama,delta_reports,augment_sidecar,heatmap,json_sidecar"
        )

        self._on_profile_changed_calls: list = []
        self._update_repo_info_called = False

    # --- Methods called by reset_merge_form_to_defaults_after_success ---

    def on_profile_changed(self, sender) -> None:
        self._on_profile_changed_calls.append(sender)

    def _update_repo_info(self) -> None:
        self._update_repo_info_called = True

    def _run_merge_form_reset_after_success_safe(self) -> None:
        """Safely reset form after success, with error handling and logging."""
        MergerUI.reset_merge_form_to_defaults_after_success(self)

    # --- Methods called by save_last_state ---

    def _get_selected_repos(self, explicit_only: bool = False):
        rows = self.tv.selected_rows or []
        if not rows:
            return [] if explicit_only else list(self.repos)
        names = []
        for section, row in rows:
            if 0 <= row < len(self.repos):
                names.append(self.repos[row])
        return names

    def _serialize_prescan_pool(self):
        out = {}
        for repo, sel in self.saved_prescan_selections.items():
            if isinstance(sel, dict):
                out[repo] = {"raw": sel.get("raw"), "compressed": sel.get("compressed")}
        return out

    def save_last_state(self, ignore_only: bool = False) -> None:
        data: dict = {}
        if self._state_path.exists():
            try:
                existing = json.loads(self._state_path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    data.update(existing)
            except (OSError, json.JSONDecodeError):
                # Ignore unreadable/invalid persisted state and continue with defaults.
                pass

        data["ignored_repos"] = sorted(self.ignored_repos)

        if not ignore_only:
            segs = getattr(self.seg_detail, "segments", [])
            idx = getattr(self.seg_detail, "selected_index", 0)
            if 0 <= idx < len(segs):
                data["detail_profile"] = segs[idx]

            data.update({
                "ext_filter": self.ext_field.text or "",
                "path_filter": self.path_field.text or "",
                "max_bytes": self.max_field.text or "",
                "split_mb": self.split_field.text or "",
                "meta_density_index": self.seg_meta.selected_index,
                "plan_only": bool(self.plan_only_switch.value),
                "code_only": bool(self.code_only_switch.value),
                "selected_repos": self._get_selected_repos(explicit_only=True),
                "extras": {
                    "health": self.extras_config.health,
                    "organism_index": self.extras_config.organism_index,
                    "fleet_panorama": self.extras_config.fleet_panorama,
                    "delta_reports": self.extras_config.delta_reports,
                    "augment_sidecar": self.extras_config.augment_sidecar,
                    "heatmap": self.extras_config.heatmap,
                    "json_sidecar": self.extras_config.json_sidecar,
                },
                "prescan_pool": self._serialize_prescan_pool(),
            })

        self._state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers for expected split-field value (mirrors reset helper logic)
# ---------------------------------------------------------------------------

def _expected_split_text() -> str:
    raw = str(DEFAULT_SPLIT_SIZE).strip()
    if not raw or raw == "0":
        return ""
    if raw.isdigit():
        return raw
    try:
        mb = int(round(parse_human_size(raw) / (1024 * 1024)))
        return str(mb) if mb > 0 else ""
    except Exception:
        return raw


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestResetMergeFormAfterSuccess(unittest.TestCase):

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        state_file = Path(self._tmpdir.name) / ".repoLens-state.json"
        self.dummy = _DummyUI(state_file)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _reset(self) -> None:
        MergerUI.reset_merge_form_to_defaults_after_success(self.dummy)

    def _saved(self) -> dict:
        return json.loads(self.dummy._state_path.read_text(encoding="utf-8"))

    # --- In-memory state ---

    def test_prescan_pool_cleared(self) -> None:
        self._reset()
        self.assertEqual(self.dummy.saved_prescan_selections, {})

    def test_tv_selected_rows_cleared(self) -> None:
        self._reset()
        self.assertEqual(self.dummy.tv.selected_rows, [])

    def test_tv_reload_data_called(self) -> None:
        self._reset()
        self.assertTrue(self.dummy.tv.reload_called)

    def test_text_fields_cleared(self) -> None:
        self._reset()
        self.assertEqual(self.dummy.ext_field.text, "")
        self.assertEqual(self.dummy.path_field.text, "")

    def test_max_field_reset_to_default(self) -> None:
        self._reset()
        expected = "" if DEFAULT_MAX_FILE_BYTES <= 0 else str(DEFAULT_MAX_FILE_BYTES)
        self.assertEqual(self.dummy.max_field.text, expected)

    def test_split_field_reset_to_default(self) -> None:
        self._reset()
        self.assertEqual(self.dummy.split_field.text, _expected_split_text())

    def test_profile_segment_reset_to_default_level(self) -> None:
        self._reset()
        expected_idx = self.dummy.seg_detail.segments.index(DEFAULT_LEVEL)
        self.assertEqual(self.dummy.seg_detail.selected_index, expected_idx)

    def test_on_profile_changed_called_with_none(self) -> None:
        self._reset()
        self.assertGreaterEqual(len(self.dummy._on_profile_changed_calls), 1)
        self.assertIsNone(self.dummy._on_profile_changed_calls[-1])

    def test_mode_segment_reset_to_default(self) -> None:
        self._reset()
        expected = 1 if DEFAULT_MODE == "pro-repo" else 0
        self.assertEqual(self.dummy.seg_mode.selected_index, expected)

    def test_meta_segment_reset_to_default(self) -> None:
        self._reset()
        expected_idx = self.dummy.seg_meta.segments.index(DEFAULT_META_DENSITY)
        self.assertEqual(self.dummy.seg_meta.selected_index, expected_idx)

    def test_switches_reset_to_false(self) -> None:
        self._reset()
        self.assertFalse(self.dummy.plan_only_switch.value)
        self.assertFalse(self.dummy.code_only_switch.value)

    def test_extras_reset_to_defaults(self) -> None:
        self._reset()
        defaults, _ = ExtrasConfig.from_csv(DEFAULT_EXTRAS)
        self.assertEqual(self.dummy.extras_config.health, defaults.health)
        self.assertEqual(self.dummy.extras_config.json_sidecar, defaults.json_sidecar)
        self.assertEqual(self.dummy.extras_config.augment_sidecar, defaults.augment_sidecar)
        self.assertEqual(self.dummy.extras_config.organism_index, defaults.organism_index)

    def test_update_repo_info_called(self) -> None:
        self._reset()
        self.assertTrue(self.dummy._update_repo_info_called)

    # --- Persisted state ---

    def test_saved_selected_repos_empty(self) -> None:
        self._reset()
        self.assertEqual(self._saved()["selected_repos"], [])

    def test_saved_prescan_pool_empty(self) -> None:
        self._reset()
        self.assertEqual(self._saved()["prescan_pool"], {})

    def test_saved_ignored_repos_preserved(self) -> None:
        self._reset()
        self.assertEqual(self._saved()["ignored_repos"], ["keep-me"])

    # --- In-place clear verification ---

    def test_prescan_pool_cleared_in_place(self) -> None:
        """Verify that pool is cleared in-place, not reassigned."""
        old_pool = self.dummy.saved_prescan_selections
        self._reset()
        # After reset, the same object should exist, but be empty
        self.assertIs(self.dummy.saved_prescan_selections, old_pool)
        self.assertEqual(old_pool, {})

    # --- Scheduler method tests ---

    def test_schedule_merge_form_reset_after_success_fallback(self) -> None:
        """Test scheduler fallback when ui.delay is not available."""
        import merger.lenskit.frontends.pythonista.repolens as repolens_module
        
        # Simulate no ui.delay by patching the module's ui
        original_ui = repolens_module.ui
        repolens_module.ui = None
        try:
            # Reset state first
            self.dummy.saved_prescan_selections = {
                "repo-a": {"raw": ["a.py"], "compressed": ["a.py"]},
            }
            self.dummy.tv.selected_rows = [(0, 0)]
            self.dummy._update_repo_info_called = False

            # Call scheduler (should fallback to direct call)
            MergerUI.schedule_merge_form_reset_after_success(self.dummy)

            # Verify reset happened
            self.assertEqual(self.dummy.saved_prescan_selections, {})
            self.assertEqual(self.dummy.tv.selected_rows, [])
            self.assertTrue(self.dummy._update_repo_info_called)
        finally:
            # Restore original ui module
            repolens_module.ui = original_ui

    def test_schedule_merge_form_reset_after_success_uses_ui_delay(self) -> None:
        """Test scheduler uses ui.delay when available."""
        import merger.lenskit.frontends.pythonista.repolens as repolens_module
        
        # Track calls to ui.delay
        calls = []
        
        class FakeUI:
            @staticmethod
            def delay(callback, seconds):
                calls.append((callback, seconds))
                callback()
        
        original_ui = repolens_module.ui
        repolens_module.ui = FakeUI
        try:
            # Reset state first
            self.dummy.saved_prescan_selections = {
                "repo-a": {"raw": ["a.py"], "compressed": ["a.py"]},
            }
            self.dummy.tv.selected_rows = [(0, 0)]
            
            # Call scheduler
            MergerUI.schedule_merge_form_reset_after_success(self.dummy)
            
            # Verify ui.delay was called with correct args
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1], 0.0)
            
            # Verify reset was executed
            self.assertEqual(self.dummy.saved_prescan_selections, {})
            self.assertEqual(self.dummy.tv.selected_rows, [])
        finally:
            # Restore original ui module
            repolens_module.ui = original_ui


if __name__ == "__main__":
    unittest.main()
