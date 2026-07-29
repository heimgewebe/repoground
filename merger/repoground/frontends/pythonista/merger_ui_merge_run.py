# -*- coding: utf-8 -*-
"""merger ui merge run.py

Extracted from build.MergerUI for REPOGROUND-LEGACY-RECONCILIATION-V1-T004.
Behavior is unchanged; methods remain bound via Mixin inheritance.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class MergerUIMergeRunMixin:
    def _run_merge_form_reset_after_success_safe(self) -> None:
        """Safely reset form after success, with error handling and logging."""
        try:
            self.reset_merge_form_to_defaults_after_success()
        except Exception as exc:
            print(
                f"[RepoGround] Warning: failed to reset merge form after success: {exc}",
                file=sys.stderr,
            )

    def schedule_merge_form_reset_after_success(self) -> None:
        """Schedule form reset on main thread (UI thread) if possible."""
        # Resolve ui from build module so tests can patch build.ui live.
        if __package__:
            from merger.repoground.frontends.pythonista import build as _build
        else:
            import build as _build  # type: ignore
        ui_mod = getattr(_build, "ui", None)
        if ui_mod is not None and hasattr(ui_mod, "delay"):
            ui_mod.delay(self._run_merge_form_reset_after_success_safe, 0.0)
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
                f"[RepoGround] Warning: failed to reset table view selection: {exc}",
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
        if getattr(self, "pre_pull_switch", None) is not None:
            self.pre_pull_switch.value = True

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
        self._pending_pre_pull = resolve_pre_pull_switch_value(getattr(self, "pre_pull_switch", None))

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
                console.alert("RepoGround", msg, "OK", hide_cancel_button=True)
            else:
                print(msg, file=sys.stderr)
        finally:
            # Cleanup snapshotted state to prevent stale values in future runs
            if hasattr(self, "_pending_plan_only"):
                del self._pending_plan_only
            if hasattr(self, "_pending_code_only"):
                del self._pending_code_only
            if hasattr(self, "_pending_pre_pull"):
                del self._pending_pre_pull

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
                print(f"[RepoGround] WARNING: {msg}", file=sys.stderr)
            else:
                repo_norm_map[norm] = r

        pool_raw = getattr(self, "saved_prescan_selections", None) or {}
        pool_norm = {}
        if isinstance(pool_raw, dict):
            for k, v in pool_raw.items():
                n_key = normalize_repo_id(k)
                if n_key: # Ignore empty keys
                    if n_key in pool_norm:
                        print(f"[RepoGround] WARNING: Pool key collision for '{n_key}' (overwriting).", file=sys.stderr)
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
                console.alert("RepoGround", "No repos selected or found in pool.", "OK", hide_cancel_button=True)
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

        if hasattr(self, "_pending_pre_pull"):
            pre_pull = self._pending_pre_pull
        else:
            pre_pull_switch = getattr(self, "pre_pull_switch", None)
            pre_pull = bool(pre_pull_switch is None or pre_pull_switch.value)

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
            print(f"[RepoGround] {msg}")

        # Check for restrictive pool entries to decide on execution strategy
        has_restrictive = False
        for name in selected_repos:
            paths = get_pool_include_paths(name)
            if paths is not None and isinstance(paths, list) and len(paths) > 0:
                has_restrictive = True
                break

        merges_dir = get_merges_dir(self.hub)
        all_out_paths = []

        # Pre-pull (bounded repo-sync mutation), two-phase across ALL selected repos
        # BEFORE any scan, so no repo is fast-forwarded when another repo hard-fails during the plan phase.
        # plan_only never mutates local repos, so it forces pre-pull off; Pythonista/iOS
        # forces it off too (no git subprocesses) — see resolve_effective_pre_pull.
        def _pre_pull_hud(message):
            try:
                if console:
                    console.hud_alert(message, "info", 2.0)
            except Exception:
                # Best-effort UI notification only; HUD errors must not interrupt the merge flow.
                pass

        effective_pre_pull = resolve_effective_pre_pull(
            pre_pull, plan_only, log=print, notify=_pre_pull_hud
        )
        if effective_pre_pull:
            pre_pull_sources = [self.hub / name for name in selected_repos if (self.hub / name).is_dir()]
            try:
                run_pre_pull_two_phase(pre_pull_sources, log=print)
            except Exception as e:
                if console:
                    try:
                        console.hud_alert(f"Pre-pull failed: {e}", "error", 2.0)
                    except Exception:
                        # Best-effort UI notification only; ignore HUD failures and continue
                        # with stderr logging + re-raising the original pre-pull exception.
                        pass
                print(f"Pre-pull failed: {e}", file=sys.stderr)
                raise
        elif pre_pull and plan_only:
            print("Pre-pull skipped because plan_only=True.")

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

                # Pre-pull already handled once (two-phase) before this loop.

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
                    mod = _load_repoground_extractor_module()
                    if mod and hasattr(mod, "find_latest_diff_for_repo") and hasattr(mod, "extract_delta_meta_from_diff_file"):
                        diff_path = mod.find_latest_diff_for_repo(merges_dir, repo_name)
                        if diff_path:
                            delta_meta = mod.extract_delta_meta_from_diff_file(diff_path)
                except Exception as e:
                    print(f"[RepoGround] Warning: Could not extract delta metadata: {e}", file=sys.stderr)

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
                generator_info={"name": "repoground", "platform": "ios"},
            )

            all_out_paths.extend(artifacts.get_all_paths())

            # Force close intermediate files
            force_close_files(artifacts.get_all_paths())

        if not all_out_paths:
            if console:
                console.alert("RepoGround", "No report generated.", "OK", hide_cancel_button=True)
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
                console.alert("RepoGround", msg, "OK", hide_cancel_button=True)
        else:
            print(f"RepoGround: {msg}")
            for p in all_out_paths:
                print(f"  - {p.name}")

        if all_out_paths:
            self.schedule_merge_form_reset_after_success()
