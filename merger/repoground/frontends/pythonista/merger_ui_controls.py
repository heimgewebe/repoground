# -*- coding: utf-8 -*-
"""merger ui controls.py

Extracted from build.MergerUI for REPOGROUND-LEGACY-RECONCILIATION-V1-T004.
Behavior is unchanged; methods remain bound via Mixin inheritance.
"""
from __future__ import annotations

from typing import List

BUILD_GLOBAL_NAMES = (
    "PROFILE_DESCRIPTIONS",
    "PROFILE_PRESETS",
    "_clear_active_merger_view",
    "_dismiss_view_best_effort",
    "parse_human_size",
    "sys",
    "ui",
)


class MergerUIControlsMixin:
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
        try:
            # dismiss() ist bei präsentierten Views zuverlässiger als close()
            _dismiss_view_best_effort(self.view)
        except Exception as e:
            # im Zweifel lieber still scheitern, statt iOS-Alert zu nerven, aber loggen
            sys.stderr.write(f"Warning: Failed to close view: {e}\n")
        finally:
            _clear_active_merger_view(self.view)

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
