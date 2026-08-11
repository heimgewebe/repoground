# -*- coding: utf-8 -*-
"""merger ui state.py

Extracted from build.MergerUI for REPOGROUND-LEGACY-RECONCILIATION-V1-T004.
Behavior is unchanged; methods remain bound via Mixin inheritance.
"""
from __future__ import annotations

from typing import Any, Dict

BUILD_GLOBAL_NAMES = (
    "console",
    "deserialize_prescan_pool",
    "json",
    "sys",
)

_RESTORED_EXTRAS = (
    "health",
    "organism_index",
    "fleet_panorama",
    "delta_reports",
    "augment_sidecar",
    "heatmap",
    "json_sidecar",
    "language_structure",
)


def _restore_extras(extras_config, extras_data):
    for key in _RESTORED_EXTRAS:
        if key in extras_data:
            setattr(extras_config, key, extras_data[key])


class MergerUIStateMixin:
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
                print(f"[RepoGround] could not read existing state: {exc!r}")

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

            pre_pull_switch = getattr(self, "pre_pull_switch", None)
            data.update(
                {
                    "ext_filter": self.ext_field.text or "",
                    "path_filter": self.path_field.text or "",
                    "max_bytes": self.max_field.text or "",
                    "split_mb": self.split_field.text or "",
                    "meta_density_index": self.seg_meta.selected_index,
                    "plan_only": bool(self.plan_only_switch.value),
                    "code_only": bool(getattr(self, "code_only_switch", False) and self.code_only_switch.value),
                    "pre_pull": True if pre_pull_switch is None else bool(pre_pull_switch.value),
                    "selected_repos": self._get_selected_repos(explicit_only=True),
                    "extras": {
                        "health": self.extras_config.health,
                        "organism_index": self.extras_config.organism_index,
                        "fleet_panorama": self.extras_config.fleet_panorama,
                        "delta_reports": self.extras_config.delta_reports,
                        "augment_sidecar": self.extras_config.augment_sidecar,
                        "heatmap": self.extras_config.heatmap,
                        "json_sidecar": self.extras_config.json_sidecar,
                        "language_structure": self.extras_config.language_structure,
                    },
                    "prescan_pool": self._serialize_prescan_pool(),
                }
            )

        try:
            self._state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[RepoGround] could not persist state: {exc}")

    def restore_last_state(self, sender=None) -> None:
        try:
            raw = self._state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            if sender: # Nur bei Klick Feedback geben
                if console:
                    console.alert("RepoGround", "No saved state found.", "OK", hide_cancel_button=True)
            return
        except Exception as exc:
            print(f"[RepoGround] could not read state: {exc!r}", file=sys.stderr)
            return

        try:
            data = json.loads(raw)
        except Exception as exc:
            print(f"[RepoGround] invalid state JSON: {exc!r}", file=sys.stderr)
            return

        # Felder setzen
        profile = data.get("detail_profile")
        if profile and profile in self.seg_detail.segments:
            try:
                self.seg_detail.selected_index = self.seg_detail.segments.index(profile)
            except ValueError as e:
                # If the profile is not found in segments, just skip setting selected_index.
                print(f"[RepoGround] Profile '{profile}' not found in segments: {e}", file=sys.stderr)

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
        if getattr(self, "pre_pull_switch", None) is not None:
            self.pre_pull_switch.value = bool(data.get("pre_pull", True))

        self.ignored_repos = set(data.get("ignored_repos", []))

        # Restore Extras
        # Important: only overwrite if key exists, otherwise keep default (which might be True for new features)
        extras_data = data.get("extras", {})
        if extras_data:
            _restore_extras(self.extras_config, extras_data)

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

    def _load_ignored_repos_from_state(self) -> None:
        """Lädt beim Start nur die persistierte Ignore-Liste."""
        # _state_path wird im __init__ gesetzt
        try:
            raw = self._state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except Exception as exc:
            print(f"[RepoGround] could not read ignore state: {exc!r}")
            return

        try:
            data = json.loads(raw)
        except Exception as exc:
            print(f"[RepoGround] invalid ignore state JSON: {exc!r}")
            return

        if isinstance(data, dict):
            self.ignored_repos = set(data.get("ignored_repos", []))
