# -*- coding: utf-8 -*-
"""merger ui init.py

Extracted from build.MergerUI for REPOGROUND-LEGACY-RECONCILIATION-V1-T004.
Behavior is unchanged; methods remain bound via Mixin inheritance.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

BUILD_GLOBAL_NAMES = (
    "DEFAULT_EXTRAS",
    "DEFAULT_LEVEL",
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MODE",
    "DEFAULT_SPLIT_SIZE",
    "ExtrasConfig",
    "LAST_STATE_FILENAME",
    "TF_BORDER_NONE",
    "_load_repoground_extractor_module",
    "_notify",
    "find_repos_in_hub",
    "parse_human_size",
    "sys",
    "ui",
)


class MergerUIInitMixin:
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
            mod = _load_repoground_extractor_module()
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

        # --- Pre-pull Switch ---
        pre_pull_label = ui.Label()
        pre_pull_label.text = "Pre-pull:"
        pre_pull_label.text_color = "white"
        pre_pull_label.background_color = "#111111"
        pre_pull_label.frame = (10, cy, 120, 22)
        bottom_container.add_subview(pre_pull_label)

        pre_pull_switch = ui.Switch()
        pre_pull_switch.frame = (130, cy - 2, 60, 32)
        pre_pull_switch.flex = "W"
        pre_pull_switch.value = True
        bottom_container.add_subview(pre_pull_switch)
        self.pre_pull_switch = pre_pull_switch

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
