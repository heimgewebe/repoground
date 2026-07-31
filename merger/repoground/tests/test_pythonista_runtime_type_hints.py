from pathlib import Path
import typing

from merger.repoground.frontends.pythonista.merger_ui_init import MergerUIInitMixin


def test_merger_ui_init_hub_type_hint_resolves_at_runtime() -> None:
    hints = typing.get_type_hints(MergerUIInitMixin.__init__)

    assert hints["hub"] is Path
    assert hints["return"] is type(None)
