# -*- coding: utf-8 -*-
"""merger ui browser.py

Extracted from build.MergerUI for REPOGROUND-LEGACY-RECONCILIATION-V1-T004.
Behavior is unchanged; methods remain bound via Mixin inheritance.
"""
from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path
from typing import Optional


BUILD_GLOBAL_NAMES = (
    "BUNDLE_FILENAME",
    "ExtrasConfig",
    "PRSchauDataSource",
    "PR_SCHAU_DIR",
    "_flatten_meta",
    "_load_repoground_extractor_module",
    "_notify",
    "console",
    "editor",
    "force_close_files",
    "get_merges_dir",
    "load_pr_schau_bundle",
    "quicklook",
    "scan_repo",
    "ui",
    "write_reports_v2",
)


class MergerUIBrowserMixin:
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
            print(f"[RepoGround] could not scan merges dir: {exc}")
            candidates = []

        if not candidates:
            if console:
                console.alert(
                    "RepoGround",
                    "No import diff found.",
                    "OK",
                    hide_cancel_button=True,
                )
            else:
                print("[RepoGround] No import diff found.")
            return

        # jüngstes Diff wählen
        try:
            diff_path = max(candidates, key=lambda p: p.stat().st_mtime)
        except Exception as exc:
            if console:
                console.alert(
                    "RepoGround",
                    f"Failed to select latest diff: {exc}",
                    "OK",
                    hide_cancel_button=True,
                )
            else:
                print(f"[RepoGround] Failed to select latest diff: {exc}")
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
                console.alert("RepoGround", msg, "OK", hide_cancel_button=True)
            else:
                print(f"[RepoGround] {msg}")
            return

        mod = _load_repoground_extractor_module()
        if mod is None or not hasattr(mod, "create_delta_merge_from_diff"):
            msg = "Delta helper (repolens-extractor) not available."
            if console:
                console.alert("RepoGround", msg, "OK", hide_cancel_button=True)
            else:
                print(f"[RepoGround] {msg}")
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
                    console.alert("RepoGround", msg, "OK", hide_cancel_button=True)
                else:
                    print(f"[RepoGround] {msg}")
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
                    print(f"[RepoGround] Failed to read delta metadata: {e}", file=sys.stderr)

            if not delta_meta:
                msg = "Could not extract delta metadata from diff."
                if console:
                    console.alert("RepoGround", msg, "OK", hide_cancel_button=True)
                else:
                    print(f"[RepoGround] {msg}")
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
                generator_info={"name": "repoground", "platform": "ios"},
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
                    console.alert("RepoGround", msg, "OK", hide_cancel_button=True)
            else:
                print(f"[RepoGround] {msg}")

        except Exception as exc:
            msg = f"Delta merge failed: {exc}"
            if console:
                console.alert("RepoGround", msg, "OK", hide_cancel_button=True)
            else:
                print(f"[RepoGround] {msg}")
            return
