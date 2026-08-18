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
