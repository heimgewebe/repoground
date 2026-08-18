from __future__ import annotations

import threading
from pathlib import Path

import pytest

from merger.repoground.frontends.pythonista import merger_ui_prescan as prescan_ui


class _Console:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def hud_alert(self, *args: object) -> None:
        self.calls.append(("hud_alert", *args))

    def show_activity(self, *args: object) -> None:
        self.calls.append(("show_activity", *args))

    def hide_activity(self, *args: object) -> None:
        self.calls.append(("hide_activity", *args))

    def alert(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("alert", *args, kwargs))


class _View(prescan_ui.MergerUIPrescanMixin):
    def __init__(self, selected: list[str]) -> None:
        self._selected = selected
        self.hub = Path("/hub")
        self._prescan_active = False

    def _get_selected_repos(self) -> list[str]:
        return self._selected

    def _present_prescan_ui(self, data: object) -> None:
        raise AssertionError(f"unexpected presentation: {data!r}")


@pytest.mark.parametrize("selected", [[], ["repo-a", "repo-b"]])
def test_show_prescan_sheet_rejects_non_single_selection(monkeypatch, selected: list[str]) -> None:
    console = _Console()
    monkeypatch.setattr(prescan_ui, "console", console, raising=False)
    view = _View(selected)

    assert view.show_prescan_sheet(None) is None

    assert console.calls == [
        ("hud_alert", "Please select exactly one repo for Prescan.", "error")
    ]
    assert view._prescan_active is False


def test_show_prescan_sheet_scans_selected_repo_and_schedules_ui(monkeypatch) -> None:
    console = _Console()
    monkeypatch.setattr(prescan_ui, "console", console, raising=False)

    delayed: list[tuple[object, int]] = []

    class _UI:
        @staticmethod
        def delay(callback, delay: int) -> None:
            delayed.append((callback, delay))

    monkeypatch.setattr(prescan_ui, "ui", _UI, raising=False)

    scan_calls: list[tuple[Path, int]] = []
    from merger.repoground.core import merge as merge_core

    def fake_prescan_repo(path: Path, *, max_depth: int):
        scan_calls.append((path, max_depth))
        return {"tree": {}, "root": "repo-a"}

    monkeypatch.setattr(merge_core, "prescan_repo", fake_prescan_repo)

    started: list[object] = []

    class _Thread:
        def __init__(self, *, target) -> None:
            self.target = target

        def start(self) -> None:
            started.append(self.target)

    monkeypatch.setattr(threading, "Thread", _Thread)

    view = _View(["repo-a"])
    assert view.show_prescan_sheet(None) is None

    assert view._prescan_active is True
    assert console.calls == [("show_activity", "Scanning structure...")]
    assert len(started) == 1

    started[0]()

    assert scan_calls == [(Path("/hub/repo-a"), 10)]
    assert len(delayed) == 1
    assert delayed[0][1] == 0
    assert console.calls[-1] == ("hide_activity",)


class _TextLabel:
    def __init__(self) -> None:
        self.text = None
        self.font = None
        self.text_color = None


class _Widget:
    def __init__(self, frame=None) -> None:
        self.subviews = []
        self._frame = (0, 0, 0, 0)
        self.width = 0
        self.height = 0
        self.closed = False
        self.presented = None
        if frame is not None:
            self.frame = frame

    @property
    def frame(self):
        return self._frame

    @frame.setter
    def frame(self, value) -> None:
        self._frame = value
        self.width = value[2]
        self.height = value[3]

    def add_subview(self, view) -> None:
        self.subviews.append(view)

    def present(self, style) -> None:
        self.presented = style
        _FakeUI.last_presented = self

    def close(self) -> None:
        self.closed = True


class _FakeView(_Widget):
    pass


class _FakeLabel(_Widget):
    def __init__(self, frame=None) -> None:
        super().__init__(frame)
        self.text = None
        self.text_color = None
        self.font = None


class _FakeButton(_Widget):
    def __init__(self, title=None) -> None:
        super().__init__()
        self.title = title
        self.action = None


class _FakeTableView(_Widget):
    def __init__(self) -> None:
        super().__init__()
        self.data_source = None
        self.delegate = None
        self.reload_count = 0

    def reload_data(self) -> None:
        self.reload_count += 1

    def delete_rows(self, rows) -> None:
        self.deleted_rows = list(rows)


class _FakeTableViewCell:
    def __init__(self, style=None) -> None:
        self.style = style
        self.text_label = _TextLabel()
        self.detail_text_label = _TextLabel()
        self.background_color = None
        self.accessory_type = None


class _FakeUI:
    View = _FakeView
    Label = _FakeLabel
    Button = _FakeButton
    TableView = _FakeTableView
    TableViewCell = _FakeTableViewCell
    ALIGN_CENTER = "center"
    alert_calls = []

    @staticmethod
    def alert(*args) -> None:
        _FakeUI.alert_calls.append(args)


def _prescan_tree():
    return {
        "path": ".",
        "type": "dir",
        "children": [
            {"path": "tests/test_x.py", "type": "file"},
            {
                "path": "src",
                "type": "dir",
                "children": [
                    {"path": "src/b.py", "type": "file"},
                    {"path": "src/a.py", "type": "file"},
                ],
            },
            {"path": "README.md", "type": "file"},
            {
                "path": "docs",
                "type": "dir",
                "children": [{"path": "docs/guide.md", "type": "file"}],
            },
        ],
    }


def _presented_prescan(monkeypatch, *, pool=None):
    monkeypatch.setattr(prescan_ui, "ui", _FakeUI, raising=False)
    monkeypatch.setattr(prescan_ui, "console", _Console(), raising=False)
    monkeypatch.setattr(prescan_ui, "normalize_path", lambda value: value, raising=False)
    monkeypatch.setattr(prescan_ui, "parse_human_size", lambda value: value, raising=False)
    view = _View(["repo-a"])
    view.saved_prescan_selections = {} if pool is None else {"repo-a": pool}
    view.saved_state_calls = 0
    view.save_last_state = lambda: setattr(view, "saved_state_calls", view.saved_state_calls + 1)
    view._prescan_active = True
    data = {
        "tree": _prescan_tree(),
        "root": "repo-a",
        "file_count": 5,
        "total_bytes": 2048,
    }
    _FakeUI.last_presented = None
    prescan_ui.MergerUIPrescanMixin._present_prescan_ui(view, data)
    return view, _FakeUI.last_presented


def _table_cells(sheet):
    table = next(widget for widget in sheet.subviews if isinstance(widget, _FakeTableView))
    ds = table.data_source
    return table, [ds.tableview_cell_for_row(table, 0, row) for row in range(ds.tableview_number_of_rows(table, 0))]


def test_present_prescan_ui_recommended_selection_and_sorted_tree(monkeypatch) -> None:
    view, sheet = _presented_prescan(monkeypatch)

    assert sheet.name == "Prescan: repo-a"
    assert sheet.presented == "sheet"
    table, cells = _table_cells(sheet)
    assert [cell.text_label.text.strip() for cell in cells] == [
        "📁 repo-a",
        "📁 docs",
        "📄 guide.md",
        "📁 src",
        "📄 a.py",
        "📄 b.py",
        "📄 README.md",
        "📄 test_x.py",
    ]
    assert [cell.accessory_type for cell in cells] == [
        "none",
        "none",
        "checkmark",
        "none",
        "checkmark",
        "checkmark",
        "checkmark",
        "none",
    ]
    assert table.reload_count == 0
    assert view._prescan_active is True


def test_present_prescan_ui_restores_directory_selection_from_pool(monkeypatch) -> None:
    _, sheet = _presented_prescan(
        monkeypatch, pool={"raw": ["src"], "compressed": ["src"]}
    )

    _, cells = _table_cells(sheet)
    selected = {
        cell.text_label.text.strip()
        for cell in cells
        if cell.accessory_type == "checkmark"
    }
    assert selected == {"📁 src", "📄 a.py", "📄 b.py"}


def test_present_prescan_ui_none_then_replace_clears_all_pool_state(monkeypatch) -> None:
    view, sheet = _presented_prescan(
        monkeypatch, pool={"raw": None, "compressed": None}
    )
    table, cells = _table_cells(sheet)
    assert all(cell.accessory_type == "checkmark" for cell in cells)

    none_button = next(widget for widget in sheet.subviews if getattr(widget, "title", None) == "None")
    none_button.action(none_button)
    assert table.reload_count == 1

    replace_button = next(
        widget for widget in sheet.subviews if getattr(widget, "title", None) == "Store (Replace)"
    )
    replace_button.action(replace_button)

    assert view.saved_prescan_selections == {}
    assert view.saved_state_calls == 1
    assert view._prescan_active is False
    assert sheet.closed is True


def test_present_prescan_ui_directory_toggle_updates_descendants(monkeypatch) -> None:
    _, sheet = _presented_prescan(monkeypatch)
    table, _ = _table_cells(sheet)
    data_source = table.data_source

    data_source.tableview_did_select(table, 0, 3)

    _, cells = _table_cells(sheet)
    selected = {
        cell.text_label.text.strip()
        for cell in cells
        if cell.accessory_type == "checkmark"
    }
    assert {"📁 src", "📄 a.py", "📄 b.py"} <= selected
    assert table.reload_count == 1


def _button(sheet, title):
    return next(widget for widget in sheet.subviews if getattr(widget, "title", None) == title)


def test_present_prescan_ui_remove_deletes_pool_and_closes(monkeypatch) -> None:
    view, sheet = _presented_prescan(
        monkeypatch, pool={"raw": ["README.md"], "compressed": ["README.md"]}
    )

    remove_button = _button(sheet, "Remove")
    remove_button.action(remove_button)

    assert view.saved_prescan_selections == {}
    assert view.saved_state_calls == 1
    assert view._prescan_active is False
    assert sheet.closed is True
    assert prescan_ui.console.calls[-1] == (
        "hud_alert", "Removed selection pool for repo-a", "success", 1.5
    )


def test_present_prescan_ui_replace_partial_materializes_directory(monkeypatch) -> None:
    view, sheet = _presented_prescan(
        monkeypatch, pool={"raw": ["src"], "compressed": ["src"]}
    )

    replace_button = _button(sheet, "Store (Replace)")
    replace_button.action(replace_button)

    assert view.saved_prescan_selections == {
        "repo-a": {
            "raw": ["src/a.py", "src/b.py"],
            "compressed": ["src"],
        }
    }
    assert view.saved_state_calls == 1
    assert view._prescan_active is False
    assert sheet.closed is True
    assert prescan_ui.console.calls[-1] == (
        "hud_alert", "Replaced selection pool for repo-a", "success", 1.5
    )


def test_present_prescan_ui_append_none_is_noop_and_stays_open(monkeypatch) -> None:
    original = {"raw": ["README.md"], "compressed": ["README.md"]}
    view, sheet = _presented_prescan(monkeypatch, pool=original.copy())

    none_button = _button(sheet, "None")
    none_button.action(none_button)
    append_button = _button(sheet, "Store (Append)")
    append_button.action(append_button)

    assert view.saved_prescan_selections == {"repo-a": original}
    assert view.saved_state_calls == 0
    assert view._prescan_active is True
    assert sheet.closed is False
    assert prescan_ui.console.calls[-1] == (
        "hud_alert", "No changes: no items selected in append mode", "error", 2.0
    )


def test_present_prescan_ui_append_partial_to_existing_all_keeps_all(monkeypatch) -> None:
    view, sheet = _presented_prescan(
        monkeypatch, pool={"raw": None, "compressed": None}
    )
    table, _ = _table_cells(sheet)

    _button(sheet, "None").action(_button(sheet, "None"))
    table.data_source.tableview_did_select(table, 0, 6)
    _button(sheet, "Store (Append)").action(_button(sheet, "Store (Append)"))

    assert view.saved_prescan_selections == {
        "repo-a": {"raw": None, "compressed": None}
    }
    assert view.saved_state_calls == 1
    assert view._prescan_active is False
    assert sheet.closed is True
    assert prescan_ui.console.calls[-1] == (
        "hud_alert", "Appended to selection pool for repo-a", "success", 1.5
    )


def test_present_prescan_ui_append_unions_and_recompresses_partial(monkeypatch) -> None:
    view, sheet = _presented_prescan(
        monkeypatch, pool={"raw": ["README.md"], "compressed": ["README.md"]}
    )
    table, _ = _table_cells(sheet)

    table.data_source.tableview_did_select(table, 0, 3)
    _button(sheet, "Store (Append)").action(_button(sheet, "Store (Append)"))

    assert view.saved_prescan_selections == {
        "repo-a": {
            "raw": ["README.md", "src/a.py", "src/b.py"],
            "compressed": ["src", "README.md"],
        }
    }
    assert view.saved_state_calls == 1
    assert view._prescan_active is False
    assert sheet.closed is True


def _presented_pool_viewer(monkeypatch, pool, *, use_console=True):
    monkeypatch.setattr(prescan_ui, "ui", _FakeUI, raising=False)
    console = _Console() if use_console else None
    monkeypatch.setattr(prescan_ui, "console", console, raising=False)
    view = _View([])
    view.saved_prescan_selections = pool
    view.saved_state_calls = 0
    view.repo_info_calls = 0
    view.save_last_state = lambda: setattr(
        view, "saved_state_calls", view.saved_state_calls + 1
    )
    view._update_repo_info = lambda: setattr(
        view, "repo_info_calls", view.repo_info_calls + 1
    )
    _FakeUI.last_presented = None
    _FakeUI.alert_calls = []
    view.show_pool_viewer(None)
    return view, _FakeUI.last_presented, console


def _pool_table(sheet):
    return next(widget for widget in sheet.subviews if isinstance(widget, _FakeTableView))


def test_show_pool_viewer_empty_pool_presents_empty_label(monkeypatch) -> None:
    _, sheet, _ = _presented_pool_viewer(monkeypatch, {})

    assert sheet.name == "Selection Pool"
    assert sheet.presented == "sheet"
    labels = [widget for widget in sheet.subviews if isinstance(widget, _FakeLabel)]
    assert len(labels) == 1
    assert labels[0].text == "Pool is empty."
    assert labels[0].alignment == _FakeUI.ALIGN_CENTER
    assert labels[0].text_color == "gray"


def test_show_pool_viewer_sorts_and_formats_rows(monkeypatch) -> None:
    pool = {
        "z-invalid": "legacy",
        "m-partial": {"raw": ["a", "b"], "compressed": ["src"]},
        "a-all": {"raw": None, "compressed": None},
    }
    _, sheet, _ = _presented_pool_viewer(monkeypatch, pool)
    table = _pool_table(sheet)
    ds = table.data_source

    cells = [
        ds.tableview_cell_for_row(table, 0, row)
        for row in range(ds.tableview_number_of_rows(table, 0))
    ]
    assert [(cell.text_label.text, cell.detail_text_label.text) for cell in cells] == [
        ("a-all", "ALL"),
        ("m-partial", "Partial: 2 files / 1 rules"),
        ("z-invalid", "Invalid state"),
    ]
    assert all(cell.accessory_type == "detail_button" for cell in cells)


def test_show_pool_viewer_inspector_limits_compressed_rules(monkeypatch) -> None:
    rules = [f"rule-{index:02d}" for index in range(16)]
    pool = {"repo-a": {"raw": ["a", "b"], "compressed": rules}}
    _, sheet, console = _presented_pool_viewer(monkeypatch, pool)
    table = _pool_table(sheet)

    table.data_source.tableview_did_select(table, 0, 0)

    assert console.calls[-1][0:3] == ("alert", "Pool Details", console.calls[-1][2])
    message = console.calls[-1][2]
    assert message.startswith("Repo: repo-a\n\nState: Partial\nFiles: 2\nRules: 16\n\nRules (Compressed):\n")
    assert "- rule-14\n" in message
    assert "rule-15" not in message
    assert message.endswith("... and 1 more")
    assert console.calls[-1][3] == "OK"
    assert console.calls[-1][4] == {"hide_cancel_button": True}


def test_show_pool_viewer_inspector_falls_back_to_ui_alert(monkeypatch) -> None:
    pool = {"repo-a": {"raw": None, "compressed": None}}
    _, sheet, _ = _presented_pool_viewer(monkeypatch, pool, use_console=False)
    table = _pool_table(sheet)

    table.data_source.tableview_accessory_button_tapped(table, 0, 0)

    assert _FakeUI.alert_calls == [
        ("Pool Details", "Repo: repo-a\n\nState: ALL files included.", "OK")
    ]


def test_show_pool_viewer_delete_persists_and_updates_info(monkeypatch) -> None:
    pool = {
        "repo-a": {"raw": None, "compressed": None},
        "repo-b": {"raw": ["x"], "compressed": ["x"]},
    }
    view, sheet, _ = _presented_pool_viewer(monkeypatch, pool)
    table = _pool_table(sheet)
    ds = table.data_source

    assert ds.tableview_can_edit(table, 0, 0) is True
    ds.tableview_delete(table, 0, 0)

    assert view.saved_prescan_selections == {
        "repo-b": {"raw": ["x"], "compressed": ["x"]}
    }
    assert view.saved_state_calls == 1
    assert view.repo_info_calls == 1
    assert table.deleted_rows == [0]
    assert ds.tableview_number_of_rows(table, 0) == 1


def test_show_pool_viewer_clear_pool_persists_updates_and_closes(monkeypatch) -> None:
    pool = {"repo-a": {"raw": None, "compressed": None}}
    view, sheet, console = _presented_pool_viewer(monkeypatch, pool)
    clear_button = next(
        widget for container in sheet.subviews for widget in getattr(container, "subviews", [])
        if getattr(widget, "title", None) == "Clear Pool"
    )

    clear_button.action(clear_button)

    assert view.saved_prescan_selections == {}
    assert view.saved_state_calls == 1
    assert view.repo_info_calls == 1
    assert sheet.closed is True
    assert console.calls[-1] == ("hud_alert", "Pool cleared")
