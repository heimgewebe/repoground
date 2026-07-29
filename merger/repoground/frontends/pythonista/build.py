#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RepoGround build – deterministic repository context for humans and agents.
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

# Explicit dual import contract:
# - package mode uses the normal merger.repoground package graph without sys.path mutation;
# - flat Pythonista execution installs only the deterministic shipped roots.
if __package__:
    from merger.repoground.frontends.pythonista.import_contract import (
        bootstrap_pythonista_imports,
    )
else:
    from import_contract import bootstrap_pythonista_imports

IMPORT_PATHS = bootstrap_pythonista_imports(globals().get("__file__"), __package__)
SCRIPT_DIR = IMPORT_PATHS.script_dir

if __package__:
    from merger.repoground.frontends.pythonista.build_utils import (
        normalize_path,
        normalize_repo_id,
        safe_script_path,
    )
    from merger.repoground.frontends.pythonista.build_helpers import (
        deserialize_prescan_pool,
        resolve_pool_include_paths,
    )
    from merger.repoground.frontends.pythonista.cli_args import parse_args as parse_cli_args
    from merger.repoground.frontends.pythonista.cli_output import (
        extract_delta_meta,
        resolve_output_options,
        resolve_scan_options,
        write_cli_reports,
    )
    from merger.repoground.frontends.pythonista.cli_runner import run_main_cli
    from merger.repoground.frontends.pythonista.source_mode import (
        git_subprocess_unavailable_message,
        git_subprocesses_supported,
        is_ios_runtime,
        resolve_effective_headless_source_mode,
        resolve_effective_pre_pull,
        resolve_headless_source_mode,
        resolve_pre_pull_switch_value,
        run_pre_pull_two_phase as _run_pre_pull_two_phase,
    )
    from merger.repoground.frontends.pythonista.merger_ui_prescan import MergerUIPrescanMixin
    from merger.repoground.frontends.pythonista.merger_ui_merge_run import MergerUIMergeRunMixin
    from merger.repoground.frontends.pythonista.merger_ui_browser import MergerUIBrowserMixin
else:
    from build_utils import normalize_path, normalize_repo_id, safe_script_path
    from build_helpers import deserialize_prescan_pool, resolve_pool_include_paths
    from cli_args import parse_args as parse_cli_args
    from cli_output import (
        extract_delta_meta,
        resolve_output_options,
        resolve_scan_options,
        write_cli_reports,
    )
    from cli_runner import run_main_cli
    from source_mode import (
        git_subprocess_unavailable_message,
        git_subprocesses_supported,
        is_ios_runtime,
        resolve_effective_headless_source_mode,
        resolve_effective_pre_pull,
        resolve_headless_source_mode,
        resolve_pre_pull_switch_value,
        run_pre_pull_two_phase as _run_pre_pull_two_phase,
    )
    from merger_ui_prescan import MergerUIPrescanMixin
    from merger_ui_merge_run import MergerUIMergeRunMixin
    from merger_ui_browser import MergerUIBrowserMixin


# Compatibility surface consumed by tests and the dependency-injected CLI runner.
__all__ = [
    "extract_delta_meta",
    "git_subprocess_unavailable_message",
    "git_subprocesses_supported",
    "is_ios_runtime",
    "parse_cli_args",
    "resolve_effective_headless_source_mode",
    "resolve_headless_source_mode",
    "resolve_output_options",
    "resolve_scan_options",
    "write_cli_reports",
]


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
            title = "RepoGround"
            if level == "error":
                title += " Error"
            ui.alert(title, msg, "OK", hide_cancel_button=True)
            return
        except Exception:
            pass

    # 3. Print (Last resort)
    sys.stderr.write(f"[RepoGround] [{level}] {msg}\n")


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
LAST_STATE_FILENAME = ".repoground-state.json"

# Import core logic
try:
    from merger.repoground.core.merge import (
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
    from merger.repoground.core.pr_schau_bundle import load_pr_schau_bundle, BUNDLE_FILENAME
except ImportError:
    # Pythonista / Flat layout fallback
    from merger.repoground.core.merge import (
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
    from merger.repoground.core.pr_schau_bundle import load_pr_schau_bundle, BUNDLE_FILENAME

try:
    from merger.repoground.service.repo_sync import (
        plan_pre_pull_repos,
        apply_pre_pull_plans,
        is_self_repo,
        PrePullStatus,
        HARD_FAIL_STATUSES,
        WARN_STATUSES,
    )
except ImportError:
    try:
        from merger.repoground.service.repo_sync import (
            plan_pre_pull_repos,
            apply_pre_pull_plans,
            is_self_repo,
            PrePullStatus,
            HARD_FAIL_STATUSES,
            WARN_STATUSES,
        )
    except ImportError:
        plan_pre_pull_repos = None
        apply_pre_pull_plans = None
        is_self_repo = lambda p: False
        PrePullStatus = None
        HARD_FAIL_STATUSES = []
        WARN_STATUSES = []

try:
    from merger.repoground.service.source_acquisition import (
        resolve_remote_ref,
        materialize_remote_snapshot,
        SourceStatus,
        validate_source_mode_request,
        SourceModeConflictError,
    )
except ImportError:
    try:
        from merger.repoground.service.source_acquisition import (
            resolve_remote_ref,
            materialize_remote_snapshot,
            SourceStatus,
            validate_source_mode_request,
            SourceModeConflictError,
        )
    except ImportError:
        # The remote-snapshot machinery needs the service package (git/network),
        # so it stays unavailable here. The source-mode *control plane*, however,
        # is pure logic with no dependencies — so we ship a local fallback rather
        # than fail open. RepoGround build must never skip source-mode validation just
        # because the service package is not importable.
        resolve_remote_ref = None
        materialize_remote_snapshot = None
        SourceStatus = None

        class SourceModeConflictError(ValueError):  # type: ignore[no-redef]
            """Local fallback mirroring service.source_acquisition.SourceModeConflictError."""

        def validate_source_mode_request(  # type: ignore[no-redef]
            *,
            repo_source_mode,
            pre_pull,
            plan_only,
            remote_ref,
            remote_ref_policy,
        ):
            """Local mirror of the central validator (kept in lockstep with it).

            Pure logic, no I/O. Rejects the same contradictions /api/jobs does so a
            headless RepoGround build run without the service package still fails closed.
            """
            allowed_modes = {None, "local_current", "local_ff", "remote_snapshot"}
            if repo_source_mode not in allowed_modes:
                raise SourceModeConflictError(f"unknown repo_source_mode: {repo_source_mode!r}")

            has_remote_ref = bool(remote_ref and str(remote_ref).strip())
            non_default_policy = remote_ref_policy is not None and remote_ref_policy != "upstream"

            if repo_source_mode == "remote_snapshot":
                if pre_pull is True:
                    raise SourceModeConflictError(
                        "remote_snapshot never mutates the local repo; pre_pull must not be true."
                    )
                return None

            if has_remote_ref:
                raise SourceModeConflictError(
                    "remote_ref is only valid with repo_source_mode='remote_snapshot'."
                )
            if non_default_policy:
                raise SourceModeConflictError(
                    "a non-default remote_ref_policy is only valid with "
                    "repo_source_mode='remote_snapshot'."
                )

            if repo_source_mode == "local_current":
                if pre_pull is True:
                    raise SourceModeConflictError(
                        "local_current scans the working tree as-is and does not fast-forward; "
                        "pre_pull must not be true."
                    )
                return None

            if repo_source_mode == "local_ff":
                if pre_pull is False:
                    raise SourceModeConflictError(
                        "local_ff implies a fast-forward pre-pull; pre_pull must not be false."
                    )
                if plan_only:
                    raise SourceModeConflictError(
                        "local_ff cannot be combined with plan_only: local_ff would fast-forward "
                        "the local repo, but plan_only must not cause any local mutation."
                    )
                return None

            # repo_source_mode is None → legacy; nothing further to validate.
            return None


# --- Runtime capability gate (Pythonista/iOS has no subprocess support) -------
#
# Pythonista on iOS raises "Subprocesses are not supported on ios" the instant
# ``subprocess`` is touched. Every git-backed feature (pre-pull, source-mode
# local-ff, remote-snapshot) shells out to git, so those must be gated off on iOS
# *before* the subprocess path is reached — never handled after the fact. Local
# filesystem scans use no subprocess and stay available.

def run_pre_pull_two_phase(sources, log=print, warn=None):
    """Run the portable two-phase pre-pull with current runtime integrations."""
    return _run_pre_pull_two_phase(
        sources,
        plan_pre_pull_repos=plan_pre_pull_repos,
        apply_pre_pull_plans=apply_pre_pull_plans,
        is_self_repo=is_self_repo,
        pre_pull_status=PrePullStatus,
        hard_fail_statuses=HARD_FAIL_STATUSES,
        warn_statuses=WARN_STATUSES,
        log=log,
        warn=warn,
    )


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


def _load_repoground_extractor_module():
    """Load extractor module from core."""
    try:
        from merger.repoground.core import extractor
        return extractor
    except ImportError:
        try:
            from merger.repoground.core import extractor
            return extractor
        except Exception as exc:
            print(f"[RepoGround] could not load lenskit.core.extractor: {exc}")
            return None
    except Exception as exc:
        print(f"[RepoGround] could not load merger.repoground.core.extractor: {exc}")
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
        extractor = _load_repoground_extractor_module()
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
        sys.stderr.write(f"[RepoGround] Extractor auto-run warning: {e}\n")
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

class MergerUI(MergerUIPrescanMixin, MergerUIBrowserMixin, MergerUIMergeRunMixin):
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
            print(f"[RepoGround] could not read ignore state: {exc!r}")
            return

        try:
            data = json.loads(raw)
        except Exception as exc:
            print(f"[RepoGround] invalid ignore state JSON: {exc!r}")
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



# --- CLI Mode ---



def _wire_pythonista_mixin_globals() -> None:
    """Bind build-module symbols into extracted MergerUI mixins.

    Mixins load during build.py import. After this module finished defining
    helpers/constants (and optional Pythonista ui), copy those names into the
    mixin modules so method bodies keep their historical free-variable lookup.
    """
    import sys

    package = __package__ or ""
    module_names = (
        f"{package}.merger_ui_prescan" if package else "merger_ui_prescan",
        f"{package}.merger_ui_merge_run" if package else "merger_ui_merge_run",
        f"{package}.merger_ui_browser" if package else "merger_ui_browser",
    )
    skip = {
        "__name__",
        "__file__",
        "__package__",
        "__cached__",
        "__builtins__",
        "__spec__",
        "__loader__",
        "__doc__",
        "__all__",
        "MergerUI",
        "MergerUIPrescanMixin",
        "MergerUIBrowserMixin",
        "MergerUIMergeRunMixin",
        "_wire_pythonista_mixin_globals",
    }
    payload = {
        name: value
        for name, value in globals().items()
        if name not in skip and not name.startswith("__")
    }
    for module_name in module_names:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for name, value in payload.items():
            setattr(module, name, value)


_wire_pythonista_mixin_globals()

def _is_headless_requested() -> bool:
    # Headless wenn:
    # 1) --headless Flag, oder
    # 2) REPOGROUND_HEADLESS=1 in the environment, or
    # 3) ui-Framework nicht verfügbar
    return ("--headless" in sys.argv) or (os.environ.get("REPOGROUND_HEADLESS") == "1") or (ui is None)

def main_cli(argv=None):
    """Run the headless contract through the explicit orchestration module."""
    return run_main_cli(sys.modules[__name__], argv)


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
                        "RepoGround",
                        f"UI not available, falling back to CLI. ({e})",
                        "OK",
                        hide_cancel_button=True,
                    )
                except Exception:
                    pass
            else:
                print(
                    f"RepoGround: UI not available, falling back to CLI. ({e})",
                    file=sys.stderr,
                )
            main_cli()
    else:
        main_cli()

if __name__ == "__main__":
    main()
