# -*- coding: utf-8 -*-
"""merger ui prescan.py

Extracted from build.MergerUI for REPOGROUND-LEGACY-RECONCILIATION-V1-T004.
Behavior is unchanged; methods remain bound via Mixin inheritance.
"""
from __future__ import annotations

BUILD_GLOBAL_NAMES = (
    "_notify",
    "console",
    "normalize_path",
    "parse_human_size",
    "ui",
)


class MergerUIPrescanMixin:
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
            from merger.repoground.core.merge import prescan_repo
        except ImportError:
            try:
                from merger.repoground.core.merge import prescan_repo
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
