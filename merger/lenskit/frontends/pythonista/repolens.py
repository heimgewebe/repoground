#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
repoLens – A structural lens for repositories.
Enhanced AI-optimized reports with strict Pflichtenheft structure.

Default-Config (Dec 2025)
------------------------
- level: dev
- mode: gesamt (UI: combined)
- split: ON via split-size default (25MB)
- max-bytes: 0 (keine Kürzung einzelner Dateien)
- extras default ON:
  json_sidecar, augment_sidecar

Rationale:
- max-bytes auf Dateiebene ist semantisch riskant (halbe Datei = halbe Wahrheit).
- Split ist logistisch: alles bleibt drin, nur auf mehrere Parts verteilt.
"""




import sys
import os
import json
import re
import traceback
import datetime
from pathlib import Path
from typing import List, Any, Dict, Optional

# Import new utils/helpers (Avoid circular imports!)
# ARCHITECTURE POLICY:
# 1. Ensure current directory is in sys.path (for script execution)
# 2. Use absolute imports exclusively (no try/except relative)
# 3. This avoids complexity and ensures consistent behavior.

SCRIPT_DIR = Path(__file__).parent.resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _insert_after_script_dir(path_s: str) -> None:
    """Helper to insert paths deterministically after SCRIPT_DIR."""
    if path_s in sys.path:
        return
    try:
        # Insert after SCRIPT_DIR if present, otherwise at start
        idx = sys.path.index(str(SCRIPT_DIR)) + 1
        sys.path.insert(idx, path_s)
    except ValueError:
        sys.path.insert(0, path_s)


# --- FIX START ---
# Auto-detect project root to fix ModuleNotFoundError in standalone mode
try:
    # Walk up until we find the 'merger' directory
    # Structure: .../merger/lenskit/frontends/pythonista/repolens.py
    # We want to add '.../' to sys.path so 'import merger' works.
    _p = SCRIPT_DIR
    while _p.name != "merger" and _p.parent != _p:
        _p = _p.parent

    if _p.name == "merger":
        # Deterministic order: SCRIPT_DIR -> REPO_ROOT -> MERGER_DIR
        # Note: We insert in reverse order of desired precedence because each call
        # inserts immediately after SCRIPT_DIR, pushing previous insertions down.
        _insert_after_script_dir(str(_p))         # Ends up at SCRIPT_DIR + 2
        _insert_after_script_dir(str(_p.parent))  # Ends up at SCRIPT_DIR + 1
except Exception as e:
    try:
        print(f"[repolens] Warning: auto path-detection failed: {e}", file=sys.stderr)
    except Exception:
        print(f"[repolens] Warning: auto path-detection failed: {e}")
# --- FIX END ---

from repolens_utils import normalize_path, normalize_repo_id, safe_script_path
from repolens_helpers import deserialize_prescan_pool, resolve_pool_include_paths


def _flatten_meta(d: Dict[str, Any]) -> Dict[str, Any]:
    """
    Helper to flatten nested 'meta' dicts (legacy v1 compatibility).
    Returns a new dict with top-level keys merged from d['meta'] if present.
    Uses setdefault to avoid overwriting existing top-level keys.
    Removes the nested 'meta' key from the result.
    """
    merged = dict(d)
    meta = merged.pop("meta", None)
    if isinstance(meta, dict):
        for k, v in meta.items():
            merged.setdefault(k, v)
    return merged


DEFAULT_LEVEL = "max"
DEFAULT_MODE = "gesamt"  # combined
DEFAULT_SPLIT_SIZE = "25MB"
DEFAULT_MAX_FILE_BYTES = 0
# Default: Minimal (Agent-fokussiert). Nur Sidecars.
DEFAULT_EXTRAS = "json_sidecar,augment_sidecar"
DEFAULT_META_DENSITY = "auto"

# Whitelist of known extras keys to prevent accidental resets of unknown flags
KNOWN_EXTRAS_KEYS = [
    "health", "organism_index", "fleet_panorama",
    "delta_reports", "augment_sidecar", "heatmap", "json_sidecar"
]

try:
    import appex  # type: ignore
except Exception:
    appex = None  # type: ignore

# Try importing Pythonista modules
# In Shortcuts-App-Extension werfen diese Importe NotImplementedError.
# Deshalb JEGLICHEN Import-Fehler abfangen, nicht nur ImportError.
try:
    import ui        # type: ignore
    import dialogs   # type: ignore
except Exception:
    ui = None
    dialogs = None

try:
    TF_BORDER_NONE = ui.TEXT_FIELD_BORDER_NONE  # neuere Pythonista-Versionen
except Exception:
    TF_BORDER_NONE = 0  # Fallback: Standardwert, entspricht "kein Rahmen"

try:
    import console   # type: ignore
except Exception:
    console = None   # type: ignore

try:
    import editor    # type: ignore
except Exception:
    editor = None    # type: ignore

try:
    import quicklook # type: ignore
except Exception:
    quicklook = None # type: ignore

# Keep track of the currently presented Merger UI view (Pythonista).
# This prevents stacking multiple fullscreen windows when the script is opened repeatedly.
_ACTIVE_MERGER_VIEW = None


# Cache script path at module level for consistent behavior
SCRIPT_PATH = safe_script_path()
SCRIPT_DIR = SCRIPT_PATH.parent


def _notify(msg: str, level: str = "info") -> None:
    """
    Central notification helper that degrades gracefully.
    Levels: 'info', 'success', 'error'
    """
    # 1. Console HUD (Preferred for transient info/success)
    if console:
        try:
            # Map level to duration or icon if needed
            duration = 1.0 if level == "info" else 1.5
            icon_map = {
                "success": "success",
                "error": "error",
                "info": None,
            }
            icon = icon_map.get(level)
            console.hud_alert(msg, icon=icon, duration=duration)
            return
        except Exception:
            pass

    # 2. UI Alert (Fallback for errors or if console missing)
    # Only if ui is available
    if ui:
        try:
            # Short title based on level
            title = "repoLens"
            if level == "error":
                title += " Error"
            ui.alert(title, msg, "OK", hide_cancel_button=True)
            return
        except Exception:
            pass

    # 3. Print (Last resort)
    sys.stderr.write(f"[repoLens] [{level}] {msg}\n")


def force_close_files(paths: List[Path]) -> None:
    """
    Ensures generated files are not left open in the editor.
    """
    if editor is None:
        return

    try:
        open_files = editor.get_open_files()
    except Exception:
        return

    target_names = {p.name for p in paths}

    for fpath in open_files:
        if os.path.basename(fpath) in target_names:
            try:
                editor.close_file(fpath)
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to close {fpath}: {e}\n")


# Merger-UI merkt sich die letzte Auswahl in dieser JSON-Datei im Hub:
LAST_STATE_FILENAME = ".repoLens-state.json"

# Import core logic
try:
    from merger.lenskit.core.merge import (
        MERGES_DIR_NAME,
        PR_SCHAU_DIR,
        SKIP_ROOTS,
        detect_hub_dir,
        get_merges_dir,
        scan_repo,
        write_reports_v2,
        _normalize_ext_list,
        ExtrasConfig,
        parse_human_size,
    )
    from merger.lenskit.core.pr_schau_bundle import load_pr_schau_bundle, BUNDLE_FILENAME
except ImportError:
    # Pythonista / Flat layout fallback
    from lenskit.core.merge import (
        MERGES_DIR_NAME,
        PR_SCHAU_DIR,
        SKIP_ROOTS,
        detect_hub_dir,
        get_merges_dir,
        scan_repo,
        write_reports_v2,
        _normalize_ext_list,
        ExtrasConfig,
        parse_human_size,
    )
    from lenskit.core.pr_schau_bundle import load_pr_schau_bundle, BUNDLE_FILENAME

PROFILE_DESCRIPTIONS = {
    # Kurzbeschreibung der Profile für den UI-Hint
    "overview": (
        "Index-Profil: Struktur + Manifest. "
        "Nur README / Runbooks / ai-context mit Inhalt."
    ),
    "summary": (
        "Doku-/Kontext-Profil: Docs, zentrale Config, CI, Contracts voll. "
        "Code größtenteils nur im Manifest."
    ),
    "dev": (
        "Arbeits-Profil: Code, Tests, Config, CI voll. "
        "Doku nur für README/Runbooks/ai-context voll."
    ),
    "machine-lean": (
        "Schlankes Maschinen-Profil: Manifest + Index + Content ohne Baum-Dekoration."
    ),
    "max": (
        "Vollsnapshot: alle Textdateien mit Inhalt (bis zum Max-Bytes-Limit pro Datei)."
    ),
}

# Voreinstellungen pro Profil:
# - Split-Größe (Part-Größe): standardmäßig 25 MB, d. h. große Merges
#   werden in mehrere Dateien aufgeteilt – es gibt aber kein Gesamtlimit.
# - Max Bytes/File: 0 = unbegrenzt (volle Dateien), Limit nur,
#   wenn explizit gesetzt.
PROFILE_PRESETS = {
    "overview": {
        # 0 → „kein per-File-Limit“
        "max_bytes": 0,
        "split_mb": 25,
    },
    "summary": {
        "max_bytes": 0,
        "split_mb": 25,
    },
    "dev": {
        "max_bytes": 0,
        "split_mb": 25,
    },
    "machine-lean": {
        "max_bytes": 0,
        "split_mb": 25,
    },
    "max": {
        "max_bytes": 0,
        "split_mb": 25,
    },
}


# --- Helper ---

def find_repos_in_hub(hub: Path) -> List[str]:
    repos: List[str] = []
    if not hub.exists():
        return []
    for child in sorted(hub.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name in SKIP_ROOTS:
            continue
        if child.name == MERGES_DIR_NAME:
            continue
        if child.name.startswith("."):
            continue
        repos.append(child.name)
    return repos


def _pick_primary_artifact(paths):
    # Prefer primary JSON for agent chains, else fallback to markdown.
    for p in paths:
        try:
            if str(p).lower().endswith(".json"):
                return p
        except Exception:
            pass
    for p in paths:
        try:
            if str(p).lower().endswith(".md"):
                return p
        except Exception:
            pass
    return paths[0] if paths else None


def _pick_human_md(paths) -> Optional[Path]:
    for p in paths:
        try:
            if str(p).lower().endswith(".md"):
                return p
        except Exception:
            pass
    return None


def _load_repolens_extractor_module():
    """Load extractor module from core."""
    try:
        from merger.lenskit.core import extractor
        return extractor
    except ImportError:
        try:
            from lenskit.core import extractor
            return extractor
        except Exception as exc:
            print(f"[repoLens] could not load lenskit.core.extractor: {exc}")
            return None
    except Exception as exc:
        print(f"[repoLens] could not load merger.lenskit.core.extractor: {exc}")
        return None


# --- UI Class (Pythonista) ---

class PRSchauDataSource(object):
    def __init__(self, items):
        self.items = items
        self.selected = set()
        self.last_tapped_row = -1

    def tableview_number_of_rows(self, tv, section):
        return len(self.items)

    def tableview_cell_for_row(self, tv, section, row):
        cell = ui.TableViewCell()
        cell.background_color = "#111111"
        cell.text_label.font = ("<System>", 14)
        cell.text_label.text = self.items[row]["display"]

        # Custom selection background
        bg = ui.View()
        bg.background_color = "#333333"
        cell.selected_background_view = bg

        if row in self.selected:
            cell.accessory_type = "checkmark"
            # Purple highlight for text to indicate selection
            cell.text_label.text_color = "#E0B0FF"
        else:
            cell.accessory_type = "none"
            cell.text_label.text_color = "white"

        return cell

    def tableview_did_select(self, tv, section, row):
        self.last_tapped_row = row
        if row in self.selected:
            self.selected.remove(row)
        else:
            self.selected.add(row)

        # Robust reload: try various signatures known in different Pythonista versions
        try:
            # Common/simpler signature first (list of rows, implicit section 0 or explicit kwarg)
            tv.reload_rows([row])
        except Exception:
            try:
                # Explicit tuple signature [(section, row)]
                tv.reload_rows([(section, row)])
            except Exception:
                # Fallback
                tv.reload_data()


def _run_extractor_on_start(hub: Path) -> None:
    """Run repolens-extractor automatically at app start (best-effort, quiet)."""
    try:
        extractor = _load_repolens_extractor_module()
        if extractor is None:
            return
        # Preferred API (added for startup auto-run)
        if hasattr(extractor, "run_extractor"):
            try:
                # Use incremental=True to avoid unnecessary work
                extractor.run_extractor(hub_override=hub, show_alert=False, incremental=True)
            except TypeError:
                # Fallback if incremental arg is not yet available in loaded module (race condition or old version)
                extractor.run_extractor(hub)
            return
        # Fallback: do nothing rather than popping alerts or blocking startup.
    except Exception as e:
        sys.stderr.write(f"[repoLens] Extractor auto-run warning: {e}\n")
        return


def _dismiss_view_best_effort(v) -> None:
    """
    Pythonista-UI: möglichst robust schließen, unabhängig davon,
    ob der View via present()/sheet()/fullscreen oder als Subview hängt.
    Reihenfolge ist Absicht: dismiss() ist bei präsentierten Views am wirksamsten.
    """
    if v is None:
        return
    # 1) dismiss (für present('fullscreen'/'sheet'/etc.))
    try:
        v.dismiss()
    except Exception:
        pass
    # 2) close (für manche Kontexte / Fallback)
    try:
        v.close()
    except Exception:
        pass
    # 3) remove_from_superview (falls der View irgendwo eingebettet ist)
    try:
        if getattr(v, "superview", None) is not None:
            v.remove_from_superview()
    except Exception:
        pass


def run_ui(hub: Path) -> int:
    """Starte den Merger im Vollbild-UI-Modus ohne Pythonista-Titlebar."""
    global _ACTIVE_MERGER_VIEW
    # If there is already a Merger view on screen, close it before presenting a new one.
    try:
        if _ACTIVE_MERGER_VIEW is not None:
            _dismiss_view_best_effort(_ACTIVE_MERGER_VIEW)
            _ACTIVE_MERGER_VIEW = None
    except Exception:
        # Never block opening a new UI because cleanup failed.
        pass

    _run_extractor_on_start(hub)

    ui_obj = MergerUI(hub)
    v = ui_obj.view
    _ACTIVE_MERGER_VIEW = v
    # Volle Fläche, eigene „Titlebar“ im View, keine weiße System-Leiste
    v.present('fullscreen', hide_title_bar=True)
    return 0

class MergerUI(object):
    def __init__(self, hub: Path) -> None:
        self.hub = hub
        self.repos = find_repos_in_hub(hub)

        # Ignore-Konfiguration für das Heimgewebe-Set
        self.ignore_mode = False
        self.ignored_repos = set()

        # Pfad zur State-Datei
        self._state_path = (self.hub / LAST_STATE_FILENAME).resolve()
        # Beim Start nur die persistierte Ignore-Liste laden – nicht die gesamte UI-Config
        self._load_ignored_repos_from_state()

        # Flag to strictly prevent merge when prescan is active
        self._prescan_active = False

        # Saved Prescan Selections (Pool)
        # repo_name -> {"raw": None|list[str], "compressed": None|list[str]}
        # POOL CONTRACT:
        # - raw: None (ALL) or list of all selected FILE paths (UI truth, MUST be files only)
        # - compressed: None (ALL) or list of compressed paths (dirs/files for backend)
        self.saved_prescan_selections: Dict[str, Dict[str, Optional[List[str]]]] = {}

        # Auto-run / warm the extractor on startup (best-effort).
        # This makes delta/inspection features immediately usable and surfaces hub issues early,
        # without breaking the main UI if anything is missing.
        try:
            mod = _load_repolens_extractor_module()
            # Prefer passing the detected hub explicitly so extractor and UI agree.
            try:
                mod.detect_hub(str(self.hub))
            except TypeError:
                # older extractor signature: detect_hub() with no args
                mod.detect_hub()
        except Exception as e:
            # Keep UI functional; extractor is an enhancement, not a hard dependency.
            print(f"[extractor] warmup skipped: {e}")

        # Basic argv parsing for UI defaults
        # Expected format: repolens.py --level max --mode gesamt ...
        import argparse
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--level", default=DEFAULT_LEVEL)
        parser.add_argument("--mode", default=DEFAULT_MODE)
        # 0 = unbegrenzt
        parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
        # Default: ab 25 MB wird gesplittet
        parser.add_argument("--split-size", default=DEFAULT_SPLIT_SIZE)
        parser.add_argument("--extras", default=DEFAULT_EXTRAS)
        # Ignore unknown args
        args, _ = parser.parse_known_args()

        # Initiale Extras aus CLI args
        self.extras_config, warnings = ExtrasConfig.from_csv(args.extras)
        for w in warnings:
            _notify(w, "info")

        v = ui.View()
        v.name = "WC-Merger"
        v.background_color = "#111111"

        # Vollbild nutzen – die Größe übernimmt dann das fullscreen-Present.
        try:
            screen_w, screen_h = ui.get_screen_size()
            v.frame = (0, 0, screen_w, screen_h)
        except Exception:
            # Fallback, falls get_screen_size nicht verfügbar ist
            v.frame = (0, 0, 1024, 768)
        v.flex = "WH"

        self.view = v

        def _wrap_textfield_in_dark_bg(parent_view, tf):
            """
            Wrapper für Eingabefelder.

            Wichtiger als „perfekt dunkel“ ist hier:
            - Text immer gut lesbar
            - keine weiße Schrift auf weißem Feld

            Darum nutzen wir den systemhellen TextField-Hintergrund
            und erzwingen nur gut sichtbare Schrift / Cursor.
            """

            # System-Hintergrund (hell) beibehalten
            tf.background_color = None
            tf.text_color = "black"        # gut lesbar auf hell
            tf.tint_color = "#007aff"      # Standard-iOS-Blau für Cursor/Markierung

            if hasattr(tf, "border_style"):
                try:
                    tf.border_style = TF_BORDER_NONE
                except Exception as e:
                    sys.stderr.write(f"Warning: Failed to set text field border style: {e}\n")

            # Kein extra Hintergrund-View mehr – direkt hinzufügen
            parent_view.add_subview(tf)

        # kleine Helper-Funktion für Dark-Theme-Textfelder
        def _style_textfield(tf: ui.TextField) -> None:
            """Basis-Styling, Wrapper übernimmt das Dunkel-Thema."""
            tf.autocorrection_type = False
            tf.autocapitalization_type = ui.AUTOCAPITALIZE_NONE

        margin = 10
        top_padding = 22  # etwas mehr Abstand zur iOS-Statusleiste
        y = 10 + top_padding

        # --- TOP HEADER ---
        # Gemeinsame Button-Leiste rechts oben: [Ignore] [Set] [Close]
        btn_width = 76
        btn_height = 28
        btn_margin_right = 10
        btn_spacing = 6

        # Close ganz rechts
        close_btn = ui.Button()
        close_btn.title = "Close"
        close_btn.frame = (
            v.width - btn_margin_right - btn_width,
            y,
            btn_width,
            btn_height,
        )
        close_btn.flex = "L"
        close_btn.background_color = "#333333"
        close_btn.tint_color = "white"
        close_btn.corner_radius = 4.0
        close_btn.action = self.close_view
        v.add_subview(close_btn)
        self.close_button = close_btn

        # Set links neben Close
        select_all_btn = ui.Button()
        select_all_btn.title = "Set"
        select_all_btn.frame = (
            close_btn.frame[0] - btn_spacing - btn_width,
            close_btn.frame[1],
            btn_width,
            btn_height,
        )
        select_all_btn.flex = "L"
        select_all_btn.background_color = "#333333"
        select_all_btn.tint_color = "white"
        select_all_btn.corner_radius = 4.0
        select_all_btn.action = self.select_all_repos
        v.add_subview(select_all_btn)
        self.select_all_button = select_all_btn

        # Ignore links von Set
        ignore_btn = ui.Button()
        ignore_btn.title = "Ignore…"
        ignore_btn.frame = (
            select_all_btn.frame[0] - btn_spacing - btn_width,
            close_btn.frame[1],
            btn_width,
            btn_height,
        )
        ignore_btn.flex = "L"
        ignore_btn.background_color = "#444444"
        ignore_btn.tint_color = "white"
        ignore_btn.corner_radius = 4.0
        ignore_btn.action = self.toggle_ignore_mode
        v.add_subview(ignore_btn)
        self.ignore_button = ignore_btn

        # Base-Dir-Label bekommt rechts ausreichend Platz vor der Button-Leiste
        base_label = ui.Label()
        max_label_width = ignore_btn.frame[0] - 10 - 4  # kleiner Sicherheitsabstand
        base_label.frame = (10, y, max_label_width, 34)
        base_label.flex = "W"
        base_label.number_of_lines = 2
        base_label.text = f"Base-Dir: {hub}"
        base_label.text_color = "white"
        base_label.background_color = "#111111"
        base_label.font = ("<System>", 11)
        v.add_subview(base_label)
        self.base_label = base_label

        y += 40

        repo_label = ui.Label()
        # Platz lassen für „Alle auswählen“-Button rechts
        repo_label.frame = (10, y, v.width - 110, 20)
        repo_label.flex = "W"
        repo_label.text = "Repos (Tap = Auswahl, None = All, SET = Heimgewebe):"
        repo_label.text_color = "white"
        repo_label.background_color = "#111111"
        repo_label.font = ("<System>", 13)
        v.add_subview(repo_label)
        # interner Toggle-Status für den All-Button
        self._all_toggle_selected = False

        y += 22
        top_header_height = y

        # --- BOTTOM SETTINGS & ACTIONS ---
        # Container view for all controls that should stick to the bottom
        # Layout calculation inside the container (starts at y=0)
        cy = 10
        cw = v.width
        # We'll set the container height at the end

        # We need a temporary container to add subviews to, but we'll attach it to v later
        bottom_container = ui.View()
        # Set initial width so subview flex calculations (right margin) work correctly
        bottom_container.frame = (0, 0, cw, 100)
        bottom_container.background_color = "#111111" # Same as v

        ext_label = ui.Label(
            frame=(10, cy, 130, 24),
            text="Filter: Extensions",
            text_color="white",
            font=("<System>", 12),
        )
        bottom_container.add_subview(ext_label)

        self.ext_field = ui.TextField(
            frame=(140, cy, cw - 150, 28),
            placeholder=".py,.rs,.md (leer = alle)",
        )
        _style_textfield(self.ext_field)
        _wrap_textfield_in_dark_bg(bottom_container, self.ext_field)
        cy += 30

        path_label = ui.Label(
            frame=(10, cy, 130, 24),
            text="Filter: Pfad",
            text_color="white",
            font=("<System>", 12),
        )
        bottom_container.add_subview(path_label)

        self.path_field = ui.TextField(
            frame=(140, cy, cw - 200, 28),
            placeholder="z. B. merger/, src/, docs/",
        )
        _style_textfield(self.path_field)
        self.path_field.autocorrection_type = False
        self.path_field.spellchecking_type = False
        _wrap_textfield_in_dark_bg(bottom_container, self.path_field)

        # Fix 2: Pool Button
        pool_btn = ui.Button(title="Pool")
        pool_btn.frame = (cw - 50, cy, 40, 28)
        pool_btn.flex = "L"
        pool_btn.background_color = "#555555"
        pool_btn.tint_color = "white"
        pool_btn.corner_radius = 4
        pool_btn.font = ("<System-Bold>", 12)
        pool_btn.action = self.show_pool_viewer
        bottom_container.add_subview(pool_btn)

        cy += 36

        # --- Detail: eigene Zeile ---
        detail_label = ui.Label()
        detail_label.text = "Detail:"
        detail_label.text_color = "white"
        detail_label.background_color = "#111111"
        detail_label.frame = (10, cy, 60, 22)
        bottom_container.add_subview(detail_label)

        seg_detail = ui.SegmentedControl()
        seg_detail.segments = ["overview", "summary", "dev", "max"]
        try:
            seg_detail.selected_index = seg_detail.segments.index(args.level)
        except ValueError:
            seg_detail.selected_index = 2  # Default dev für arbeitsfähiges Profil
        seg_detail.frame = (70, cy - 2, cw - 80, 28)
        seg_detail.flex = "W"
        # Use standard iOS blue instead of white for better contrast
        seg_detail.tint_color = "#007aff"
        seg_detail.background_color = "#dddddd"
        seg_detail.action = self.on_profile_changed
        bottom_container.add_subview(seg_detail)
        self.seg_detail = seg_detail

        # Kurzer Text unterhalb der Detail-Presets
        self.profile_hint = ui.Label(
            frame=(margin, cy + 28, cw - 2 * margin, 20),
            flex="W",
            text="",
            text_color="white",
            font=("<system>", 12),
        )
        bottom_container.add_subview(self.profile_hint)
        cy += 24 # Platz für Hint

        cy += 36  # neue Zeile für Mode

        # --- Mode: darunter, eigene Zeile ---
        mode_label = ui.Label()
        mode_label.text = "Mode:"
        mode_label.text_color = "white"
        mode_label.background_color = "#111111"
        mode_label.frame = (10, cy, 60, 22)
        bottom_container.add_subview(mode_label)

        seg_mode = ui.SegmentedControl()
        seg_mode.segments = ["combined", "per repo"]
        if args.mode == "pro-repo":
            seg_mode.selected_index = 1
        else:
            seg_mode.selected_index = 0
        seg_mode.frame = (70, cy - 2, cw - 80, 28)
        seg_mode.flex = "W"
        # Same accent color as detail segmented control
        seg_mode.tint_color = "#007aff"
        seg_mode.background_color = "#dddddd"
        bottom_container.add_subview(seg_mode)
        self.seg_mode = seg_mode

        cy += 36

        # --- Meta Density ---
        meta_label = ui.Label()
        meta_label.text = "Meta:"
        meta_label.text_color = "white"
        meta_label.background_color = "#111111"
        meta_label.frame = (10, cy, 60, 22)
        bottom_container.add_subview(meta_label)

        seg_meta = ui.SegmentedControl()
        seg_meta.segments = ["auto", "min", "standard", "full"]
        seg_meta.selected_index = 0 # Default auto
        seg_meta.frame = (70, cy - 2, cw - 80, 28)
        seg_meta.flex = "W"
        seg_meta.tint_color = "#007aff"
        seg_meta.background_color = "#dddddd"
        bottom_container.add_subview(seg_meta)
        self.seg_meta = seg_meta

        cy += 36

        max_label = ui.Label()
        max_label.text = "Max Bytes/File:"
        max_label.text_color = "white"
        max_label.background_color = "#111111"
        max_label.frame = (10, cy, 120, 22)
        bottom_container.add_subview(max_label)

        max_field = ui.TextField()
        # 0 oder kleiner = „unbegrenzt“ → Feld leer lassen
        if args.max_bytes and args.max_bytes > 0:
            max_field.text = str(args.max_bytes)
        else:
            max_field.text = ""
        max_field.frame = (130, cy - 2, 140, 28)
        max_field.flex = "W"
        max_field.placeholder = "0 / empty = unlimited"
        _style_textfield(max_field)
        max_field.keyboard_type = ui.KEYBOARD_NUMBER_PAD
        _wrap_textfield_in_dark_bg(bottom_container, max_field)
        self.max_field = max_field

        cy += 36

        split_label = ui.Label()
        # Globale Split-Größe:
        # steuert optional, ob der Merge in mehrere Dateien aufgeteilt wird,
        # ist aber **kein** harter Global-Limit-Cut.
        split_label.text = "Split Size (MB):"
        split_label.text_color = "white"
        split_label.background_color = "#111111"
        split_label.frame = (10, cy, 120, 22)
        bottom_container.add_subview(split_label)

        split_field = ui.TextField()
        # Leer oder 0 = kein Split → ein Merge ohne globales Größenlimit.
        split_field.placeholder = "leer/0 = kein Split"
        # UI erwartet MB als Zahl; CLI/Config dürfen aber auch "25MB" o.ä. liefern.
        split_text = ""
        raw_split = (getattr(args, "split_size", "") or "").strip()
        if raw_split and raw_split != "0":
            if raw_split.isdigit():
                split_text = raw_split
            else:
                try:
                    mb = int(round(parse_human_size(raw_split) / (1024 * 1024)))
                    split_text = str(mb) if mb > 0 else ""
                except Exception:
                    # Fallback: lieber sichtbar machen als stillschweigend löschen
                    split_text = raw_split
        split_field.text = split_text
        split_field.frame = (130, cy - 2, 140, 28)
        split_field.flex = "W"
        _style_textfield(split_field)
        split_field.keyboard_type = ui.KEYBOARD_NUMBER_PAD
        _wrap_textfield_in_dark_bg(bottom_container, split_field)
        self.split_field = split_field

        cy += 36

        # --- Plan Only Switch ---
        plan_label = ui.Label()
        plan_label.text = "Plan only:"
        plan_label.text_color = "white"
        plan_label.background_color = "#111111"
        plan_label.frame = (10, cy, 120, 22)
        bottom_container.add_subview(plan_label)

        plan_switch = ui.Switch()
        plan_switch.frame = (130, cy - 2, 60, 32)
        plan_switch.flex = "W"
        plan_switch.value = False
        bottom_container.add_subview(plan_switch)
        self.plan_only_switch = plan_switch

        # --- Code Only Switch (direkt neben Plan Only) ---
        code_label = ui.Label()
        code_label.text = "Code only:"
        code_label.text_color = "white"
        code_label.background_color = "#111111"
        code_label.frame = (210, cy, 120, 22)
        bottom_container.add_subview(code_label)

        code_switch = ui.Switch()
        code_switch.frame = (330, cy - 2, 60, 32)
        code_switch.flex = "W"
        code_switch.value = False
        bottom_container.add_subview(code_switch)
        self.code_only_switch = code_switch

        cy += 36

        info_label = ui.Label()
        info_label.text_color = "white"
        info_label.background_color = "#111111"
        info_label.font = ("<System>", 11)
        info_label.number_of_lines = 1
        info_label.frame = (10, cy, cw - 20, 18)
        info_label.flex = "W"
        bottom_container.add_subview(info_label)
        self.info_label = info_label
        self._update_repo_info()

        # Initiale Anzeige des Hints
        self.on_profile_changed(None)

        cy += 26

        # --- Buttons am unteren Rand (innerhalb des Containers) ---

        cy += 10 # Gap
        cy = self._make_bottom_bar(bottom_container, cy, cw)
        cy += 24 # Bottom margin inside container

        container_height = cy

        # Now place the container at the bottom of the main view
        bottom_container.frame = (0, v.height - container_height, v.width, container_height)
        bottom_container.flex = "WT" # Width flex, Top margin flex (stays at bottom)
        v.add_subview(bottom_container)

        # --- REPO LIST ---
        # The list fills the space between header and bottom container
        tv = ui.TableView()

        # Calculate height: available space between top header and bottom container
        list_height = v.height - top_header_height - container_height

        tv.frame = (10, top_header_height, v.width - 20, list_height)
        tv.flex = "WH" # Width flex, Height flex (fills space)
        tv.background_color = "#111111"
        tv.separator_color = "#333333"
        tv.row_height = 32
        tv.allows_multiple_selection = True
        # Improve readability on dark background
        tv.tint_color = "#007aff"

        ds = ui.ListDataSource(self.repos)
        ds.text_color = "white"
        # Bei Auswahl/Deselektion die Statuszeile aktualisieren
        ds.action = self._on_repo_selection_changed
        ds.tableview_did_select = self._tableview_did_select
        ds.tableview_did_deselect = self._tableview_did_deselect
        # deutliche Selektion: kräftiges Blau statt „grau auf schwarz“
        ds.highlight_color = "#0050ff"
        ds.tableview_cell_for_row = self._tableview_cell
        tv.data_source = ds
        tv.delegate = ds
        v.add_subview(tv)
        self.tv = tv
        self.ds = ds

        # Beim Start: Defaults verwenden, nur Ignore-Liste wurde bereits geladen.
        # Info-Zeile initial aktualisieren.
        self._update_repo_info()

    def _make_bottom_bar(self, parent, y, w):
        """
        Erstellt die kompakte Button-Bar (2 Reihen).
        Reihe 1: Extras | Load | Delta | PR-Schau
        Reihe 2: Run Merge (CTA)
        """
        # Reihe 1: Buttons
        row1_h = 34
        gap = 8
        margin = 10

        # Titles & Actions
        # Presets, Extras, Load, Delta, Prescan, PR-Schau

        # 5 Buttons (Presets removed)
        count = 5
        w_avail = w - (2 * margin)
        btn_w = (w_avail - (count - 1) * gap) / count

        btns = [
            ("Extras", self.show_extras_sheet, "#333333"),
            ("Load", self.restore_last_state, "#333333"),
            ("Delta", self.run_delta_from_last_import, "#444444"), # Delta slightly different
            ("Prescan", self.show_prescan_sheet, "#555555"),       # Grey for Prescan
            ("PR-Schau", self.show_pr_schau_browser, "#8E44AD"),   # Purple
        ]

        curr_x = margin
        for title, action, color in btns:
            b = ui.Button()
            b.title = title
            b.font = ("<System>", 12)  # Slightly smaller font to fit
            b.frame = (curr_x, y, btn_w, row1_h)
            b.flex = "W"
            b.background_color = color
            b.tint_color = "white"
            b.corner_radius = 6.0
            b.action = action
            parent.add_subview(b)

            # Save references if needed (delta button was saved in self.delta_button)
            if title == "Delta":
                self.delta_button = b

            curr_x += btn_w + gap

        y += row1_h + gap

        # Reihe 2: Run Merge
        row2_h = 42

        run_btn = ui.Button()
        run_btn.title = "Run Merge"
        run_btn.font = ("<System-Bold>", 16)
        run_btn.frame = (margin, y, w - 2*margin, row2_h)
        run_btn.flex = "W"
        run_btn.background_color = "#007aff"
        run_btn.tint_color = "white"
        run_btn.corner_radius = 6.0
        run_btn.action = self.run_merge
        parent.add_subview(run_btn)
        self.run_button = run_btn

        y += row2_h
        return y

    def _tableview_did_select(self, tableview, section, row):
        if self.ignore_mode:
            self._update_repo_info()
            return
        self._on_repo_selection_changed(tableview)

    def _tableview_did_deselect(self, tableview, section, row):
        if self.ignore_mode:
            self._update_repo_info()
            return
        self._on_repo_selection_changed(tableview)

    def _on_repo_selection_changed(self, sender) -> None:
        """Callback des ListDataSource – hält die Info-Zeile in Sync."""
        self._update_repo_info()

    def _update_repo_info(self) -> None:
        """Zeigt unten an, wie viele Repos es gibt und wie viele ausgewählt sind."""
        if not self.repos:
            self.info_label.text = "No repos found in Hub."
            return

        total = len(self.repos)
        tv = getattr(self, "tv", None)
        if tv is None:
            self.info_label.text = f"{total} Repos found."
            return

        rows = tv.selected_rows or []
        if not rows:
            # Semantik „none = all“ steht bereits in der Überschrift über der Liste.
            self.info_label.text = f"{total} Repos found."
        else:
            self.info_label.text = f"{total} Repos found ({len(rows)} selected)."

    def toggle_ignore_mode(self, sender) -> None:
        """Umschalten zwischen Normalmodus und Ignore-Auswahlmodus."""
        self.ignore_mode = not self.ignore_mode

        if self.ignore_mode:
            # Bisher ignorierte Repos markieren
            self.tv.selected_rows = [
                (0, idx) for idx, name in enumerate(self.repos)
                if name in self.ignored_repos
            ]
            self.ignore_button.title = "Save"
        else:
            rows = self.tv.selected_rows or []
            newly_ignored: set[str] = set()

            for sec, idx in rows:
                if sec == 0 and 0 <= idx < len(self.repos):
                    newly_ignored.add(self.repos[idx])

            # Wenn aus irgendeinem Grund keine Zeilen selektiert sind,
            # lassen wir eine bereits existierende Ignore-Liste intakt,
            # statt sie stillschweigend zu leeren.
            if newly_ignored:
                self.ignored_repos = newly_ignored
            self.ignore_button.title = "Ignore…"
            # Nur die Ignore-Liste persistent machen, nicht die gesamte Merge-Config
            self.save_last_state(ignore_only=True)

            # Zurück in den Merge-Modus ohne Vorauswahl
            self.tv.selected_rows = []

        self._update_repo_info()

    def select_all_repos(self, sender) -> None:
        """
        SET: Wählt das Heimgewebe-Set an Repositories aus.

        Semantik:
        - Wenn die Ignore-Liste leer ist:
          → Alle Repos selektieren (wie früher „All“).
        - Wenn die Ignore-Liste gefüllt ist:
          → Alle Repos selektieren, deren Name NICHT in der Ignore-Liste steht.

        „None = All“-Semantik bleibt außerhalb von SET bestehen:
        - Keine Selektion = alle Repos mergen.
        """
        if not self.repos:
            return

        excluded = self.ignored_repos
        tv = self.tv

        rows: List[tuple[int, int]] = []
        for idx, name in enumerate(self.repos):
            if name in excluded:
                continue
            rows.append((0, idx))

        # Wenn nichts übrig bleibt → lieber keine Selektion setzen,
        # damit das Verhalten klar sichtbar bleibt.
        if not rows:
            tv.selected_rows = []
        else:
            tv.selected_rows = rows

        self._update_repo_info()

    def close_view(self, sender=None) -> None:
        """Schließt den Merger-Screen in Pythonista."""
        global _ACTIVE_MERGER_VIEW
        try:
            # dismiss() ist bei präsentierten Views zuverlässiger als close()
            _dismiss_view_best_effort(self.view)
        except Exception as e:
            # im Zweifel lieber still scheitern, statt iOS-Alert zu nerven, aber loggen
            sys.stderr.write(f"Warning: Failed to close view: {e}\n")
        finally:
            # If this instance is the active one, clear the pointer.
            try:
                if _ACTIVE_MERGER_VIEW is self.view:
                    _ACTIVE_MERGER_VIEW = None
            except Exception:
                pass

    def show_extras_sheet(self, sender):
        """Zeigt ein Sheet zur Konfiguration der Extras."""
        s = ui.View()
        s.name = "Extras"
        s.background_color = "#222222"

        # Items definieren, um Höhe zu berechnen
        items = [
            ("Repo Health Checks", "health"),
            ("Organism Index", "organism_index"),
            ("Fleet Panorama", "fleet_panorama"),
            ("Delta Reports", "delta_reports"),
            ("Augment Sidecar", "augment_sidecar"),
            ("AI Heatmap", "heatmap"),
            ("JSON Sidecar", "json_sidecar")
        ]

        row_h = 44
        padding_top = 20
        padding_bottom = 20
        title_height = 50 # War 40 + gap, wir nehmen etwas mehr für 2 Zeilen

        dynamic_h = padding_top + title_height + len(items) * row_h + padding_bottom + 60 # +60 für Done-Button + Gap

        # Mindest- und Maximalhöhe setzen (Pythonista Sheet Constraints)
        dynamic_h = max(260, min(dynamic_h, 540))

        s.frame = (0, 0, 420, dynamic_h)

        y = 20
        margin = 20
        w = s.width - 2 * margin

        lbl = ui.Label(frame=(margin, y, w, 40))
        lbl.text = "Optionale Zusatzanalysen\n(Health, Organism, etc.)"
        lbl.number_of_lines = 2
        lbl.text_color = "white"
        lbl.alignment = ui.ALIGN_CENTER
        s.add_subview(lbl)
        y += 50

        # Helper for switches
        def add_switch(key, title):
            nonlocal y
            sw = ui.Switch()
            sw.value = getattr(self.extras_config, key)
            sw.name = key
            # Action: direkt in self.extras_config schreiben
            def action(sender):
                setattr(self.extras_config, key, sender.value)
            sw.action = action
            sw.frame = (w - 60, y, 60, 32)

            l = ui.Label(frame=(margin, y, w - 70, 32))
            l.text = title
            l.text_color = "white"

            s.add_subview(l)
            s.add_subview(sw)
            y += row_h

        for title, key in items:
            add_switch(key, title)

        # Close button
        y += 10
        btn = ui.Button(frame=(margin, y, w, 40))
        btn.title = "Done"
        btn.background_color = "#007aff"
        btn.tint_color = "white"
        btn.corner_radius = 6
        def close_action(sender):
            s.close()
        btn.action = close_action
        s.add_subview(btn)

        s.present("sheet")

    def on_profile_changed(self, sender):
        """
        Aktualisiert den Hint-Text und setzt sinnvolle Defaults
        für max_bytes / split_size basierend auf dem gewählten Profil.

        Wichtig: Pfad- und Extension-Filter bleiben unverändert, damit
        man sie frei kombinieren kann (Profil + eigener Filter).
        """
        idx = self.seg_detail.selected_index
        if not (0 <= idx < len(self.seg_detail.segments)):
            return

        seg_name = self.seg_detail.segments[idx]

        # Hint-Text aktualisieren
        desc = PROFILE_DESCRIPTIONS.get(seg_name, "")
        self.profile_hint.text = desc

        # Presets anwenden (nur max_bytes + split_mb)
        preset = PROFILE_PRESETS.get(seg_name)
        if preset:
            # Max Bytes/File:
            # 0 oder None = unbegrenzt → Feld leer lassen
            max_bytes = preset.get("max_bytes", 0)
            if max_bytes is None or max_bytes <= 0:
                self.max_field.text = ""
            else:
                try:
                    self.max_field.text = str(int(max_bytes))
                except Exception:
                    # Fallback: lieber „unlimited“ als ein falscher Wert
                    self.max_field.text = ""

            # Gesamtlimit (Total Limit / Split = Part-Größe):
            split_mb = preset.get("split_mb")
            # None oder <=0 = kein Split → Feld leer lassen
            if split_mb is None or (
                isinstance(split_mb, (int, float)) and split_mb <= 0
            ):
                self.split_field.text = ""
            else:
                try:
                    self.split_field.text = str(int(split_mb))
                except Exception:
                    self.split_field.text = ""

    # --- State-Persistenz -------------------------------------------------

    def _collect_selected_repo_names(self) -> List[str]:
        """Liest die aktuell in der Liste selektierten Repos aus."""
        # abhängig davon, wie deine TableView/DataSource arbeitet:
        ds = self.ds
        selected: List[str] = []
        if hasattr(ds, "items"):
            # Standard ui.ListDataSource
            rows = getattr(self.tv, "selected_rows", None) or []
            for idx, name in enumerate(ds.items):
                # selected_rows ist eine Liste von Tupeln (section, row)
                if any(sec == 0 and r == idx for sec, r in rows):
                    selected.append(name)
        return selected

    def _apply_selected_repo_names(self, names: List[str]) -> None:
        """Setzt die Repo-Auswahl anhand gespeicherter Namen."""
        ds = self.ds
        if not hasattr(ds, "items"):
            return

        name_to_index = {name: i for i, name in enumerate(ds.items)}

        rows = []
        for name in names:
            idx = name_to_index.get(name)
            if idx is not None:
                rows.append((0, idx))

        if not rows:
            # Explicitly clear selection if list is empty
            try:
                self.tv.selected_rows = []
                # Defensive: force visual refresh
                if hasattr(self.tv, "reload_data"):
                    self.tv.reload_data()
            except Exception:
                pass
            return

        tv = self.tv
        try:
            tv.selected_rows = rows
        except Exception:
            # Fallback: nur die erste gefundene Zeile selektieren
            try:
                tv.selected_row = rows[0]
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to select row in fallback: {e}\n")

    def _load_ignored_repos_from_state(self) -> None:
        """Lädt beim Start nur die persistierte Ignore-Liste."""
        # _state_path wird im __init__ gesetzt
        try:
            raw = self._state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except Exception as exc:
            print(f"[repoLens] could not read ignore state: {exc!r}")
            return

        try:
            data = json.loads(raw)
        except Exception as exc:
            print(f"[repoLens] invalid ignore state JSON: {exc!r}")
            return

        if isinstance(data, dict):
            self.ignored_repos = set(data.get("ignored_repos", []))

    def _serialize_prescan_pool(self) -> Dict[str, Any]:
        """
        Serialize prescan pool to structured format.
        Internal format is already {"raw": ..., "compressed": ...}.
        """
        serialized = {}
        for repo, selection in self.saved_prescan_selections.items():
            if isinstance(selection, dict):
                # Already in structured format
                serialized[repo] = {
                    "raw": selection.get("raw"),
                    "compressed": selection.get("compressed")
                }
            else:
                # Shouldn't happen with new code, but handle legacy just in case
                if selection is None:
                    serialized[repo] = {"raw": None, "compressed": None}
                elif isinstance(selection, list):
                    serialized[repo] = {"raw": selection, "compressed": selection}
        return serialized

    def save_last_state(self, ignore_only: bool = False) -> None:
        """
        Speichert den UI-Zustand in einer JSON-Datei.

        ignore_only = True:
            Nur die Ignore-Liste aktualisieren, sonstige Felder unangetastet lassen.
        ignore_only = False:
            Vollständige Config (Filter, Profile, Auswahl, Extras) + Ignore-Liste speichern.
        """
        data: Dict[str, Any] = {}

        # Bestehenden Zustand laden, damit wir bei ignore_only nicht alles überschreiben
        if self._state_path.exists():
            try:
                raw = self._state_path.read_text(encoding="utf-8")
                existing = json.loads(raw)
                if isinstance(existing, dict):
                    data.update(existing)
            except Exception as exc:
                print(f"[repoLens] could not read existing state: {exc!r}")

        # Ignore-Liste wird *immer* aktualisiert
        data["ignored_repos"] = sorted(self.ignored_repos)

        # Nur wenn wir *nicht* im ignore_only-Modus sind, die restliche Config überschreiben
        if not ignore_only:
            profile = None
            try:
                segments = getattr(self.seg_detail, "segments", [])
                idx = getattr(self.seg_detail, "selected_index", 0)
                if 0 <= idx < len(segments):
                    profile = segments[idx]
            except Exception:
                profile = None

            if profile is not None:
                data["detail_profile"] = profile

            data.update(
                {
                    "ext_filter": self.ext_field.text or "",
                    "path_filter": self.path_field.text or "",
                    "max_bytes": self.max_field.text or "",
                    "split_mb": self.split_field.text or "",
                    "meta_density_index": self.seg_meta.selected_index,
                    "plan_only": bool(self.plan_only_switch.value),
                    "code_only": bool(getattr(self, "code_only_switch", False) and self.code_only_switch.value),
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
                }
            )

        try:
            self._state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[repoLens] could not persist state: {exc}")

    def restore_last_state(self, sender=None) -> None:
        try:
            raw = self._state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            if sender: # Nur bei Klick Feedback geben
                if console:
                    console.alert("repoLens", "No saved state found.", "OK", hide_cancel_button=True)
            return
        except Exception as exc:
            print(f"[repoLens] could not read state: {exc!r}", file=sys.stderr)
            return

        try:
            data = json.loads(raw)
        except Exception as exc:
            print(f"[repoLens] invalid state JSON: {exc!r}", file=sys.stderr)
            return

        # Felder setzen
        profile = data.get("detail_profile")
        if profile and profile in self.seg_detail.segments:
            try:
                self.seg_detail.selected_index = self.seg_detail.segments.index(profile)
            except ValueError as e:
                # If the profile is not found in segments, just skip setting selected_index.
                print(f"[repoLens] Profile '{profile}' not found in segments: {e}", file=sys.stderr)

        self.ext_field.text = data.get("ext_filter", "")
        self.path_field.text = data.get("path_filter", "")
        self.max_field.text = data.get("max_bytes", "")
        self.split_field.text = data.get("split_mb", "")

        meta_idx = data.get("meta_density_index", 0)
        if 0 <= meta_idx < len(self.seg_meta.segments):
            self.seg_meta.selected_index = meta_idx

        self.plan_only_switch.value = bool(data.get("plan_only", False))
        if getattr(self, "code_only_switch", None) is not None:
            self.code_only_switch.value = bool(data.get("code_only", False))

        self.ignored_repos = set(data.get("ignored_repos", []))

        # Restore Extras
        # Important: only overwrite if key exists, otherwise keep default (which might be True for new features)
        extras_data = data.get("extras", {})
        if extras_data:
            if "health" in extras_data:
                self.extras_config.health = extras_data["health"]
            if "organism_index" in extras_data:
                self.extras_config.organism_index = extras_data["organism_index"]
            if "fleet_panorama" in extras_data:
                self.extras_config.fleet_panorama = extras_data["fleet_panorama"]
            if "delta_reports" in extras_data:
                self.extras_config.delta_reports = extras_data["delta_reports"]
            if "augment_sidecar" in extras_data:
                self.extras_config.augment_sidecar = extras_data["augment_sidecar"]
            if "heatmap" in extras_data:
                self.extras_config.heatmap = extras_data["heatmap"]
            if "json_sidecar" in extras_data:
                self.extras_config.json_sidecar = extras_data["json_sidecar"]

        # Restore Prescan Pool (with migration support)
        self.saved_prescan_selections = deserialize_prescan_pool(data.get("prescan_pool", {}))

        # Update hint text to match restored profile
        self.on_profile_changed(None)

        selected = data.get("selected_repos")
        if selected is not None:
            # Direkt anwenden – auch wenn leer (zum Leeren der Auswahl)
            self._apply_selected_repo_names(selected)

        if sender and console:
            # Kurzes Feedback, aber niemals hart failen
            try:
                console.hud_alert("Config loaded")
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to show HUD alert: {e}\n")

        # Info-Zeile nach dem Wiederherstellen aktualisieren
        self._update_repo_info()


    def _tableview_cell(self, tableview, section, row):
        cell = ui.TableViewCell()
        cell.background_color = "#111111"
        if 0 <= row < len(self.repos):
            cell.text_label.text = self.repos[row]
        cell.text_label.text_color = "white"
        cell.text_label.background_color = "#111111"

        selected_bg = ui.View()
        # gut sichtbarer Selected-Hintergrund
        selected_bg.background_color = "#0050ff"
        cell.selected_background_view = selected_bg
        return cell

    def _get_selected_repos(self, explicit_only: bool = False) -> List[str]:
        tv = self.tv
        rows = tv.selected_rows or []
        if not rows:
            return [] if explicit_only else list(self.repos)
        names: List[str] = []
        for section, row in rows:
            if 0 <= row < len(self.repos):
                names.append(self.repos[row])
        return names

    def _parse_max_bytes(self) -> int:
        txt = (self.max_field.text or "").strip()
        # Leeres Feld → Standard: unbegrenzt (0 = „no limit“)
        if not txt:
            return 0

        # Optional: Eingaben wie "10M", "512K", "1G" akzeptieren
        try:
            val = parse_human_size(txt)
        except Exception:
            val = 0

        # <=0 interpretieren wir bewusst als „kein Limit“
        if val <= 0:
            return 0
        return val

    def _parse_split_size(self) -> int:
        txt = (self.split_field.text or "").strip()
        if not txt:
            return 0
        try:
            # Assume MB if plain number in UI, or allow "1GB"
            if txt.isdigit():
                return int(txt) * 1024 * 1024
            return parse_human_size(txt)
        except Exception:
            return 0

    def merge_pr_schau_bundles(self, ds, items, sheet) -> None:
        selected_indices = ds.selected
        if not selected_indices:
            if console:
                console.hud_alert("No bundles selected", "error")
            return

        # Deterministische Auswahlreihenfolge: sortiere Indices nach Timestamp (desc) der Items
        # Dies ist robuster als das Sortieren der extrahierten Liste
        # Note: We rely on string sorting of 'ts' which is strictly ISO-8601-like (%Y-%m-%dT%H%M%SZ)
        sorted_indices = sorted(selected_indices, key=lambda i: items[i]["ts"], reverse=True)
        selected_items = [items[i] for i in sorted_indices]

        # Zielverzeichnis: merges/
        merges_dir = get_merges_dir(self.hub)
        now_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        out_filename = f"pr-schau-merge_{now_ts}.md"
        out_path = merges_dir / out_filename

        lines = [
            "# PR-Schau Merge Report",
            f"- Generated: {now_ts}",
            f"- Source root: {PR_SCHAU_DIR}",
            f"- Bundles: {len(selected_items)}",
            "",
            "## Included Bundles",
        ]

        # Inhaltsverzeichnis
        for item in selected_items:
            lines.append(f"- {item['display']}")
        lines.append("")

        MAX_CHARS = 40000

        for item in selected_items:
            bdir = item.get("bundle_dir")
            if not bdir: continue

            # Load metadata
            meta = {}
            delta = {}
            try:
                meta_raw, _ = load_pr_schau_bundle(bdir, strict=False, verify_level="none")
                meta = _flatten_meta(meta_raw)
            except Exception:
                pass

            try:
                p_delta = bdir / "delta.json"
                if p_delta.exists():
                    delta = json.loads(p_delta.read_text("utf-8"))
            except Exception:
                pass

            repo = meta.get("repo", item["repo"])
            created = meta.get("created_at", item["ts"])

            summary_str = "n/a"
            if "summary" in delta:
                s = delta["summary"]
                summary_str = f"+{s.get('added',0)} / ~{s.get('changed',0)} / -{s.get('removed',0)}"

            lines.append(f"## {repo} @ {created}")
            # Provenance: Bundle-Pfad relativ zum Hub (falls möglich) oder zu Source Root
            try:
                rel_bundle_path = bdir.relative_to(self.hub)
                lines.append(f"- Bundle dir: `{rel_bundle_path}`")
            except Exception:
                lines.append(f"- Bundle dir: `{bdir.name}`")

            lines.append(f"- **Summary**: {summary_str}")
            if "hub_rel" in meta:
                lines.append(f"- **Path**: `{meta['hub_rel']}`")
            if "old_tree_hint" in meta:
                lines.append(f"- **Base**: `{meta['old_tree_hint']}`")
            if "new_tree_hint" in meta:
                lines.append(f"- **Head**: `{meta['new_tree_hint']}`")
            lines.append("")

            # Review Content (Truncated)
            review_md = item.get("path")
            if review_md and review_md.exists():
                lines.append("### Review Content")
                try:
                    content = review_md.read_text("utf-8", errors="replace")
                    if len(content) > MAX_CHARS:
                        lines.append(f"> **Note**: Content truncated at {MAX_CHARS} characters. Full content in original `review.md`.")
                        content = content[:MAX_CHARS] + "\n\n... [Truncated due to size] ..."
                    lines.append(content)
                except Exception as e:
                    lines.append(f"> Error reading review content: {e}")
            else:
                lines.append("> (No review.md content available)")
            lines.append("")
            lines.append("---")
            lines.append("")

        try:
            out_path.write_text("\n".join(lines), encoding="utf-8")

            # Validierung vor Feedback
            if not out_path.exists() or out_path.stat().st_size == 0:
                raise RuntimeError("Output file empty or missing.")

            msg = f"Merged {len(selected_items)} bundles to {out_filename}"
            if console:
                console.hud_alert("Merge created", "success")
            else:
                print(msg)

            # Optional: Open output if editor available
            if editor:
                editor.open_file(str(out_path))

            # Close sheet on success
            sheet.close()

        except Exception as e:
            if console:
                console.alert("Merge Failed", str(e), "OK")
            else:
                print(f"Merge Failed: {e}")

    def show_pr_schau_browser(self, sender):
        """Zeigt Liste der verfügbaren PR-Schau Bundles mit Multi-Select Workflow."""
        pr_dir = self.hub / PR_SCHAU_DIR

        def _normalize_ts(val: str) -> Optional[str]:
            """Ensure timestamp is strictly %Y-%m-%dT%H%M%SZ."""
            # 0. Safety guard for non-string types (e.g. from JSON)
            if not isinstance(val, str):
                return None
            # 1. Check strict match
            if re.match(r"^\d{4}-\d{2}-\d{2}T\d{6}Z$", val):
                return val
            # 2. Try parsing common formats
            try:
                # Handle Z suffix manually for pre-3.11 compatibility or partial ISO
                clean = val.replace("Z", "+00:00")
                dt = datetime.datetime.fromisoformat(clean)
                # Re-format strict
                return dt.strftime("%Y-%m-%dT%H%M%SZ")
            except ValueError:
                return None

        items = []
        if pr_dir.exists():
            for repo_dir in pr_dir.iterdir():
                if not repo_dir.is_dir(): continue
                repo_name = repo_dir.name

                for ts_dir in repo_dir.iterdir():
                    if not ts_dir.is_dir(): continue

                    # Timestamp Contract: Ensure strictly formatted timestamp folder name
                    # Expected: %Y-%m-%dT%H%M%SZ (e.g. 2025-05-10T123000Z)
                    ts_raw = ts_dir.name
                    ts_sort = _normalize_ts(ts_raw)

                    if not ts_sort:
                        # Attempt fallback from bundle metadata if folder name is invalid
                        try:
                            # Use canonical loader even for fallback checks
                            bj_raw, _ = load_pr_schau_bundle(ts_dir, strict=False, verify_level="none")
                            bj = _flatten_meta(bj_raw)

                            # legacy created_at / v1 generated_at / fallback ts
                            candidates = [bj.get("created_at"), bj.get("generated_at"), bj.get("ts")]
                            ts_source = next((x for x in candidates if x), None)
                            if ts_source:
                                # Normalize the JSON timestamp too
                                ts_sort = _normalize_ts(ts_source)
                        except Exception:
                            pass

                    # If still no valid sort key, use a fallback to ensure list display but minimal priority
                    display_ts = ts_raw
                    if not ts_sort:
                        ts_sort = "0000-00-00T000000Z" # Sorts to bottom in desc
                        display_ts = f"{ts_raw} (invalid ts)"
                    else:
                        display_ts = ts_sort

                    review_md_path = ts_dir / "review.md"
                    bundle_json_path = ts_dir / BUNDLE_FILENAME
                    delta_json_path = ts_dir / "delta.json"

                    # Robustness: Include even if review.md missing, if metadata exists
                    if review_md_path.exists() or bundle_json_path.exists() or delta_json_path.exists():
                        display_text = f"{repo_name} @ {display_ts}"
                        if not review_md_path.exists():
                            display_text += " (no review.md)"

                        items.append({
                            "repo": repo_name,
                            "ts": ts_sort,
                            "path": review_md_path,
                            "bundle_dir": ts_dir,
                            "display": display_text
                        })

        if not items:
            if console:
                console.alert("PR-Schau", "Keine PR-Bundles gefunden.", "OK", hide_cancel_button=True)
            return

        # Sort by timestamp descending
        items.sort(key=lambda x: x["ts"], reverse=True)

        sheet = ui.View()
        sheet.name = "PR-Schau Bundles"
        sheet.background_color = "#111111"
        # Increase size for better overview
        sheet.frame = (0, 0, 600, 700)

        # Button Bar Area
        bar_height = 50

        tv = ui.TableView()
        tv.frame = (0, 0, sheet.width, sheet.height - bar_height)
        tv.flex = "WH"
        tv.background_color = "#111111"
        tv.separator_color = "#333333"
        tv.row_height = 44 # Better touch target

        ds = PRSchauDataSource(items)
        tv.data_source = ds
        tv.delegate = ds

        sheet.add_subview(tv)

        # Bottom Bar
        bar = ui.View()
        bar.frame = (0, sheet.height - bar_height, sheet.width, bar_height)
        bar.flex = "WT"
        bar.background_color = "#222222"
        sheet.add_subview(bar)

        btn_y = 8
        btn_h = 34
        margin = 10

        # Button: Open (Left aligned, Fixed)
        btn_open = ui.Button(title="Open")
        btn_open.frame = (margin, btn_y, 80, btn_h)
        btn_open.flex = ""
        btn_open.background_color = "#333333"
        btn_open.tint_color = "white"
        btn_open.corner_radius = 6

        def action_open(sender):
            row = -1
            # Prioritize last tapped, then first selected
            if ds.last_tapped_row >= 0:
                row = ds.last_tapped_row
            elif ds.selected:
                row = next(iter(ds.selected))

            if row < 0 or row >= len(items):
                _notify("Select a bundle to open", "info")
                return

            # Smart Open: Try review.md -> bundle metadata -> delta.json
            item = items[row]
            candidates = [
                item.get("path"),                   # review.md
                item.get("bundle_dir") / BUNDLE_FILENAME,
                item.get("bundle_dir") / "delta.json"
            ]

            opened = False
            for cand in candidates:
                if cand and isinstance(cand, Path) and cand.exists():
                    path_str = str(cand)

                    # Strategy 1: Editor
                    if editor:
                        try:
                            editor.open_file(path_str)
                            opened = True
                            break
                        except Exception:
                            pass

                    # Strategy 2: Console Quicklook
                    if console:
                        try:
                            console.quicklook(path_str)
                            opened = True
                            break
                        except Exception:
                            pass

                    # Strategy 3: Standard Quicklook module
                    if quicklook:
                        try:
                            quicklook.quicklook(path_str)
                            opened = True
                            break
                        except Exception:
                            pass

                    # Strategy 4: Fallback UI Alert (inform user file exists but can't be viewed)
                    if ui:
                        try:
                            ui.alert("File exists", f"Cannot open: {cand.name}\n(No viewer available)", "OK", hide_cancel_button=True)
                            opened = True # Handled in UI
                            break
                        except Exception:
                            pass

            if not opened:
                _notify("No viewable file found", "error")

        btn_open.action = action_open
        bar.add_subview(btn_open)

        # Button: Close (Right aligned)
        btn_close = ui.Button(title="Close")
        btn_close.frame = (sheet.width - 80 - margin, btn_y, 80, btn_h)
        btn_close.flex = "L"
        btn_close.background_color = "#333333"
        btn_close.tint_color = "white"
        btn_close.corner_radius = 6
        btn_close.action = lambda s: sheet.close()
        bar.add_subview(btn_close)

        # Button: Merge Selected (Middle, Flexible width)
        # Calculate remaining space
        mid_x = 80 + margin * 2
        mid_w = sheet.width - (80 + margin * 2) * 2

        btn_merge = ui.Button(title="Merge selected")
        btn_merge.frame = (mid_x, btn_y, mid_w, btn_h)
        btn_merge.flex = "W"
        btn_merge.background_color = "#8E44AD"
        btn_merge.tint_color = "white"
        btn_merge.corner_radius = 6
        btn_merge.action = lambda s: self.merge_pr_schau_bundles(ds, items, sheet)

        bar.add_subview(btn_merge)

        sheet.present("sheet")

    def run_delta_from_last_import(self, sender) -> None:
        """
        Erzeugt einen Delta-Merge aus dem neuesten Import-Diff im merges-Ordner.
        Nutzt die Delta-Helfer aus repolens-extractor.py (falls verfügbar).
        """
        merges_dir = get_merges_dir(self.hub)
        try:
            candidates = list(merges_dir.glob("*-import-diff-*.md"))
        except Exception as exc:
            print(f"[repoLens] could not scan merges dir: {exc}")
            candidates = []

        if not candidates:
            if console:
                console.alert(
                    "repoLens",
                    "No import diff found.",
                    "OK",
                    hide_cancel_button=True,
                )
            else:
                print("[repoLens] No import diff found.")
            return

        # jüngstes Diff wählen
        try:
            diff_path = max(candidates, key=lambda p: p.stat().st_mtime)
        except Exception as exc:
            if console:
                console.alert(
                    "repoLens",
                    f"Failed to select latest diff: {exc}",
                    "OK",
                    hide_cancel_button=True,
                )
            else:
                print(f"[repoLens] Failed to select latest diff: {exc}")
            return

        name = diff_path.name
        prefix = "-import-diff-"
        if prefix in name:
            repo_name = name.split(prefix, 1)[0]
        else:
            repo_name = name

        repo_root = self.hub / repo_name
        if not repo_root.exists():
            msg = f"Repo root not found for diff {diff_path.name}"
            if console:
                console.alert("repoLens", msg, "OK", hide_cancel_button=True)
            else:
                print(f"[repoLens] {msg}")
            return

        mod = _load_repolens_extractor_module()
        if mod is None or not hasattr(mod, "create_delta_merge_from_diff"):
            msg = "Delta helper (repolens-extractor) not available."
            if console:
                console.alert("repoLens", msg, "OK", hide_cancel_button=True)
            else:
                print(f"[repoLens] {msg}")
            return

        # Execute delta extraction (without generating a legacy report)
        try:
            # We bypass create_delta_merge_from_diff to avoid double-writing.
            # Instead we extract metadata directly from the diff file.
            delta_meta = None
            extract_returned_none = False
            diff_mtime = None

            try:
                diff_mtime = diff_path.stat().st_mtime
            except Exception:
                diff_mtime = None

            if hasattr(mod, "extract_delta_meta_from_diff_file"):
                try:
                    delta_meta = mod.extract_delta_meta_from_diff_file(diff_path)
                    if delta_meta is None:
                        extract_returned_none = True
                except Exception as e:
                    sys.stderr.write(f"[ERROR] Delta extraction failed: {e}\n")

            # Wenn der Extraktor erfolgreich lief, aber kein Delta liefert, kein Fallback zulassen
            if extract_returned_none:
                msg = "Diff enthält keine Delta-Zeilen (keine Änderungen?) – breche ohne Fallback ab."
                if console:
                    console.alert("repoLens", msg, "OK", hide_cancel_button=True)
                else:
                    print(f"[repoLens] {msg}")
                return

            # Fallback nur, wenn der Extraktor nicht verfügbar war oder fehlgeschlagen ist
            if delta_meta is None:
                try:
                    candidate_paths = []
                    delta_from_diff = diff_path.with_suffix(".delta.json")
                    candidate_paths.append(delta_from_diff)
                    try:
                        repo_specific = sorted(
                            merges_dir.glob(f"{repo_name}-import-diff-*.delta.json"),
                            key=lambda p: p.stat().st_mtime,
                            reverse=True,
                        )
                        candidate_paths.extend(repo_specific)
                    except Exception:
                        pass
                    legacy_delta = merges_dir / "delta.json"
                    candidate_paths.append(legacy_delta)

                    for candidate in candidate_paths:
                        if not candidate.exists():
                            continue
                        # Verhindere veraltete Artefakte: nur Dateien akzeptieren, die zeitlich zum Diff passen
                        try:
                            cand_mtime = candidate.stat().st_mtime
                            if diff_mtime is not None and cand_mtime + 1 < diff_mtime:
                                continue
                        except Exception:
                            pass
                        raw = json.loads(candidate.read_text(encoding="utf-8"))
                        if (
                            isinstance(raw, dict)
                            and raw.get("type") == "repolens-delta"
                            and "summary" in raw
                        ):
                            delta_meta = raw
                            break
                except Exception as e:
                    print(f"[repoLens] Failed to read delta metadata: {e}", file=sys.stderr)

            if not delta_meta:
                msg = "Could not extract delta metadata from diff."
                if console:
                    console.alert("repoLens", msg, "OK", hide_cancel_button=True)
                else:
                    print(f"[repoLens] {msg}")
                return

            # Determine extras config consistent with UI
            # We use self.extras_config but enable delta_reports
            extras = ExtrasConfig(
                health=self.extras_config.health,
                organism_index=self.extras_config.organism_index,
                fleet_panorama=self.extras_config.fleet_panorama,
                augment_sidecar=self.extras_config.augment_sidecar,
                heatmap=self.extras_config.heatmap,
                delta_reports=True # Force enable
            )

            # Need to scan repo for write_reports_v2
            # Delta Report Strategy:
            # 1. Scan repo fully (max_bytes=0 => unlimited)
            # 2. Filter file list based on delta_meta (changed + added)
            # 3. Use profile 'max' to ensure full content is included for these files

            summary = scan_repo(repo_root, extensions=None, path_contains=None, max_bytes=0, calculate_md5=True, include_hidden=True)

            # Filter files to include only changed/added
            # Helper to collect paths from delta_meta
            allowed_paths = set()

            # Check for legacy arrays
            if "files_added" in delta_meta and isinstance(delta_meta["files_added"], list):
                allowed_paths.update(delta_meta["files_added"])

            if "files_changed" in delta_meta and isinstance(delta_meta["files_changed"], list):
                for item in delta_meta["files_changed"]:
                    if isinstance(item, dict):
                        path = item.get("path")
                        if path: allowed_paths.add(path)
                    elif isinstance(item, str):
                        allowed_paths.add(item)

            # Check for summary object (repolens-delta schema) if arrays are missing/empty
            # Note: The schema stores lists in top-level usually. If they are missing, we can't filter.
            # If allowed_paths is empty but summary says there are changes, we might have a problem.
            # But assume delta_meta is well-formed from extractor.

            if allowed_paths:
                # Filter the file list in summary
                # Use normalized posix string for comparison
                filtered_files = []
                for f in summary["files"]:
                    if f.rel_path.as_posix() in allowed_paths:
                        filtered_files.append(f)

                summary["files"] = filtered_files
                # Update stats
                summary["total_files"] = len(filtered_files)
                summary["total_bytes"] = sum(f.size for f in filtered_files)

            # Generate merge reports
            # Use 'max' profile to ensure full content for the changed/added files
            # (dev/doc logic might otherwise hide content for doc changes)
            artifacts = write_reports_v2(
                merges_dir,
                self.hub,
                [summary],
                "max",
                "repo",
                0,
                plan_only=False,
                code_only=False,
                debug=False,
                path_filter=None,
                ext_filter=None,
                extras=extras,
                delta_meta=delta_meta,    # << NEW: real delta injected
                generator_info={"name": "repolens", "platform": "ios"},
            )

            # Close files
            out_paths = artifacts.get_all_paths()
            force_close_files(out_paths)

            primary_path = artifacts.get_primary_path()
            msg = (
                f"Delta report generated: {primary_path.name}"
                if primary_path is not None
                else "Delta report generated"
            )
            if console:
                try:
                    console.hud_alert(msg)
                except Exception:
                    console.alert("repoLens", msg, "OK", hide_cancel_button=True)
            else:
                print(f"[repoLens] {msg}")

        except Exception as exc:
            msg = f"Delta merge failed: {exc}"
            if console:
                console.alert("repoLens", msg, "OK", hide_cancel_button=True)
            else:
                print(f"[repoLens] {msg}")
            return

    def show_prescan_sheet(self, sender):
        """
        Shows the Prescan UI (Tree View) for the selected repository.
        Currently limited to single repo selection for simplicity.
        
        ARCHITECTURE:
        - Prescan → Selection Pool (modify only, never triggers merge)
        - Merge → Explicit action from main view via Run Merge button
        - No implicit transition from prescan to merge execution
        """
        selected = self._get_selected_repos()
        if len(selected) != 1:
            if console:
                console.hud_alert("Please select exactly one repo for Prescan.", "error")
            return

        repo_name = selected[0]
        repo_path = self.hub / repo_name

        # We need to run prescan logic. Since we are in Pythonista (local), we call core directly.
        try:
            from merger.lenskit.core.merge import prescan_repo
        except ImportError:
            try:
                from lenskit.core.merge import prescan_repo
            except ImportError:
                _notify("Core merge module not found", "error")
                return

        # Engage Guard
        self._prescan_active = True

        # Show Loading HUD
        if console:
            console.show_activity("Scanning structure...")

        def run_scan_bg():
            try:
                # Run prescan
                data = prescan_repo(repo_path, max_depth=10)
                # Ensure UI update on main thread
                ui.delay(lambda: self._present_prescan_ui(data), 0)
            except Exception as e:
                # Bind exception text before scheduling delayed UI callback;
                # Python clears exception variables after except blocks.
                _err_msg = str(e)
                def err():
                    if console: console.alert("Prescan Failed", _err_msg, "OK", hide_cancel_button=True)
                    # Reset flag on failure
                    self._prescan_active = False
                ui.delay(err, 0)
            finally:
                if console:
                    console.hide_activity()

        # Run in background
        import threading
        t = threading.Thread(target=run_scan_bg)
        t.start()

    def _present_prescan_ui(self, prescan_data):
        """
        Displays the prescan tree in a Sheet.
        Allows selection of files/folders.
        """
        root_node = prescan_data["tree"]
        root_name = prescan_data["root"]

        # Flatten tree for table view (simple indentation approach)
        flat_items = []

        def traverse(node, depth):
            # Item struct: { path, display, type, depth, node_ref }
            name = node["path"].split("/")[-1]
            if node["path"] == ".": name = root_name

            icon = "📁" if node["type"] == "dir" else "📄"
            indent = "  " * depth
            display = f"{indent}{icon} {name}"

            flat_items.append({
                "path": node["path"],
                "display": display,
                "type": node["type"],
                "depth": depth,
                "orig": node,
                "selected": False # Default state
            })

            if node.get("children"):
                # Sort: Dirs first, then files
                dirs = [c for c in node["children"] if c["type"] == "dir"]
                files = [c for c in node["children"] if c["type"] == "file"]

                dirs.sort(key=lambda x: x["path"])
                files.sort(key=lambda x: x["path"])

                for c in dirs + files:
                    traverse(c, depth + 1)

        traverse(root_node, 0)

        # Initially select based on Recommended heuristic
        # Start with None, then run heuristic
        for item in flat_items:
            item["selected"] = False

        # Load existing selection from pool if available
        # This supports the "Append" workflow by initializing with previous state
        existing_pool_entry = self.saved_prescan_selections.get(root_name)

        # Logic:
        # - If pool has entry (dict):
        #   - If raw is None: ALL state - select everything
        #   - If raw is list: Use raw for UI truth (not compressed)
        # - If no pool entry:
        #   - Run Heuristic (Recommended).

        if existing_pool_entry:
            if isinstance(existing_pool_entry, dict):
                raw = existing_pool_entry.get("raw")
                if raw is None:
                    # ALL state - select everything
                    for item in flat_items:
                        item["selected"] = True
                elif isinstance(raw, list):
                    # Partial selection from pool - use raw for UI truth
                    # Normalize paths for consistent matching
                    pool_set = set(normalize_path(p) for p in raw)
                    for item in flat_items:
                        normalized_item_path = normalize_path(item["path"])
                        # Direct match
                        if normalized_item_path in pool_set:
                            item["selected"] = True
                        else:
                            # Check if parent dir is in pool (for compressed paths)
                            parts = normalized_item_path.split('/')
                            for i in range(len(parts)):
                                sub = "/".join(parts[:i+1])
                                if sub in pool_set:
                                    item["selected"] = True
                                    break
            else:
                # Legacy format - shouldn't happen after migration
                # Run heuristic as fallback
                pass
        else:
            # No existing selection -> Heuristic
            # Run heuristic logic (same as prescanRecommended)
            def is_recommended(path_str):
                path = path_str.lower()
                # Critical
                if "readme" in path or path.endswith(".ai-context.yml"):
                    return True
                # Code
                parts = path.split('/')
                if "src" in parts or "contracts" in parts or "docs" in parts:
                    if "test" not in path:
                         return True
                return False

            for item in flat_items:
                if item["type"] == "file":
                    if is_recommended(item["path"]):
                        item["selected"] = True

        # Create Sheet with reliable close handling
        # ARCHITECTURE NOTE: Prescan → Selection Pool (modify only)
        # Merge → Explicit action from main view (never triggered from prescan)
        class PrescanSheet(ui.View):
            """
            Custom View subclass.
            Note: We avoid relying solely on will_close() for critical state reset due to
            potential delegate limitations/bugs in some Pythonista versions.
            State is reset explicitly in action handlers.
            """
            def __init__(self, parent):
                super().__init__()
                self._parent = parent
                self.name = f"Prescan: {root_name}"
                self.background_color = "#111111"
                self.frame = (0, 0, 600, 800)

            def will_close(self):
                # Fallback safety net
                if self._parent._prescan_active:
                     self._parent._prescan_active = False

        sheet = PrescanSheet(self)

        def reset_guard():
            self._prescan_active = False

        # Track selection mode explicitly for better state management
        # This helps prevent crashes when transitioning between ALL/PARTIAL/NONE states
        selection_state = {
            'mode': 'partial'  # 'all', 'partial', or 'none'
        }
        
        # Initialize selection mode based on current selection
        # Check if existing pool entry is in ALL state (both raw and compressed are None)
        is_all = (isinstance(existing_pool_entry, dict) and 
                  existing_pool_entry.get("raw") is None and 
                  existing_pool_entry.get("compressed") is None)
        
        if is_all:
            selection_state['mode'] = 'all'
        elif not any(item["selected"] for item in flat_items):
            selection_state['mode'] = 'none'
        else:
            selection_state['mode'] = 'partial'

        # Header Stats
        stats_lbl = ui.Label(frame=(10, 10, 580, 20))
        stats_lbl.text = f"{prescan_data['file_count']} files • {parse_human_size(str(prescan_data['total_bytes']))} bytes total" # approximate
        stats_lbl.text_color = "gray"
        stats_lbl.font = ("<System>", 12)
        sheet.add_subview(stats_lbl)

        # Buttons: Select All / None / Recommended
        btn_y = 40
        btn_w = 80
        btn_h = 30

        def toggle_all(val):
            for i in flat_items: i["selected"] = val
            # Update selection mode
            if val:
                selection_state['mode'] = 'all'
            else:
                selection_state['mode'] = 'none'
            tv.reload_data()

        btn_all = ui.Button(title="All")
        btn_all.frame = (10, btn_y, btn_w, btn_h)
        btn_all.background_color = "#333333"
        btn_all.tint_color = "white"
        btn_all.corner_radius = 4
        btn_all.action = lambda s: toggle_all(True)
        sheet.add_subview(btn_all)

        btn_none = ui.Button(title="None")
        btn_none.frame = (100, btn_y, btn_w, btn_h)
        btn_none.background_color = "#333333"
        btn_none.tint_color = "white"
        btn_none.corner_radius = 4
        btn_none.action = lambda s: toggle_all(False)
        sheet.add_subview(btn_none)

        # TableView
        tv_y = 80
        tv_h = sheet.height - tv_y - 60 # space for bottom bar
        tv = ui.TableView()
        tv.frame = (0, tv_y, sheet.width, tv_h)
        tv.flex = "WH"
        tv.background_color = "#111111"
        tv.separator_color = "#333333"
        tv.allows_multiple_selection = False # We handle selection manually

        class PrescanDS(object):
            def tableview_number_of_rows(self, tv, section):
                return len(flat_items)

            def tableview_cell_for_row(self, tv, section, row):
                item = flat_items[row]
                cell = ui.TableViewCell()
                cell.text_label.text = item["display"]
                cell.text_label.font = ("<Mono>", 12)
                cell.background_color = "#111111"
                cell.text_label.text_color = "white" if item["type"] == "file" else "#88ccff"

                if item["selected"]:
                    cell.accessory_type = "checkmark"
                else:
                    cell.accessory_type = "none"
                return cell

            def tableview_did_select(self, tv, section, row):
                # Toggle logic
                item = flat_items[row]
                new_state = not item["selected"]
                
                # Handle ALL state transition
                if selection_state['mode'] == 'all' and not new_state:
                    # Deselecting from ALL state - switch to partial selection mode
                    selection_state['mode'] = 'partial'
                
                self._set_selected_recursive(item, new_state)
                
                # Update selection mode after change
                if all(i["selected"] for i in flat_items):
                    selection_state['mode'] = 'all'
                elif not any(i["selected"] for i in flat_items):
                    selection_state['mode'] = 'none'
                else:
                    selection_state['mode'] = 'partial'
                
                tv.reload_data()

            def _set_selected_recursive(self, item, state):
                item["selected"] = state
                # If dir, find children in flat list and toggle
                if item["type"] == "dir":
                    # Naive: scan following items with depth > item.depth
                    # Since it is a flat list from traversal, children are immediately following.
                    idx = flat_items.index(item)
                    for i in range(idx + 1, len(flat_items)):
                        child = flat_items[i]
                        if child["depth"] <= item["depth"]:
                            break
                        child["selected"] = state

        ds = PrescanDS()
        tv.data_source = ds
        tv.delegate = ds
        sheet.add_subview(tv)

        # Bottom Bar: Remove / Cancel / Replace / Append
        bar_y = sheet.height - 50
        
        # Shared pool update logic
        def _pool_update(mode):
            """
            Update the prescan selection pool.
            mode: 'replace', 'append', or 'remove'
            """
            # Create a map for quick lookup of selection status by path
            # Note: We rely on the UI state (flat_items) where possible.
            selection_map = {item["path"]: item["selected"] for item in flat_items}

            # FIX 1: Materialize raw paths correctly (DFS).
            # If a directory is selected, ALL its descendants must be in raw_paths.
            # We cannot rely solely on flat_items["selected"] for files if the user only clicked the folder.
            
            materialized_raw = []
            compressed_paths = []

            def collect_materialized(node):
                path = node["path"]
                # Check selection state from map (populated by UI toggles)
                is_selected = selection_map.get(path, False)

                if is_selected:
                    if node["type"] == "file":
                        materialized_raw.append(path)
                        compressed_paths.append(path)
                    else:
                        # Directory is selected -> fully selected
                        compressed_paths.append(path)
                        # Materialize all descendants for raw truth
                        collect_all_descendants(node)
                else:
                    # Not selected -> descend
                    if node["type"] == "dir" and node.get("children"):
                        for c in node["children"]:
                            collect_materialized(c)

            def collect_all_descendants(node):
                if node["type"] == "file":
                    materialized_raw.append(node["path"])
                elif node.get("children"):
                    for c in node["children"]:
                        collect_all_descendants(c)

            collect_materialized(root_node)

            # Normalize and deduplicate
            raw_paths = sorted(list(set(normalize_path(p) for p in materialized_raw)))
            compressed_paths = sorted(list(set(normalize_path(p) for p in compressed_paths)))
            
            # Handle different modes
            if mode == 'remove':
                # Remove from pool
                if root_name in self.saved_prescan_selections:
                    del self.saved_prescan_selections[root_name]
                self.save_last_state()
                if console:
                    console.hud_alert(f"Removed selection pool for {root_name}", "success", 1.5)
                reset_guard()
                sheet.close()
                return
            
            # Get current selection mode
            current_mode = selection_state['mode']
            
            # Check if we have an existing selection for this repo
            existing = self.saved_prescan_selections.get(root_name)
            
            if mode == 'replace':
                # Replace mode: overwrite existing selection
                if current_mode == 'all':
                    # ALL selected
                    self.saved_prescan_selections[root_name] = {"raw": None, "compressed": None}
                elif current_mode == 'none':
                    # Nothing selected - remove from pool
                    if root_name in self.saved_prescan_selections:
                        del self.saved_prescan_selections[root_name]
                else:
                    # Partial selection - store both raw and compressed
                    if compressed_paths or raw_paths:
                        self.saved_prescan_selections[root_name] = {
                            "raw": raw_paths if raw_paths else None,
                            "compressed": compressed_paths if compressed_paths else None
                        }
                    else:
                        # Empty selection - remove from pool
                        if root_name in self.saved_prescan_selections:
                            del self.saved_prescan_selections[root_name]
                
                self.save_last_state()
                if console:
                    console.hud_alert(f"Replaced selection pool for {root_name}", "success", 1.5)
                
            elif mode == 'append':
                # Append mode: union with existing selection
                if current_mode == 'none':
                    # Nothing selected in current view - no-op with feedback
                    if console:
                        console.hud_alert("No changes: no items selected in append mode", "error", 2.0)
                    return # Don't close dialog
                
                if current_mode == 'all':
                    # ALL selected - ALL overrides everything
                    self.saved_prescan_selections[root_name] = {"raw": None, "compressed": None}
                else:
                    # Partial selection - union raw, then RE-COMPRESS
                    merged_raw = None

                    if existing and isinstance(existing, dict):
                        existing_raw = existing.get("raw")
                        if existing_raw is None:
                            # Existing was ALL. Union(ALL, Partial) = ALL
                            self.saved_prescan_selections[root_name] = {"raw": None, "compressed": None}
                            self.save_last_state()
                            if console: console.hud_alert(f"Appended to selection pool for {root_name}", "success", 1.5)
                            reset_guard()
                            sheet.close()
                            return
                        else:
                            # Union of existing and new raw paths
                            merged_raw = set(existing_raw)
                            if raw_paths:
                                merged_raw.update(raw_paths)
                    else:
                        # No existing -> just new raw
                        merged_raw = set(raw_paths) if raw_paths else None

                    # If we have a merged raw set, re-compress using the tree (Iterative DFS)
                    if merged_raw and len(merged_raw) > 0:
                        new_compressed = []

                        # Build a map for O(1) lookup, ensure normalization
                        raw_set = set(normalize_path(p) for p in merged_raw)

                        # Phase 1: Determine selection status of all nodes (Post-order simulation)
                        # We need to know if a dir is fully selected. Since flat_items is flat,
                        # we can't easily do post-order without recursion.
                        # BUT: flat_items was built via DFS. We can iterate backwards?
                        # No, simpler: Build a tree-like structure or map from the flat items?
                        # Actually, root_node is available and it IS a tree.

                        # Iterative Post-Order to mark 'fully_selected'
                        # We decorate the nodes temporarily or use a map ID->Status

                        node_status = {} # path -> bool (fully selected)

                        # Iterative Post-Order Traversal using 2 stacks
                        stack1 = [root_node]
                        stack2 = []
                        while stack1:
                            node = stack1.pop()
                            stack2.append(node)
                            if node.get("children"):
                                for c in node["children"]:
                                    stack1.append(c)

                        # Process stack2 (children before parents)
                        while stack2:
                            node = stack2.pop()
                            path = normalize_path(node["path"])

                            if node["type"] == "file":
                                node_status[path] = path in raw_set
                            else: # dir
                                children = node.get("children", [])
                                if not children:
                                    node_status[path] = False # Empty dir not selected
                                else:
                                    # All children must be fully selected
                                    all_selected = True
                                    for c in children:
                                        c_path = normalize_path(c["path"])
                                        if not node_status.get(c_path, False):
                                            all_selected = False
                                            break
                                    node_status[path] = all_selected

                        # Phase 2: Collect compressed paths (Pre-order)
                        # If a node is fully selected, add it and skip children. Else descend.
                        stack = [root_node]
                        while stack:
                            node = stack.pop()
                            path = normalize_path(node["path"])

                            if node_status.get(path, False):
                                # Fully selected (Dir or File)
                                new_compressed.append(path)
                                # Do NOT push children
                            else:
                                # Not fully selected. If dir, push children to check them.
                                # Push in reverse order to maintain order when popping
                                if node.get("children"):
                                    for i in range(len(node["children"]) - 1, -1, -1):
                                        stack.append(node["children"][i])
                                elif node["type"] == "file":
                                    # File not selected? Then don't include.
                                    # (Should be covered by node_status check above, but logic:
                                    # if file is false, we do nothing)
                                    pass

                        self.saved_prescan_selections[root_name] = {
                            "raw": sorted(list(raw_set)),
                            "compressed": [normalize_path(p) for p in new_compressed]
                        }
                    else:
                        # Empty result -> remove
                        if root_name in self.saved_prescan_selections:
                            del self.saved_prescan_selections[root_name]
                
                self.save_last_state()
                if console:
                    console.hud_alert(f"Appended to selection pool for {root_name}", "success", 1.5)
            
            reset_guard()
            sheet.close()
            # No auto-merge!
        
        # Remove button (left side)
        btn_remove = ui.Button(title="Remove")
        btn_remove.frame = (10, bar_y, 80, 40)
        btn_remove.flex = "RT" # Right margin flex, Top margin flex
        btn_remove.background_color = "#ff3b30"
        btn_remove.tint_color = "white"
        btn_remove.corner_radius = 6
        btn_remove.action = lambda s: _pool_update('remove')
        sheet.add_subview(btn_remove)
        
        # Cancel button (right side)
        btn_cancel = ui.Button(title="Cancel")
        btn_cancel.frame = (sheet.width - 310, bar_y, 70, 40)
        btn_cancel.flex = "LT" # Left margin flex, Top margin flex
        btn_cancel.background_color = "#444444"
        btn_cancel.tint_color = "white"
        btn_cancel.corner_radius = 6
        btn_cancel.action = lambda s: (reset_guard(), sheet.close())
        sheet.add_subview(btn_cancel)
        
        # Replace button (right side)
        # "Store to Pool (Replace)" - abbreviated for mobile UI if needed, but clarity is prioritized
        btn_replace = ui.Button(title="Store (Replace)")
        btn_replace.frame = (sheet.width - 250, bar_y, 120, 40)
        btn_replace.flex = "LT" # Left margin flex, Top margin flex
        btn_replace.background_color = "#007aff"
        btn_replace.tint_color = "white"
        btn_replace.corner_radius = 6
        btn_replace.action = lambda s: _pool_update('replace')
        sheet.add_subview(btn_replace)
        
        # Append button (right side)
        # "Store to Pool (Append)"
        btn_append = ui.Button(title="Store (Append)")
        btn_append.frame = (sheet.width - 120, bar_y, 110, 40)
        btn_append.flex = "LT" # Left margin flex, Top margin flex
        btn_append.background_color = "#34c759"
        btn_append.tint_color = "white"
        btn_append.corner_radius = 6
        btn_append.action = lambda s: _pool_update('append')
        sheet.add_subview(btn_append)

        sheet.present("sheet")


    def show_pool_viewer(self, sender):
        """Shows the current Selection Pool content."""
        pool = self.saved_prescan_selections

        sheet = ui.View()
        sheet.name = "Selection Pool"
        sheet.background_color = "#111111"
        sheet.frame = (0, 0, 500, 600)

        if not pool:
            lbl = ui.Label(frame=(0, 0, 500, 600))
            lbl.text = "Pool is empty."
            lbl.alignment = ui.ALIGN_CENTER
            lbl.text_color = "gray"
            sheet.add_subview(lbl)
        else:
            tv = ui.TableView()
            tv.frame = (0, 0, 500, 540)
            tv.flex = "WH"
            tv.background_color = "#111111"
            tv.separator_color = "#333333"

            # Helper to format info
            def format_pool_info(data):
                if not data or not isinstance(data, dict):
                    return "Invalid state"

                # Check for ALL state (both None)
                raw = data.get("raw")
                compressed = data.get("compressed")

                if raw is None and compressed is None:
                    return "ALL"

                # Partial state
                raw_count = len(raw) if raw else 0
                compressed_count = len(compressed) if compressed else 0
                return f"Partial: {raw_count} files / {compressed_count} rules"

            # Convert pool to list
            items = []
            for repo, data in pool.items():
                info = format_pool_info(data)
                items.append({"repo": repo, "info": info})

            items.sort(key=lambda x: x["repo"])

            class PoolDS(object):
                def __init__(self, parent_ui):
                    self.parent = parent_ui

                def tableview_number_of_rows(self, tv, section):
                    return len(items)

                def tableview_cell_for_row(self, tv, section, row):
                    item = items[row]
                    cell = ui.TableViewCell('value1')
                    cell.text_label.text = item["repo"]
                    cell.detail_text_label.text = item["info"]
                    cell.text_label.text_color = "white"
                    cell.detail_text_label.text_color = "#888888"
                    cell.background_color = "#111111"
                    cell.accessory_type = 'detail_button'
                    return cell

                def tableview_accessory_button_tapped(self, tv, section, row):
                    self.show_inspector(row)

                def tableview_did_select(self, tv, section, row):
                    self.show_inspector(row)

                def show_inspector(self, row):
                    item = items[row]
                    repo = item["repo"]
                    entry = pool.get(repo)

                    if not entry or not isinstance(entry, dict):
                        return

                    raw = entry.get("raw")
                    compressed = entry.get("compressed")

                    msg = f"Repo: {repo}\n\n"

                    if raw is None and compressed is None:
                        msg += "State: ALL files included."
                    else:
                        r_count = len(raw) if raw else 0
                        c_count = len(compressed) if compressed else 0
                        msg += f"State: Partial\nFiles: {r_count}\nRules: {c_count}\n\n"

                        if compressed:
                            msg += "Rules (Compressed):\n"
                            # Limit display
                            display_rules = compressed[:15]
                            for r in display_rules:
                                msg += f"- {r}\n"
                            if len(compressed) > 15:
                                msg += f"... and {len(compressed)-15} more"

                    if console:
                        console.alert("Pool Details", msg, "OK", hide_cancel_button=True)
                    elif ui:
                        ui.alert("Pool Details", msg, "OK")

                def tableview_can_edit(self, tv, section, row):
                    return True

                def tableview_delete(self, tv, section, row):
                    repo = items[row]["repo"]
                    if repo in pool:
                        del pool[repo]
                        # Persist immediately using parent reference
                        self.parent.save_last_state()
                        self.parent._update_repo_info()

                    items.pop(row)
                    tv.delete_rows([row])

            ds = PoolDS(self)
            tv.data_source = ds
            tv.delegate = ds
            sheet.add_subview(tv)

            # Bottom Bar
            bar = ui.View(frame=(0, 540, 500, 60))
            bar.flex = "WT"
            bar.background_color = "#222222"

            btn_clear = ui.Button(title="Clear Pool")
            btn_clear.frame = (10, 10, 100, 40)
            btn_clear.background_color = "#ff3b30"
            btn_clear.tint_color = "white"
            btn_clear.corner_radius = 6
            def clear_action(sender):
                pool.clear()
                self.save_last_state()
                self._update_repo_info()
                sheet.close()
                if console: console.hud_alert("Pool cleared")
            btn_clear.action = clear_action
            bar.add_subview(btn_clear)

            sheet.add_subview(bar)

        sheet.present("sheet")

    def _run_merge_form_reset_after_success_safe(self) -> None:
        """Safely reset form after success, with error handling and logging."""
        try:
            self.reset_merge_form_to_defaults_after_success()
        except Exception as exc:
            print(
                f"[repolens] Warning: failed to reset merge form after success: {exc}",
                file=sys.stderr,
            )

    def schedule_merge_form_reset_after_success(self) -> None:
        """Schedule form reset on main thread (UI thread) if possible."""
        if ui is not None and hasattr(ui, "delay"):
            ui.delay(self._run_merge_form_reset_after_success_safe, 0.0)
        else:
            self._run_merge_form_reset_after_success_safe()

    def reset_merge_form_to_defaults_after_success(self) -> None:
        """Reset only merge-related transient UI state after a successful merge run."""
        pool = getattr(self, "saved_prescan_selections", None)
        if pool is None:
            self.saved_prescan_selections = {}
        else:
            pool.clear()

        try:
            if getattr(self, "tv", None) is not None:
                self.tv.selected_rows = []
                if hasattr(self.tv, "reload_data"):
                    self.tv.reload_data()
        except Exception as exc:
            print(
                f"[repolens] Warning: failed to reset table view selection: {exc}",
                file=sys.stderr,
            )

        if getattr(self, "ext_field", None) is not None:
            self.ext_field.text = ""
        if getattr(self, "path_field", None) is not None:
            self.path_field.text = ""

        if getattr(self, "max_field", None) is not None:
            self.max_field.text = "" if DEFAULT_MAX_FILE_BYTES <= 0 else str(DEFAULT_MAX_FILE_BYTES)

        if getattr(self, "split_field", None) is not None:
            split_text = ""
            if DEFAULT_SPLIT_SIZE and str(DEFAULT_SPLIT_SIZE).strip() not in ("", "0"):
                raw = str(DEFAULT_SPLIT_SIZE).strip()
                if raw.isdigit():
                    split_text = raw
                else:
                    try:
                        mb = int(round(parse_human_size(raw) / (1024 * 1024)))
                        split_text = str(mb) if mb > 0 else ""
                    except Exception:
                        split_text = raw
            self.split_field.text = split_text

        if getattr(self, "seg_detail", None) is not None:
            try:
                self.seg_detail.selected_index = self.seg_detail.segments.index(DEFAULT_LEVEL)
            except Exception:
                self.seg_detail.selected_index = 0
            if hasattr(self, "on_profile_changed"):
                self.on_profile_changed(None)

        if getattr(self, "seg_mode", None) is not None:
            self.seg_mode.selected_index = 1 if DEFAULT_MODE == "pro-repo" else 0

        if getattr(self, "seg_meta", None) is not None:
            try:
                self.seg_meta.selected_index = self.seg_meta.segments.index(DEFAULT_META_DENSITY)
            except Exception:
                self.seg_meta.selected_index = 0

        if getattr(self, "plan_only_switch", None) is not None:
            self.plan_only_switch.value = False
        if getattr(self, "code_only_switch", None) is not None:
            self.code_only_switch.value = False

        extras_defaults, _ = ExtrasConfig.from_csv(DEFAULT_EXTRAS)
        self.extras_config = extras_defaults

        self._update_repo_info()
        self.save_last_state()

    def run_merge(self, sender) -> None:
        """
        UI-Handler: niemals schwere Arbeit im Main-Thread ausführen,
        sonst wirkt Pythonista "eingefroren" – besonders bei Multi-Repo.
        """
        if getattr(self, "_prescan_active", False):
            if console:
                console.hud_alert("Prescan active - merge blocked", "error")
            return

        # Snapshot UI state on main thread to avoid thread-safety issues in background
        self._pending_plan_only = self.plan_only_switch.value
        # Use getattr for code_only just in case (legacy robustness)
        self._pending_code_only = bool(getattr(self, "code_only_switch", None) and self.code_only_switch.value)

        try:
            import ui as _ui
            in_bg = getattr(_ui, "in_background", None)
        except Exception:
            in_bg = None

        if in_bg:
            in_bg(self._run_merge_safe)()
        else:
            # Fallback: wenigstens nicht crashen – aber UI kann dann weiterhin blocken.
            self._run_merge_safe()

    def _run_merge_safe(self) -> None:
        try:
            # Aktuellen Zustand merken
            self.save_last_state()
            self._run_merge_inner()
        except Exception as e:
            traceback.print_exc()

            # Use specific messaging for validation errors if possible
            if "ValidationException" in type(e).__name__ or "Structure Violation" in str(e):
                msg = f"Validation Error: {e}"
            else:
                msg = f"Error: {e}"

            if console:
                console.alert("repoLens", msg, "OK", hide_cancel_button=True)
            else:
                print(msg, file=sys.stderr)
        finally:
            # Cleanup snapshotted state to prevent stale values in future runs
            if hasattr(self, "_pending_plan_only"):
                del self._pending_plan_only
            if hasattr(self, "_pending_code_only"):
                del self._pending_code_only

    def _run_merge_inner(self) -> None:
        # 1. Determine Selection Strategy (Explicit vs Pool vs All)
        tv = self.tv
        rows = tv.selected_rows or []

        selected_repos: List[str] = []
        selection_source = "default(all)"

        # Build normalized maps once (avoid N^2 drift pain)
        repo_norm_map = {}
        for r in self.repos:
            norm = normalize_repo_id(r)
            if norm in repo_norm_map:
                # Collision detected
                msg = f"Repo collision: '{r}' and '{repo_norm_map[norm]}' normalize to same ID '{norm}'."
                print(f"[repoLens] WARNING: {msg}", file=sys.stderr)
            else:
                repo_norm_map[norm] = r

        pool_raw = getattr(self, "saved_prescan_selections", None) or {}
        pool_norm = {}
        if isinstance(pool_raw, dict):
            for k, v in pool_raw.items():
                n_key = normalize_repo_id(k)
                if n_key: # Ignore empty keys
                    if n_key in pool_norm:
                        print(f"[repoLens] WARNING: Pool key collision for '{n_key}' (overwriting).", file=sys.stderr)
                    pool_norm[n_key] = v

        # Pool repos that actually exist in current hub
        pool_active_repos = sorted(list({repo_norm_map[nk] for nk in pool_norm.keys() if nk in repo_norm_map}))

        if rows:
            # Explicit UI selection
            selection_source = "explicit"
            for section, row in rows:
                if 0 <= row < len(self.repos):
                    selected_repos.append(self.repos[row])
        elif pool_active_repos:
            # Implicit Pool selection
            selection_source = "pool"
            selected_repos = pool_active_repos
        else:
            # Default All
            selection_source = "default(all)"
            selected_repos = list(self.repos)

        # Deduplicate and Sort
        selected_repos = sorted(list(set(selected_repos)))

        if not selected_repos:
            if console:
                console.alert("repoLens", "No repos selected or found in pool.", "OK", hide_cancel_button=True)
            return

        ext_text = (self.ext_field.text or "").strip()
        extensions = _normalize_ext_list(ext_text)

        path_contains = (self.path_field.text or "").strip() or None

        detail_idx = self.seg_detail.selected_index
        detail = ["overview", "summary", "dev", "max"][detail_idx]

        mode_idx = self.seg_mode.selected_index
        mode = ["gesamt", "pro-repo"][mode_idx]

        meta_idx = self.seg_meta.selected_index
        meta_density = self.seg_meta.segments[meta_idx]

        max_bytes = self._parse_max_bytes()
        split_size = self._parse_split_size()

        # Use snapshotted values from main thread if available (thread-safe), else fallback
        if hasattr(self, "_pending_plan_only"):
            plan_only = self._pending_plan_only
        else:
            plan_switch = getattr(self, "plan_only_switch", None)
            plan_only = bool(plan_switch and plan_switch.value)

        if hasattr(self, "_pending_code_only"):
            code_only = self._pending_code_only
        else:
            code_switch = getattr(self, "code_only_switch", None)
            code_only = bool(code_switch and code_switch.value)

        # Mutual exclusion: plan_only wins to avoid ambiguous semantics.
        if plan_only and code_only:
            code_only = False

        # Helper to get include_paths from pool with normalized O(1) lookup
        def get_pool_include_paths(repo_name):
            entry = pool_norm.get(normalize_repo_id(repo_name))
            return resolve_pool_include_paths(entry)

        # Calculate Stats for UX
        total_paths = 0
        repos_with_filters = 0
        for name in selected_repos:
            paths = get_pool_include_paths(name)
            if paths is not None:
                if isinstance(paths, list):
                    total_paths += len(paths)
                repos_with_filters += 1

        # HUD / Log Feedback
        pool_keys_total = len(pool_norm) if isinstance(pool_norm, dict) else 0
        pool_keys_matched = len(pool_active_repos)

        msg = f"Selection: {selection_source.upper()} ({len(selected_repos)} repos)"
        if selection_source == "pool":
            msg += f" / pool matched {pool_keys_matched}/{pool_keys_total}"

        if repos_with_filters > 0:
            if selection_source == "pool":
                msg += f" / {total_paths} paths"
            else:
                msg += f" / {total_paths} paths from pool"

        if console:
            console.hud_alert(msg, "info", 1.5)
        else:
            print(f"[repoLens] {msg}")

        # Check for restrictive pool entries to decide on execution strategy
        has_restrictive = False
        for name in selected_repos:
            paths = get_pool_include_paths(name)
            if paths is not None and isinstance(paths, list) and len(paths) > 0:
                has_restrictive = True
                break

        merges_dir = get_merges_dir(self.hub)
        all_out_paths = []

        # Execution Strategy
        # If restrictive pool entries exist, we must split execution per repo to ensure
        # correct include_paths are respected and not mixed with global filters.
        # This matches WebUI "force pro-repo" logic.

        execution_list = []
        if has_restrictive:
            # Force sequential processing per repo
            for name in selected_repos:
                execution_list.append([name])
            if console:
                console.hud_alert("Pool active: Splitting jobs per repo")
        else:
            # Standard batch processing (all selected together)
            execution_list.append(selected_repos)

        for b_idx, batch_repos in enumerate(execution_list, start=1):
            summaries = []

            # Scan phase for this batch
            for i, name in enumerate(batch_repos, start=1):
                root = self.hub / name
                if not root.is_dir():
                    continue

                # Feedback
                if console:
                    try:
                        console.hud_alert(f"Scanning {name} ({i}/{len(batch_repos)})", duration=0.6)
                    except Exception:
                        pass
                try:
                    import ui as _ui
                    _ui.delay(lambda: None, 0.0)
                except Exception:
                    pass

                # Resolve paths
                use_include_paths = get_pool_include_paths(name)

                # If we are in a restrictive split-job scenario, and this repo has NO pool entry,
                # it uses global defaults (None). If it HAS an entry, it uses that.
                # scan_repo handles include_paths=None as "scan all".

                summary = scan_repo(root, extensions or None, path_contains, max_bytes, include_paths=use_include_paths, calculate_md5=True, include_hidden=True)
                summaries.append(summary)

            if not summaries:
                continue

            # Delta Logic Injection (Batch-aware)
            delta_meta = None
            if self.extras_config.delta_reports and len(summaries) == 1:
                repo_name = summaries[0]["name"]
                try:
                    mod = _load_repolens_extractor_module()
                    if mod and hasattr(mod, "find_latest_diff_for_repo") and hasattr(mod, "extract_delta_meta_from_diff_file"):
                        diff_path = mod.find_latest_diff_for_repo(merges_dir, repo_name)
                        if diff_path:
                            delta_meta = mod.extract_delta_meta_from_diff_file(diff_path)
                except Exception as e:
                    print(f"[repoLens] Warning: Could not extract delta metadata: {e}", file=sys.stderr)

            # Generate Report for this batch
            # If splitting jobs, we likely want "pro-repo" mode for the output to be named correctly,
            # or if it was "gesamt" but forced split, we get one file per repo anyway.
            # We preserve the user's requested mode unless we forced a split, in which case effectively it behaves like pro-repo
            # but write_reports_v2 needs to know how to name it.
            # If has_restrictive is True, we are iterating 1-by-1. calling write_reports_v2 with 1 summary.
            # Mode "gesamt" with 1 summary produces 1 file. Mode "pro-repo" with 1 summary produces 1 file.
            # So passing the user's `mode` is fine.

            # However, if we forced split, we should probably ensure `path_filter` passed to write_reports
            # doesn't confuse the header if we are using specific include_paths.
            # But `write_reports_v2` uses `path_filter` just for metadata display usually.
            # We pass it through.

            artifacts = write_reports_v2(
                merges_dir,
                self.hub,
                summaries,
                detail,
                mode,
                max_bytes,
                plan_only,
                code_only,
                split_size,
                debug=False,
                path_filter=path_contains,
                ext_filter=extensions or None,
                extras=self.extras_config,
                delta_meta=delta_meta,
                meta_density=meta_density,
                generator_info={"name": "repolens", "platform": "ios"},
            )

            all_out_paths.extend(artifacts.get_all_paths())

            # Force close intermediate files
            force_close_files(artifacts.get_all_paths())

        if not all_out_paths:
            if console:
                console.alert("repoLens", "No report generated.", "OK", hide_cancel_button=True)
            else:
                print("No report generated.")
            return

        # Generate Bundle Index if multiple artifacts (Post-Step)
        if len(all_out_paths) > 1:
            try:
                now_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
                bundle_path = merges_dir / f"bundle-merge_{now_ts}.md"

                # Identify restrictive repos for metadata
                restrictive_repos = []
                for name in selected_repos:
                    paths = get_pool_include_paths(name)
                    if paths is not None and isinstance(paths, list) and len(paths) > 0:
                        restrictive_repos.append(name)

                # Dynamic split_mode based on actual execution logic
                is_split_mode = has_restrictive

                lines = [
                    "---",
                    "pool_status:",
                    f"  restrictive_repos: {json.dumps(restrictive_repos)}",
                    f"  split_mode: {str(is_split_mode).lower()}",
                    "---",
                    "# Bundle Merge Report",
                    f"- Generated: {now_ts}",
                    f"- Parts: {len(all_out_paths)}",
                    "",
                    "## Index",
                ]

                for p in all_out_paths:
                    lines.append(f"- [{p.name}]({p.name})")

                bundle_path.write_text("\n".join(lines), encoding="utf-8")
                # Prepend to be the primary result
                all_out_paths.insert(0, bundle_path)
            except Exception as e:
                print(f"Failed to create bundle index: {e}", file=sys.stderr)

        # Summary Feedback
        count = len(all_out_paths)
        primary = _pick_primary_artifact(all_out_paths)

        # Enforce bundle as primary if present
        for p in all_out_paths:
            if "bundle-merge" in p.name:
                primary = p
                break

        if count == 1 and primary:
            msg = f"Merge generated: {primary.name}"
        elif primary and count > 1:
            msg = f"Merge generated: {primary.name} (+{count-1} parts)"
        else:
            msg = f"Generated {count} artifacts"

        if console:
            try:
                console.hud_alert(msg, "success", 1.5)
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to show HUD alert (falling back to alert): {e}\n")
                console.alert("repoLens", msg, "OK", hide_cancel_button=True)
        else:
            print(f"repoLens: {msg}")
            for p in all_out_paths:
                print(f"  - {p.name}")

        if all_out_paths:
            self.schedule_merge_form_reset_after_success()


# --- CLI Mode ---

def _is_headless_requested() -> bool:
    # Headless wenn:
    # 1) --headless Flag, oder
    # 2) REPOLENS_HEADLESS=1 in der Umgebung, oder
    # 3) ui-Framework nicht verfügbar
    return ("--headless" in sys.argv) or (os.environ.get("REPOLENS_HEADLESS") == "1") or (ui is None)

def main_cli():
    import argparse
    parser = argparse.ArgumentParser(description="repoLens CLI")
    parser.add_argument("paths", nargs="*", help="Repositories to merge")
    parser.add_argument("--hub", help="Base directory (repolens-hub)")
    parser.add_argument("--level", choices=["overview", "summary", "dev", "max"], default=DEFAULT_LEVEL)
    parser.add_argument("--mode", choices=["gesamt", "pro-repo"], default=DEFAULT_MODE)
    # 0 = unbegrenzt pro Datei
    parser.add_argument(
        "--max-bytes",
        type=str,
        default=str(DEFAULT_MAX_FILE_BYTES),
        help="Max bytes per file (e.g. 5MB, 500K, or 0 for unlimited)",
    )
    # Default: ab 25 MB wird gesplittet, aber kein Gesamtlimit – es werden
    # beliebig viele Parts erzeugt.
    parser.add_argument("--split-size", help="Split output into chunks (e.g. 50MB, 1GB)", default=DEFAULT_SPLIT_SIZE)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--code-only", action="store_true", help="Include only code/test/config/contract categories")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument("--headless", action="store_true", help="Force headless (no Pythonista UI/editor)")
    parser.add_argument(
        "--extras",
        help="Comma-separated list of extras (health,organism_index,fleet_panorama,delta_reports,augment_sidecar,json_sidecar,heatmap; alias: ai_heatmap) or 'none'",
        default=DEFAULT_EXTRAS,
    )
    parser.add_argument("--extensions", help="Comma-separated list of extensions (e.g. .md,.py) to include", default=None)
    parser.add_argument("--path-filter", help="Path substring to include (e.g. docs/)", default=None)
    parser.add_argument("--json-sidecar", action="store_true", help="Generate JSON sidecar file alongside markdown report")
    parser.add_argument("--meta-density", choices=["min", "standard", "full", "auto"], default="auto", help="Control metadata verbosity")
    parser.add_argument("--output-mode", choices=["archive", "retrieval", "dual"], default="dual", help="Output mode: archive (MD only), retrieval (Chunk Index), or dual (both)")
    parser.add_argument("--redact-secrets", action="store_true", help="Enable heuristic secret redaction")

    args = parser.parse_args()

    try:
        hub = detect_hub_dir(SCRIPT_PATH, args.hub)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    sources = []
    if args.paths:
        for p in args.paths:
            path = Path(p)
            if not path.exists():
                path = hub / p
            if path.exists() and path.is_dir():
                sources.append(path)
            else:
                print(f"Warning: {path} not found.")
    else:
        repos = find_repos_in_hub(hub)
        for r in repos:
            sources.append(hub / r)

    if not sources:
        cwd = Path.cwd()
        print(f"No sources in hub ({hub}). Scanning current directory: {cwd}")
        sources.append(cwd)

    print(f"Hub: {hub}")
    print(f"Sources: {[s.name for s in sources]}")

    max_bytes = parse_human_size(str(args.max_bytes))
    if max_bytes < 0:
        max_bytes = 0

    ext_list = _normalize_ext_list(args.extensions) if args.extensions else None
    path_filter = args.path_filter

    summaries = []
    for src in sources:
        print(f"Scanning {src.name}...")
        summary = scan_repo(src, ext_list, path_filter, max_bytes, calculate_md5=True, include_hidden=True)
        summaries.append(summary)

    # Default: ab 25 MB wird gesplittet, aber kein Gesamtlimit – es werden
    # beliebig viele Parts erzeugt.
    split_size = 0
    if args.split_size:
        split_size = parse_human_size(args.split_size)
        print(f"Splitting at {split_size} bytes")

    extras_config, warnings = ExtrasConfig.from_csv(args.extras)
    for w in warnings:
        print(f"Warning: {w}")

    # Handle --json-sidecar flag
    if args.json_sidecar:
        extras_config.json_sidecar = True

    merges_dir = get_merges_dir(hub)

    # Try to extract delta_meta if delta_reports is enabled
    delta_meta = None
    if extras_config.delta_reports and summaries and len(summaries) == 1:
        # Only try to find delta for single-repo merges
        repo_name = summaries[0]["name"]
        try:
            mod = _load_repolens_extractor_module()
            if mod and hasattr(mod, "find_latest_diff_for_repo") and hasattr(mod, "extract_delta_meta_from_diff_file"):
                diff_path = mod.find_latest_diff_for_repo(merges_dir, repo_name)
                if diff_path:
                    delta_meta = mod.extract_delta_meta_from_diff_file(diff_path)
                    if delta_meta and args.debug:
                        print(f"Delta metadata extracted from {diff_path.name}")
        except Exception as e:
            if args.debug:
                print(f"Warning: Could not extract delta metadata: {e}")

    artifacts = write_reports_v2(
        merges_dir,
        hub,
        summaries,
        args.level,
        args.mode,
        max_bytes,
        args.plan_only,
        args.code_only,
        split_size,
        debug=args.debug,
        path_filter=path_filter,
        ext_filter=ext_list,
        extras=extras_config,
        delta_meta=delta_meta,
        meta_density=args.meta_density,
        output_mode=args.output_mode,
        redact_secrets=args.redact_secrets,
        generator_info={"name": "repolens", "platform": "cli"},
    )

    out_paths = artifacts.get_all_paths()
    print(f"Generated {len(out_paths)} report(s):")
    for p in out_paths:
        print(f"  - {p}")


def main():
    # UI nur verwenden, wenn wir NICHT als App-Extension laufen und NICHT headless requested ist
    use_ui = (
        ui is not None
        and not _is_headless_requested()
        and (appex is None or not appex.is_running_extension())
    )

    if use_ui:
        try:
            hub = detect_hub_dir(SCRIPT_PATH)
            return run_ui(hub)
        except Exception as e:
            # Fallback auf CLI (headless), falls UI trotz ui-Import nicht verfügbar ist
            if console:
                try:
                    console.alert(
                        "repoLens",
                        f"UI not available, falling back to CLI. ({e})",
                        "OK",
                        hide_cancel_button=True,
                    )
                except Exception:
                    pass
            else:
                print(
                    f"repoLens: UI not available, falling back to CLI. ({e})",
                    file=sys.stderr,
                )
            main_cli()
    else:
        main_cli()

if __name__ == "__main__":
    main()
