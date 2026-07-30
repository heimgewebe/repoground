from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import Any


AppProvider = Callable[[], ModuleType]


class AttributeProxy:
    """Resolve one app-module attribute on every access.

    Tests and embedded callers historically replace ``service.app.state`` and
    selected security/Atlas collaborators. Routers use this proxy so those
    compatibility hooks keep affecting live requests after the split.
    """

    def __init__(self, provider: AppProvider, attribute: str) -> None:
        object.__setattr__(self, "_provider", provider)
        object.__setattr__(self, "_attribute", attribute)

    def _target(self) -> Any:
        return getattr(self._provider(), self._attribute)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._target(), name, value)

    def __bool__(self) -> bool:
        return bool(self._target())


def dynamic_callable(provider: AppProvider, attribute: str) -> Callable[..., Any]:
    """Return a callable that resolves its target from the app at call time."""

    def invoke(*args: Any, **kwargs: Any) -> Any:
        target = getattr(provider(), attribute)
        return target(*args, **kwargs)

    return invoke
