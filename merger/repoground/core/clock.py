"""
Central time source for lenskit.
Provides deterministic time for testing and consistent UTC timestamps.
Thread-safe and async-safe via contextvars.

Time is sourced from merger.repoground.core.clock.now_utc(); tests should prefer clock.frozen().
"""
import datetime
import contextlib
from typing import Optional, Generator
from contextvars import ContextVar

# ContextVar for thread/task-local storage of frozen time
_frozen_time_var: ContextVar[Optional[datetime.datetime]] = ContextVar("frozen_time", default=None)

def now_utc() -> datetime.datetime:
    """
    Returns the current time in UTC.
    If time is frozen (via `freeze_time` or `frozen` context), returns the frozen time.
    """
    frozen = _frozen_time_var.get()
    if frozen:
        return frozen
    return datetime.datetime.now(datetime.timezone.utc)

def freeze_time(dt: Optional[datetime.datetime]) -> None:
    """
    Freeze the time to a specific datetime for the current context.
    Pass None to unfreeze (resets to system time, does not restore previous frozen state).

    For scoped usage, prefer the `frozen()` context manager.

    Raises ValueError if dt is not timezone-aware and set to UTC.
    """
    if dt is not None:
        if dt.tzinfo != datetime.timezone.utc:
             # Strict UTC enforcement
             raise ValueError("Frozen time must be strictly UTC (tzinfo=datetime.timezone.utc)")

    _frozen_time_var.set(dt)

@contextlib.contextmanager
def frozen(dt: datetime.datetime) -> Generator[None, None, None]:
    """
    Context manager to safely freeze time for a block.
    Restores the previous time state upon exit.
    """
    # Validate first
    if dt.tzinfo != datetime.timezone.utc:
        raise ValueError("Frozen time must be strictly UTC (tzinfo=datetime.timezone.utc)")

    token = _frozen_time_var.set(dt)
    try:
        yield
    finally:
        _frozen_time_var.reset(token)
