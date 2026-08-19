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


def _selected_prescan_repo_path(view):
    selected = view._get_selected_repos()
    if len(selected) != 1:
        if console:
            console.hud_alert("Please select exactly one repo for Prescan.", "error")
        return False, None
    return True, view.hub / selected[0]


def _append_prescan_item(flat_items, node, depth, root_name):
    name = node["path"].split("/")[-1]
    if node["path"] == ".":
        name = root_name
    icon = "📁" if node["type"] == "dir" else "📄"
    flat_items.append(
        {
            "path": node["path"],
            "display": f"{'  ' * depth}{icon} {name}",
            "type": node["type"],
            "depth": depth,
            "orig": node,
            "selected": False,
        }
    )
    children = node.get("children") or []
    dirs = sorted((child for child in children if child["type"] == "dir"), key=lambda child: child["path"])
    files = sorted((child for child in children if child["type"] == "file"), key=lambda child: child["path"])
    for child in dirs + files:
        _append_prescan_item(flat_items, child, depth + 1, root_name)


def _flatten_prescan_items(root_node, root_name):
    flat_items = []
    _append_prescan_item(flat_items, root_node, 0, root_name)
    return flat_items


def _recommended_prescan_path(path_str):
    path = path_str.lower()
    if "readme" in path or path.endswith(".ai-context.yml"):
        return True
    parts = path.split("/")
    return ("src" in parts or "contracts" in parts or "docs" in parts) and "test" not in path


def _pool_selects_path(path, pool_set, normalize_path_fn):
    normalized = normalize_path_fn(path)
    if normalized in pool_set:
        return True
    parts = normalized.split("/")
    return any("/".join(parts[: index + 1]) in pool_set for index in range(len(parts)))


def _initialize_prescan_selection(flat_items, existing_pool_entry, normalize_path_fn):
    if existing_pool_entry and isinstance(existing_pool_entry, dict):
        raw = existing_pool_entry.get("raw")
        if raw is None:
            for item in flat_items:
                item["selected"] = True
            return
        if isinstance(raw, list):
            pool_set = {normalize_path_fn(path) for path in raw}
            for item in flat_items:
                item["selected"] = _pool_selects_path(item["path"], pool_set, normalize_path_fn)
        return
    if not existing_pool_entry:
        for item in flat_items:
            item["selected"] = item["type"] == "file" and _recommended_prescan_path(item["path"])


def _initial_prescan_selection_state(flat_items, existing_pool_entry):
    is_all = (
        isinstance(existing_pool_entry, dict)
        and existing_pool_entry.get("raw") is None
        and existing_pool_entry.get("compressed") is None
    )
    if is_all:
        return {"mode": "all"}
    if not any(item["selected"] for item in flat_items):
        return {"mode": "none"}
    return {"mode": "partial"}


def _make_prescan_sheet(owner, root_name, ui_module):
    class PrescanSheet(ui_module.View):
        def __init__(self, parent):
            super().__init__()
            self._parent = parent
            self.name = f"Prescan: {root_name}"
            self.background_color = "#111111"
            self.frame = (0, 0, 600, 800)

        def will_close(self):
            if self._parent._prescan_active:
                self._parent._prescan_active = False

    return PrescanSheet(owner)


def _add_prescan_stats(sheet, prescan_data, ui_module, parse_human_size_fn):
    stats_lbl = ui_module.Label(frame=(10, 10, 580, 20))
    stats_lbl.text = (
        f"{prescan_data['file_count']} files • "
        f"{parse_human_size_fn(str(prescan_data['total_bytes']))} bytes total"
    )
    stats_lbl.text_color = "gray"
    stats_lbl.font = ("<System>", 12)
    sheet.add_subview(stats_lbl)


def _toggle_prescan_all(flat_items, selection_state, table_view, value):
    for item in flat_items:
        item["selected"] = value
    selection_state["mode"] = "all" if value else "none"
    table_view.reload_data()


def _add_prescan_select_buttons(sheet, flat_items, selection_state, table_view, ui_module):
    button_specs = (("All", 10, True), ("None", 100, False))
    for title, x, value in button_specs:
        button = ui_module.Button(title=title)
        button.frame = (x, 40, 80, 30)
        button.background_color = "#333333"
        button.tint_color = "white"
        button.corner_radius = 4
        button.action = lambda sender, selected=value: _toggle_prescan_all(
            flat_items, selection_state, table_view, selected
        )
        sheet.add_subview(button)


def _create_prescan_table(sheet, flat_items, selection_state, ui_module):
    table_view = ui_module.TableView()
    table_view.frame = (0, 80, sheet.width, sheet.height - 140)
    table_view.flex = "WH"
    table_view.background_color = "#111111"
    table_view.separator_color = "#333333"
    table_view.allows_multiple_selection = False
    data_source = _PrescanDataSource(flat_items, selection_state, ui_module)
    table_view.data_source = data_source
    table_view.delegate = data_source
    return table_view


def _collect_all_descendant_files(node, materialized_raw):
    if node["type"] == "file":
        materialized_raw.append(node["path"])
        return
    for child in node.get("children") or []:
        _collect_all_descendant_files(child, materialized_raw)


def _collect_materialized_selection(node, selection_map, materialized_raw, compressed_paths):
    path = node["path"]
    if selection_map.get(path, False):
        if node["type"] == "file":
            materialized_raw.append(path)
            compressed_paths.append(path)
        else:
            compressed_paths.append(path)
            _collect_all_descendant_files(node, materialized_raw)
        return
    if node["type"] == "dir":
        for child in node.get("children") or []:
            _collect_materialized_selection(
                child, selection_map, materialized_raw, compressed_paths
            )


def _materialize_prescan_paths(root_node, flat_items, normalize_path_fn):
    selection_map = {item["path"]: item["selected"] for item in flat_items}
    materialized_raw = []
    compressed_paths = []
    _collect_materialized_selection(
        root_node, selection_map, materialized_raw, compressed_paths
    )
    raw_paths = sorted({normalize_path_fn(path) for path in materialized_raw})
    compressed = sorted({normalize_path_fn(path) for path in compressed_paths})
    return raw_paths, compressed


def _prescan_node_selection_status(root_node, raw_set, normalize_path_fn):
    stack1 = [root_node]
    stack2 = []
    while stack1:
        node = stack1.pop()
        stack2.append(node)
        stack1.extend(node.get("children") or [])

    node_status = {}
    while stack2:
        node = stack2.pop()
        path = normalize_path_fn(node["path"])
        if node["type"] == "file":
            node_status[path] = path in raw_set
            continue
        children = node.get("children") or []
        node_status[path] = bool(children) and all(
            node_status.get(normalize_path_fn(child["path"]), False)
            for child in children
        )
    return node_status


def _compress_prescan_raw_paths(root_node, merged_raw, normalize_path_fn):
    raw_set = {normalize_path_fn(path) for path in merged_raw}
    node_status = _prescan_node_selection_status(root_node, raw_set, normalize_path_fn)
    new_compressed = []
    stack = [root_node]
    while stack:
        node = stack.pop()
        path = normalize_path_fn(node["path"])
        if node_status.get(path, False):
            new_compressed.append(path)
            continue
        children = node.get("children") or []
        for child in reversed(children):
            stack.append(child)
    return {
        "raw": sorted(raw_set),
        "compressed": [normalize_path_fn(path) for path in new_compressed],
    }


def _replace_prescan_pool(pool, root_name, current_mode, raw_paths, compressed_paths):
    if current_mode == "all":
        pool[root_name] = {"raw": None, "compressed": None}
    elif current_mode == "none":
        pool.pop(root_name, None)
    elif compressed_paths or raw_paths:
        pool[root_name] = {
            "raw": raw_paths if raw_paths else None,
            "compressed": compressed_paths if compressed_paths else None,
        }
    else:
        pool.pop(root_name, None)


def _append_prescan_pool(
    pool, root_name, current_mode, raw_paths, root_node, normalize_path_fn
):
    if current_mode == "none":
        return False
    if current_mode == "all":
        pool[root_name] = {"raw": None, "compressed": None}
        return True

    existing = pool.get(root_name)
    if existing and isinstance(existing, dict):
        existing_raw = existing.get("raw")
        if existing_raw is None:
            pool[root_name] = {"raw": None, "compressed": None}
            return True
        merged_raw = set(existing_raw)
        merged_raw.update(raw_paths)
    else:
        merged_raw = set(raw_paths) if raw_paths else None

    if merged_raw:
        pool[root_name] = _compress_prescan_raw_paths(
            root_node, merged_raw, normalize_path_fn
        )
    else:
        pool.pop(root_name, None)
    return True


def _finish_prescan_pool_update(view, sheet, root_name, action, console_module):
    view.save_last_state()
    if console_module:
        console_module.hud_alert(
            f"{action} selection pool for {root_name}", "success", 1.5
        )
    view._prescan_active = False
    sheet.close()


def _update_prescan_pool(
    view,
    sheet,
    root_node,
    root_name,
    flat_items,
    selection_state,
    mode,
    normalize_path_fn,
    console_module,
):
    raw_paths, compressed_paths = _materialize_prescan_paths(
        root_node, flat_items, normalize_path_fn
    )
    pool = view.saved_prescan_selections

    if mode == "remove":
        pool.pop(root_name, None)
        _finish_prescan_pool_update(view, sheet, root_name, "Removed", console_module)
        return

    current_mode = selection_state["mode"]
    if mode == "replace":
        _replace_prescan_pool(
            pool, root_name, current_mode, raw_paths, compressed_paths
        )
        _finish_prescan_pool_update(view, sheet, root_name, "Replaced", console_module)
        return

    if mode == "append":
        changed = _append_prescan_pool(
            pool, root_name, current_mode, raw_paths, root_node, normalize_path_fn
        )
        if not changed:
            if console_module:
                console_module.hud_alert(
                    "No changes: no items selected in append mode", "error", 2.0
                )
            return
        _finish_prescan_pool_update(view, sheet, root_name, "Appended to", console_module)
        return

    view._prescan_active = False
    sheet.close()


def _format_pool_info(data):
    if not data or not isinstance(data, dict):
        return "Invalid state"
    raw = data.get("raw")
    compressed = data.get("compressed")
    if raw is None and compressed is None:
        return "ALL"
    raw_count = len(raw) if raw else 0
    compressed_count = len(compressed) if compressed else 0
    return f"Partial: {raw_count} files / {compressed_count} rules"


def _pool_viewer_items(pool):
    items = [
        {"repo": repo, "info": _format_pool_info(data)}
        for repo, data in pool.items()
    ]
    items.sort(key=lambda item: item["repo"])
    return items


def _pool_inspector_message(repo, entry):
    raw = entry.get("raw")
    compressed = entry.get("compressed")
    message = f"Repo: {repo}\n\n"
    if raw is None and compressed is None:
        return message + "State: ALL files included."

    raw_count = len(raw) if raw else 0
    compressed_count = len(compressed) if compressed else 0
    message += (
        f"State: Partial\nFiles: {raw_count}\nRules: {compressed_count}\n\n"
    )
    if not compressed:
        return message

    message += "Rules (Compressed):\n"
    for rule in compressed[:15]:
        message += f"- {rule}\n"
    if len(compressed) > 15:
        message += f"... and {len(compressed) - 15} more"
    return message


def _show_pool_inspector(pool, repo, console_module, ui_module):
    entry = pool.get(repo)
    if not entry or not isinstance(entry, dict):
        return
    message = _pool_inspector_message(repo, entry)
    if console_module:
        console_module.alert(
            "Pool Details", message, "OK", hide_cancel_button=True
        )
    elif ui_module:
        ui_module.alert("Pool Details", message, "OK")


def _add_empty_pool_label(sheet, ui_module):
    label = ui_module.Label(frame=(0, 0, 500, 600))
    label.text = "Pool is empty."
    label.alignment = ui_module.ALIGN_CENTER
    label.text_color = "gray"
    sheet.add_subview(label)


def _create_pool_viewer_table(parent, pool, ui_module, console_module):
    table = ui_module.TableView()
    table.frame = (0, 0, 500, 540)
    table.flex = "WH"
    table.background_color = "#111111"
    table.separator_color = "#333333"
    data_source = _PoolViewerDataSource(
        parent, pool, _pool_viewer_items(pool), ui_module, console_module
    )
    table.data_source = data_source
    table.delegate = data_source
    return table


def _clear_pool_from_viewer(parent, pool, sheet, console_module):
    pool.clear()
    parent.save_last_state()
    parent._update_repo_info()
    sheet.close()
    if console_module:
        console_module.hud_alert("Pool cleared")


def _add_pool_viewer_clear_bar(parent, pool, sheet, ui_module, console_module):
    bar = ui_module.View(frame=(0, 540, 500, 60))
    bar.flex = "WT"
    bar.background_color = "#222222"

    button = ui_module.Button(title="Clear Pool")
    button.frame = (10, 10, 100, 40)
    button.background_color = "#ff3b30"
    button.tint_color = "white"
    button.corner_radius = 6
    button.action = lambda sender: _clear_pool_from_viewer(
        parent, pool, sheet, console_module
    )
    bar.add_subview(button)
    sheet.add_subview(bar)


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
        selection_ok, repo_path = _selected_prescan_repo_path(self)
        if not selection_ok:
            return

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
        """Displays the prescan tree in a selection-only Sheet."""
        root_node = prescan_data["tree"]
        root_name = prescan_data["root"]
        flat_items = _flatten_prescan_items(root_node, root_name)
        existing_pool_entry = self.saved_prescan_selections.get(root_name)
        _initialize_prescan_selection(flat_items, existing_pool_entry, normalize_path)
        selection_state = _initial_prescan_selection_state(flat_items, existing_pool_entry)

        sheet = _make_prescan_sheet(self, root_name, ui)
        _add_prescan_stats(sheet, prescan_data, ui, parse_human_size)
        tv = _create_prescan_table(sheet, flat_items, selection_state, ui)
        _add_prescan_select_buttons(sheet, flat_items, selection_state, tv, ui)
        sheet.add_subview(tv)

        def reset_guard():
            self._prescan_active = False

        # Bottom Bar: Remove / Cancel / Replace / Append
        bar_y = sheet.height - 50

        # Remove button (left side)
        btn_remove = ui.Button(title="Remove")
        btn_remove.frame = (10, bar_y, 80, 40)
        btn_remove.flex = "RT" # Right margin flex, Top margin flex
        btn_remove.background_color = "#ff3b30"
        btn_remove.tint_color = "white"
        btn_remove.corner_radius = 6
        btn_remove.action = lambda s: _update_prescan_pool(
            self, sheet, root_node, root_name, flat_items, selection_state,
            "remove", normalize_path, console
        )
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
        btn_replace.action = lambda s: _update_prescan_pool(
            self, sheet, root_node, root_name, flat_items, selection_state,
            "replace", normalize_path, console
        )
        sheet.add_subview(btn_replace)

        # Append button (right side)
        # "Store to Pool (Append)"
        btn_append = ui.Button(title="Store (Append)")
        btn_append.frame = (sheet.width - 120, bar_y, 110, 40)
        btn_append.flex = "LT" # Left margin flex, Top margin flex
        btn_append.background_color = "#34c759"
        btn_append.tint_color = "white"
        btn_append.corner_radius = 6
        btn_append.action = lambda s: _update_prescan_pool(
            self, sheet, root_node, root_name, flat_items, selection_state,
            "append", normalize_path, console
        )
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
            _add_empty_pool_label(sheet, ui)
        else:
            sheet.add_subview(_create_pool_viewer_table(self, pool, ui, console))
            _add_pool_viewer_clear_bar(self, pool, sheet, ui, console)

        sheet.present("sheet")


class _PoolViewerDataSource:
    def __init__(self, parent, pool, items, ui_module, console_module):
        self.parent = parent
        self.pool = pool
        self.items = items
        self.ui = ui_module
        self.console = console_module

    def tableview_number_of_rows(self, tv, section):
        return len(self.items)

    def tableview_cell_for_row(self, tv, section, row):
        item = self.items[row]
        cell = self.ui.TableViewCell("value1")
        cell.text_label.text = item["repo"]
        cell.detail_text_label.text = item["info"]
        cell.text_label.text_color = "white"
        cell.detail_text_label.text_color = "#888888"
        cell.background_color = "#111111"
        cell.accessory_type = "detail_button"
        return cell

    def tableview_accessory_button_tapped(self, tv, section, row):
        self.show_inspector(row)

    def tableview_did_select(self, tv, section, row):
        self.show_inspector(row)

    def show_inspector(self, row):
        repo = self.items[row]["repo"]
        _show_pool_inspector(self.pool, repo, self.console, self.ui)

    def tableview_can_edit(self, tv, section, row):
        return True

    def tableview_delete(self, tv, section, row):
        repo = self.items[row]["repo"]
        if repo in self.pool:
            del self.pool[repo]
            self.parent.save_last_state()
            self.parent._update_repo_info()
        self.items.pop(row)
        tv.delete_rows([row])


class _PrescanDataSource:
    def __init__(self, flat_items, selection_state, ui_module):
        self.flat_items = flat_items
        self.selection_state = selection_state
        self.ui = ui_module

    def tableview_number_of_rows(self, tv, section):
        return len(self.flat_items)

    def tableview_cell_for_row(self, tv, section, row):
        item = self.flat_items[row]
        cell = self.ui.TableViewCell()
        cell.text_label.text = item["display"]
        cell.text_label.font = ("<Mono>", 12)
        cell.background_color = "#111111"
        cell.text_label.text_color = "white" if item["type"] == "file" else "#88ccff"
        cell.accessory_type = "checkmark" if item["selected"] else "none"
        return cell

    def tableview_did_select(self, tv, section, row):
        item = self.flat_items[row]
        new_state = not item["selected"]
        if self.selection_state["mode"] == "all" and not new_state:
            self.selection_state["mode"] = "partial"
        self._set_selected_recursive(item, new_state)
        self._refresh_selection_mode()
        tv.reload_data()

    def _refresh_selection_mode(self):
        if all(item["selected"] for item in self.flat_items):
            self.selection_state["mode"] = "all"
        elif not any(item["selected"] for item in self.flat_items):
            self.selection_state["mode"] = "none"
        else:
            self.selection_state["mode"] = "partial"

    def _set_selected_recursive(self, item, state):
        item["selected"] = state
        if item["type"] != "dir":
            return
        index = self.flat_items.index(item)
        for child in self.flat_items[index + 1 :]:
            if child["depth"] <= item["depth"]:
                break
            child["selected"] = state
