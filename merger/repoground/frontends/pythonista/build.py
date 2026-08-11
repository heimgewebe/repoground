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
    from merger.repoground.frontends.pythonista.merger_ui_init import MergerUIInitMixin
    from merger.repoground.frontends.pythonista.merger_ui_state import MergerUIStateMixin
    from merger.repoground.frontends.pythonista.merger_ui_controls import MergerUIControlsMixin
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
    from merger_ui_init import MergerUIInitMixin
    from merger_ui_state import MergerUIStateMixin
    from merger_ui_controls import MergerUIControlsMixin
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
    "delta_reports", "augment_sidecar", "heatmap", "json_sidecar",
    "language_structure"
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


def _clear_active_merger_view(view) -> None:
    """Clear the shared active-view pointer only for the matching view."""
    global _ACTIVE_MERGER_VIEW
    if _ACTIVE_MERGER_VIEW is view:
        _ACTIVE_MERGER_VIEW = None


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

class MergerUI(MergerUIInitMixin, MergerUIControlsMixin, MergerUIStateMixin, MergerUIPrescanMixin, MergerUIBrowserMixin, MergerUIMergeRunMixin):
    """Composition shell for the Pythonista Merger UI.

    Behavior lives in mixins extracted for REPOGROUND-LEGACY-RECONCILIATION-V1-T004.
    """


# --- CLI Mode ---



def _wire_pythonista_mixin_globals() -> None:
    """Bind only declared build-module dependencies into MergerUI mixins.

    The extracted methods preserve their historical global lookups, but each
    mixin now declares the exact names it consumes. Missing declarations fail
    during import instead of silently inheriting the entire build module.
    """
    import sys

    available = {
        "BUNDLE_FILENAME": BUNDLE_FILENAME,
        "DEFAULT_EXTRAS": DEFAULT_EXTRAS,
        "DEFAULT_LEVEL": DEFAULT_LEVEL,
        "DEFAULT_MAX_FILE_BYTES": DEFAULT_MAX_FILE_BYTES,
        "DEFAULT_META_DENSITY": DEFAULT_META_DENSITY,
        "DEFAULT_MODE": DEFAULT_MODE,
        "DEFAULT_SPLIT_SIZE": DEFAULT_SPLIT_SIZE,
        "ExtrasConfig": ExtrasConfig,
        "LAST_STATE_FILENAME": LAST_STATE_FILENAME,
        "PROFILE_DESCRIPTIONS": PROFILE_DESCRIPTIONS,
        "PROFILE_PRESETS": PROFILE_PRESETS,
        "PRSchauDataSource": PRSchauDataSource,
        "PR_SCHAU_DIR": PR_SCHAU_DIR,
        "TF_BORDER_NONE": TF_BORDER_NONE,
        "_clear_active_merger_view": _clear_active_merger_view,
        "_dismiss_view_best_effort": _dismiss_view_best_effort,
        "_flatten_meta": _flatten_meta,
        "_load_repoground_extractor_module": _load_repoground_extractor_module,
        "_normalize_ext_list": _normalize_ext_list,
        "_notify": _notify,
        "_pick_primary_artifact": _pick_primary_artifact,
        "console": console,
        "deserialize_prescan_pool": deserialize_prescan_pool,
        "editor": editor,
        "find_repos_in_hub": find_repos_in_hub,
        "force_close_files": force_close_files,
        "get_merges_dir": get_merges_dir,
        "json": json,
        "load_pr_schau_bundle": load_pr_schau_bundle,
        "normalize_path": normalize_path,
        "normalize_repo_id": normalize_repo_id,
        "parse_human_size": parse_human_size,
        "quicklook": quicklook,
        "resolve_effective_pre_pull": resolve_effective_pre_pull,
        "resolve_pool_include_paths": resolve_pool_include_paths,
        "resolve_pre_pull_switch_value": resolve_pre_pull_switch_value,
        "run_pre_pull_two_phase": run_pre_pull_two_phase,
        "scan_repo": scan_repo,
        "sys": sys,
        "ui": ui,
        "write_reports_v2": write_reports_v2,
    }
    for mixin in (
        MergerUIInitMixin,
        MergerUIControlsMixin,
        MergerUIStateMixin,
        MergerUIPrescanMixin,
        MergerUIBrowserMixin,
        MergerUIMergeRunMixin,
    ):
        module = sys.modules.get(mixin.__module__)
        if module is None:
            raise RuntimeError(f"MergerUI mixin module not loaded: {mixin.__module__}")
        required = tuple(getattr(module, "BUILD_GLOBAL_NAMES", ()))
        if not required:
            raise RuntimeError(f"MergerUI mixin has no dependency contract: {mixin.__module__}")
        missing = sorted(name for name in required if name not in available)
        if missing:
            raise RuntimeError(
                f"MergerUI mixin dependencies missing for {mixin.__module__}: {missing}"
            )
        for name in required:
            setattr(module, name, available[name])


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
